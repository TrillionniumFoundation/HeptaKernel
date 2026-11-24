#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bind every inventory blob to its actual raw bytes, without following paths.

Git tree reconstruction binds modes, names, object identities, not sizes.
This pass rehashes the raw object payload with the Git blob header and an
independent SHA-256 content digest. Gitlinks are retained as external
commit obligations, not fetched or mistaken for verified file content.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_inventory_tree_identity import PINNED_COMMIT, PINNED_TREE, reconstruct

OID = re.compile(r"[0-9a-f]{40}")
CHUNK = 1 << 20


def expectations(leaves):
    blobs = {}
    gitlinks = []
    for row in leaves:
        oid, size, kind = row["oid"], row["size"], row["type"]
        if not isinstance(oid, str) or OID.fullmatch(oid) is None:
            raise ValueError("invalid object ID")
        if kind == "commit" and row["mode"] == "160000" and size is None:
            gitlinks.append({"path_b64": row["path_b64"], "oid": oid})
            continue
        if (kind != "blob" or row["mode"] not in ("100644", "100755", "120000")
                or type(size) is not int or size < 0):
            raise ValueError("invalid inventory blob size or type")
        entry = blobs.setdefault(oid, [size, 0])
        if entry[0] != size:
            raise ValueError("inconsistent size for duplicate blob " + oid)
        entry[1] += 1
    return blobs, gitlinks


def consume_batch(stream, blobs):
    for oid, (expected_size, count) in sorted(blobs.items()):
        header = stream.readline(256)
        expected_header = f"{oid} blob {expected_size}\n".encode("ascii")
        if header != expected_header:
            raise ValueError("missing, wrong-type, wrong-size or out-of-order blob " + oid)
        git_hash = hashlib.sha1(f"blob {expected_size}\0".encode("ascii"))
        content_hash = hashlib.sha256()
        remaining = expected_size
        while remaining:
            data = stream.read(min(remaining, CHUNK))
            if not data:
                raise ValueError("truncated blob " + oid)
            git_hash.update(data)
            content_hash.update(data)
            remaining -= len(data)
        if stream.read(1) != b"\n":
            raise ValueError("missing blob frame terminator " + oid)
        if git_hash.hexdigest() != oid:
            raise ValueError("Git blob identity mismatch " + oid)
        yield {"oid": oid, "size": expected_size, "paths": count,
               "content_sha256": content_hash.hexdigest()}
    if stream.read(1):
        raise ValueError("unexpected trailing Git batch output")


def audit_objects(repo, leaves):
    blobs, gitlinks = expectations(leaves)
    # Feed requests from a file instead of piping an unbounded list into a
    # blocked child while it is writing potentially large binary payloads.
    # Full OIDs only: do not resolve worktree paths, replace refs or lazy fetch.
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    with tempfile.TemporaryFile() as requests, tempfile.TemporaryFile() as errors:
        requests.write(b"".join(oid.encode("ascii") + b"\n" for oid in sorted(blobs)))
        requests.seek(0)
        process = subprocess.Popen(["git", "--no-replace-objects", "-C", str(repo),
                                    "cat-file", "--batch"],
                                   stdin=requests, stdout=subprocess.PIPE,
                                   stderr=errors, env=env)
        try:
            records = list(consume_batch(process.stdout, blobs))
            if process.wait(timeout=30) != 0:
                raise ValueError("Git batch child failed")
            errors.seek(0)
            if errors.read(1):
                raise ValueError("Git batch reported diagnostics")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=30)
            process.stdout.close()
    return records, gitlinks


def verify(repo, folder):
    env = dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    def git(*args):
        return subprocess.check_output(["git", "--no-replace-objects", "-C",
                                        str(repo), *args], env=env,
                                       timeout=30).strip().decode("ascii")
    report = json.loads((folder / "report.json").read_bytes())
    if (report["linux_commit"] != PINNED_COMMIT
            or report["linux_root_tree"] != PINNED_TREE
            or git("rev-parse", "HEAD") != PINNED_COMMIT
            or git("rev-parse", "HEAD^{tree}") != PINNED_TREE):
        raise ValueError("wrong pinned commit/tree")
    def read(name, field):
        raw = (folder / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != report[field]:
            raise ValueError("manifest digest mismatch: " + name)
        return list(map(json.loads, raw.splitlines()))
    leaves = read("source-paths.jsonl", "source_paths_sha256")
    directories = read("directory-objects.jsonl", "directory_objects_sha256")
    tree = reconstruct(leaves, directories, PINNED_TREE)
    records, gitlinks = audit_objects(repo, leaves)
    content = b"".join((json.dumps(record, sort_keys=True, separators=(",", ":"))
                         + "\n").encode("ascii") for record in records)
    target = folder / "blob-content-identities.jsonl"
    # Never publish a partly verified identity ledger on a failed child.
    with tempfile.NamedTemporaryFile(dir=folder, prefix=".blob-content-",
                                     delete=False) as temp:
        partial = Path(temp.name)
        try:
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
            temp.close()
            os.replace(partial, target)
        finally:
            if partial.exists():
                partial.unlink()
    return {"status": "PASS_PINNED_BLOB_CONTENT_IDENTITY_ONLY",
            "linux_commit": PINNED_COMMIT, **tree,
            "unique_blobs": len(records),
            "blob_paths": sum(x["paths"] for x in records),
            "unique_blob_bytes": sum(x["size"] for x in records),
            "path_blob_bytes": sum(x["size"] * x["paths"] for x in records),
            "external_gitlinks_unverified": gitlinks,
            "content_ledger": target.name,
            "content_ledger_sha256": hashlib.sha256(content).hexdigest(),
            "source_paths_sha256": report["source_paths_sha256"],
            "inventory_complete": False, "full_rewrite_complete": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.repo, args.inventory), sort_keys=True))
