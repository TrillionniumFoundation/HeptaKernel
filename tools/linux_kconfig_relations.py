#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Byte-origin, whole-tree Kconfig relation-line inventory (not Kconfig evaluation).

Lexical matching deliberately retains candidates inside help text and inactive
conditional blocks; they are not asserted to be semantic dependency edges.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

OID = re.compile(rb"[0-9a-f]{40}\Z")
PROPERTY = re.compile(
    rb"^[ \t]*(depends[ \t]+on|visible[ \t]+if|select|imply|default|"
    rb"range|prompt|def_bool|def_tristate)[ \t]+([^ \t\r].*)$"
)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def extract(data: bytes):
    """Every lexical property line with original physical offsets and bytes."""
    offset = 0
    for line_no, raw in enumerate(data.split(b"\n"), 1):
        matched = PROPERTY.match(raw)
        if matched:
            word = b" ".join(matched.group(1).split())
            yield {
                "line": line_no,
                "byte_at": offset + matched.start(1),
                "byte_end": offset + len(raw),
                "kind": word.decode("ascii").replace(" ", "_"),
                "operand_b64": base64.b64encode(matched.group(2)).decode("ascii"),
                "raw_b64": base64.b64encode(raw).decode("ascii"),
                "status": "LEXICAL_CANDIDATE_NOT_EVALUATED",
            }
        offset += len(raw) + 1


def collect(repo: Path, commit: str):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("full lowercase commit SHA required")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode():
        raise ValueError("pinned Linux HEAD mismatch")
    if git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("pinned Linux object is not commit")
    root = git(repo, "rev-parse", commit + "^{tree}").strip().decode()
    tree = git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit)
    records, seen, counts = [], set(), Counter()
    for entry in filter(None, tree.split(b"\0")):
        metadata, sep, path = entry.partition(b"\t")
        if not sep or not path or path in seen:
            raise ValueError("missing/duplicate Git path")
        seen.add(path)
        parts = metadata.split()
        if len(parts) != 4 or not OID.fullmatch(parts[2]):
            raise ValueError("malformed Git tree entry")
        mode, kind, oid, size = parts
        leaf = path.rsplit(b"/", 1)[-1]
        if not (leaf == b"Kconfig" or leaf.startswith(b"Kconfig.")):
            continue
        counts["kconfig_paths"] += 1
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            counts["unreadable_kconfig_paths"] += 1
            continue
        if not size.isdigit():
            raise ValueError("regular Kconfig blob missing Git size")
        original = git(repo, "cat-file", "blob", oid.decode("ascii"))
        if len(original) != int(size):
            raise ValueError("Kconfig blob size mismatch")
        counts["scanned_kconfig_paths"] += 1
        binding = {"path_b64": base64.b64encode(path).decode("ascii"),
                   "blob_oid": oid.decode("ascii")}
        for record in extract(original):
            counts[record["kind"]] += 1
            records.append({**binding, **record})
    if not seen or not records:
        raise ValueError("empty or invalid pinned Kconfig source inventory")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode():
        raise ValueError("Linux HEAD changed during source inventory")
    output = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        .encode("ascii") for row in records)
    counts["relation_line_candidates"] = len(records)
    report = {
        "schema": "heptakernel.linux-kconfig-relation-lines.v1",
        "status": "PARTIAL_LEXICAL_RELATIONS_NOT_RESOLVED_GRAPH",
        "linux_commit": commit, "linux_root_tree": root,
        "source_file": "kconfig-relation-lines.jsonl",
        "source_sha256": hashlib.sha256(output).hexdigest(),
        "counts": dict(sorted(counts.items())),
        "inventory_complete": False, "full_rewrite_complete": False,
        "limitations": [
            "Help text and inactive branches may yield lexical candidates",
            "Continuation lines, option scopes and source includes remain unevaluated",
            "No actual driver, architecture, ABI or Linux feature has been implemented",
        ],
    }
    return output, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--lock", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    lock = json.loads(args.lock.read_bytes())
    output, report = collect(args.repo, lock["linux"]["commit"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / report["source_file"]).write_bytes(output)
    (args.out / "kconfig-relation-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
