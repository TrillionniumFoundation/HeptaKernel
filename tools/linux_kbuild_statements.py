#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Lossless Kbuild/Makefile source statements from one immutable Linux Git tree.

This is NOT a make evaluator, a dependency solver, or driver implementation.
Every physical source byte in each regular Kbuild source is retained in
ordered lexical statements; comments, rules and unknown forms are not dropped.
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
ASSIGN = re.compile(rb"^[ \t]*(?P<lhs>[^ \t\r\n:=]+)[ \t]*(?P<operator>[:+?]?=)[ \t]*(?P<rhs>[^\r\n]*)[ \t\r\n]*\Z")
CONFIG = re.compile(rb"CONFIG_[A-Za-z_0-9]+")
MAX_SOURCE = 32 * 1024 * 1024


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def encoded(path: bytes) -> dict:
    result = {"path_b64": base64.b64encode(path).decode("ascii")}
    try:
        result["path"] = path.decode("utf-8")
    except UnicodeDecodeError:
        result["path"] = None
    return result


def line(record: dict) -> bytes:
    return (json.dumps(record, sort_keys=True, ensure_ascii=True,
                       separators=(",", ":")) + "\n").encode("ascii")


def kbuild_path(path: bytes) -> bool:
    name = path.rsplit(b"/", 1)[-1]
    return name in (b"Makefile", b"Kbuild") or name.startswith(
        (b"Makefile.", b"Kbuild."))


def inventory(repo: Path, commit: str) -> list[dict]:
    result = []
    seen = set()
    raw = git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit)
    for field in raw.split(b"\0"):
        if not field:
            continue
        meta, tab, path = field.partition(b"\t")
        if tab != b"\t" or not path or path in seen:
            raise ValueError("malformed or repeated original tree path")
        seen.add(path)
        mode, typ, oid, size = meta.split()
        if not OID.fullmatch(oid) or typ not in (b"blob", b"commit"):
            raise ValueError("invalid immutable object type or id")
        if not kbuild_path(path):
            continue
        if typ == b"commit" and (mode != b"160000" or size != b"-"):
            raise ValueError("invalid Kbuild gitlink")
        if typ == b"blob" and (mode not in (b"100644", b"100755", b"120000")
                               or not size.isdigit()):
            raise ValueError("invalid Kbuild blob metadata")
        result.append({**encoded(path), "mode": mode.decode("ascii"),
                       "type": typ.decode("ascii"), "oid": oid.decode("ascii"),
                       "size": None if size == b"-" else int(size)})
    result.sort(key=lambda row: base64.b64decode(row["path_b64"]))
    return result


def physical_lines(blob: bytes) -> list[bytes]:
    parts = blob.split(b"\n")
    # Avoid phantom final empty line, preserve every byte incl. an unterminated
    # final line, embedded NUL, CRLF and non-UTF8 bytes.
    return [piece + b"\n" for piece in parts[:-1]] + (
        [parts[-1]] if parts[-1] else [])


def statements(blob: bytes, entry: dict):
    physical = physical_lines(blob)
    cursor = 0
    number = 1
    i = 0
    while i < len(physical):
        first, start = i, cursor
        raw = physical[i]
        cursor += len(physical[i])
        i += 1
        while raw.endswith((b"\\\n", b"\\\r\n")) and i < len(physical):
            raw += physical[i]
            cursor += len(physical[i])
            i += 1
        text = re.sub(rb"\\\r?\n[ \t]*", b" ", raw)
        stripped = text.strip()
        shape = ASSIGN.fullmatch(text)
        if not stripped:
            kind = "BLANK"
        elif stripped.startswith(b"#"):
            kind = "COMMENT"
        elif shape is not None:
            kind = "LEXICAL_ASSIGNMENT"
        else:
            kind = "OTHER_UNRESOLVED_MAKE_SYNTAX"
        result = {
            **encoded(base64.b64decode(entry["path_b64"])),
            "blob_oid": entry["oid"],
            "start_byte": start,
            "end_byte": cursor,
            "start_line": first + 1,
            "end_line": i,
            "raw_b64": base64.b64encode(raw).decode("ascii"),
            "status": kind,
            "lhs_b64": (base64.b64encode(shape["lhs"]).decode("ascii")
                        if shape else None),
            "operator": (shape["operator"].decode("ascii") if shape else None),
            "rhs_b64": (base64.b64encode(shape["rhs"]).decode("ascii")
                        if shape else None),
            "config_refs_b64": [
                base64.b64encode(ref).decode("ascii")
                for ref in sorted(set(CONFIG.findall(text)))
            ] if shape else [],
        }
        yield result
    if cursor != len(blob) or number != 1:
        raise ValueError("incomplete immutable Kbuild source byte traversal")


def build(repo: Path, lock: Path, destination: Path) -> dict:
    commit = json.loads(lock.read_bytes())["linux"]["commit"]
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("lock requires full lowercase Linux commit SHA")
    actual = git(repo, "rev-parse", "HEAD").strip().decode("ascii")
    if actual != commit:
        raise ValueError("HEAD mismatch with immutable Linux lock")
    if git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("locked Linux object is not a commit")
    tree = git(repo, "rev-parse", commit + "^{tree}").strip().decode("ascii")
    files = inventory(repo, commit)
    source = b"".join(line(entry) for entry in files)
    records = bytearray()
    counts = Counter()
    for entry in files:
        counts["kbuild_paths"] += 1
        if entry["mode"] not in ("100644", "100755"):
            counts["unreadable_paths"] += 1
            continue
        blob = git(repo, "cat-file", "blob", entry["oid"])
        if len(blob) != entry["size"] or len(blob) > MAX_SOURCE:
            raise ValueError("Kbuild blob size mismatch or explicit resource cap")
        counts["regular_sources"] += 1
        covered = 0
        for statement in statements(blob, entry):
            counts["statements"] += 1
            counts["status_" + statement["status"]] += 1
            counts["config_references_lexical"] += len(statement["config_refs_b64"])
            covered += statement["end_byte"] - statement["start_byte"]
            records.extend(line(statement))
        if covered != len(blob):
            raise ValueError("Kbuild byte coverage mismatch")
        counts["source_bytes"] += len(blob)
    content = bytes(records)
    report = {
        "schema": "heptakernel.linux-kbuild-lexical-source.v1",
        "status": "SOURCE_ONLY_NOT_KBUILD_EVALUATION",
        "linux_commit": commit,
        "linux_tree": tree,
        "files_file": "kbuild-files.jsonl",
        "files_sha256": hashlib.sha256(source).hexdigest(),
        "statements_file": "kbuild-statements.jsonl",
        "statements_sha256": hashlib.sha256(content).hexdigest(),
        "counts": dict(sorted(counts.items())),
        "all_regular_kbuild_bytes_retained": True,
        "kbuild_dependency_resolution": False,
        "active_kconfig_profiles_resolved": False,
        "driver_linkage_or_architecture_coverage_proven": False,
        "full_linux_rewrite_complete": False,
        "full_linux_acceptance": "HOLD",
        "limitations": [
            "Make variable expansion, conditionals, include semantics and
recursive object graph evaluation are not performed.".replace("\n", " "),
            "Assignments are lexical and their CONFIG mentions are not
preprocessor, Kconfig or runtime reachability results.".replace("\n", " "),
            "Regular source bytes are reproduced exactly from immutable blobs.
Nonregular links are recorded but not dereferenced.".replace("\n", " "),
            "The original 17 full-Linux gates and 422 syscall rows remain open.",
        ],
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "kbuild-files.jsonl").write_bytes(source)
    (destination / "kbuild-statements.jsonl").write_bytes(content)
    (destination / "report.json").write_bytes(
        json.dumps(report, sort_keys=True, indent=2).encode("ascii") + b"\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.repo, args.lock, args.out), sort_keys=True))


if __name__ == "__main__":
    main()
