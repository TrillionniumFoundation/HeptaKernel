#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Byte-identity inventory of _IO* invocation-bearing UAPI #defines.

This is a lexical source obligation report, NOT ioctl-number evaluation,
preprocessor reachability, or a claim of Linux ioctl implementation.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_inventory import enumerate_entries, git, is_uapi, json_line

DEFINE = re.compile(rb"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)")
IO_CALL = re.compile(
    rb"(?<![A-Za-z0-9_])(_IO(?:WR|R|W|C)?(?:_BAD)?)[ \t\r\n]*\("
)
SHA1 = re.compile(r"[0-9a-f]{40}")


def continued(line: bytes) -> bool:
    # A C line splice is a backslash IMMEDIATELY followed by newline (CRLF
    # is retained as seen in the original blob); trailing spaces do not splice.
    return line.endswith(b"\\\n") or line.endswith(b"\\\r\n")


def scan_defines(data: bytes) -> list[dict]:
    """Parse complete logical #define line spans without C preprocessing."""
    lines = data.splitlines(keepends=True)
    offset = 0
    offsets = []
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    if offset != len(data):
        raise ValueError("source line-span coverage mismatch")
    result = []
    i = 0
    while i < len(lines):
        match = DEFINE.match(lines[i])
        if match is None:
            i += 1
            continue
        begin = i
        end = i
        while continued(lines[end]) and end + 1 < len(lines):
            end += 1
        raw = data[offsets[begin]:offsets[end] + len(lines[end])]
        # Only the replacement list is searched, not the function-like
        # macro's own name. Comment/inactive matches remain lexical.
        tail = raw[match.end():]
        names = [m.group(1).decode("ascii") for m in IO_CALL.finditer(tail)]
        if names:
            result.append({
                "macro": match.group(1).decode("ascii"),
                "start_byte": offsets[begin],
                "end_byte": offsets[end] + len(lines[end]),
                "start_line": begin + 1,
                "end_line": end + 1,
                "raw_b64": base64.b64encode(raw).decode("ascii"),
                "io_calls": names,
                "status": ("UNTERMINATED_CONTINUATION" if (
                    continued(lines[end]) or
                    (end == len(lines) - 1 and lines[end].endswith(b"\\") )
                ) else "LEXICAL_IO_CALL_NOT_EVALUATED"),
            })
        i = end + 1
    return result


def collect(repo: Path, lock: Path) -> tuple[bytes, dict]:
    pinned = json.loads(lock.read_text(encoding="utf-8"))["linux"]["commit"]
    if not isinstance(pinned, str) or not SHA1.fullmatch(pinned):
        raise ValueError("an exact pinned Linux commit is required")
    if git(repo, "rev-parse", "HEAD").strip() != pinned.encode():
        raise ValueError("pinned Linux HEAD mismatch")
    if git(repo, "cat-file", "-t", pinned) != b"commit\n":
        raise ValueError("pinned Linux commit object unavailable")
    tree = git(repo, "rev-parse", pinned + "^{tree}").strip().decode("ascii")

    rows = []
    count = Counter()
    for path, item in enumerate_entries(repo, pinned):
        if not is_uapi(path) or not path.endswith(b".h"):
            continue
        count["uapi_headers"] += 1
        if item["type"] != "blob" or item["mode"] not in ("100644", "100755"):
            count["unreadable_headers"] += 1
            continue
        blob = git(repo, "cat-file", "blob", item["oid"])
        if len(blob) != item["size"]:
            raise ValueError("pinned UAPI header Git blob size mismatch")
        count["readable_headers"] += 1
        for row in scan_defines(blob):
            count["ioctl_macro_definitions"] += 1
            count["ioctl_calls"] += len(row["io_calls"])
            count[row["status"]] += 1
            rows.append({
                "path_b64": base64.b64encode(path).decode("ascii"),
                "blob_oid": item["oid"],
                **row,
            })
    if not rows:
        raise ValueError("no UAPI _IO-family definitions found")
    if git(repo, "rev-parse", "HEAD").strip() != pinned.encode():
        raise ValueError("Linux HEAD changed during scan")
    data = b"".join(json_line(row) for row in rows)
    report = {
        "schema": "heptakernel.linux-uapi-ioctl-lexical.v1",
        "status": "PARTIAL_LEXICAL_NO_NUMBER_EVALUATION_OR_ABI_IMPLEMENTATION",
        "linux_commit": pinned, "linux_root_tree": tree,
        "source_file": "uapi-ioctl-macro-obligations.jsonl",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "records": len(rows), "counts": dict(sorted(count.items())),
        "inventory_complete": False, "full_rewrite_complete": False,
        "limitations": [
            "Only UAPI .h files and direct _IO/_IOR/_IOW/_IOWR/_IOC expressions are indexed",
            "Numeric constants, macro indirection, ABI reachability and #if conditions are not resolved",
            "Comments, malformed source and inactive branches are retained as lexical source candidates",
            "Definitions and invocation counts are not implemented ioctl commands",
        ],
    }
    return data, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data, report = collect(args.repo, args.lock)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / report["source_file"]).write_bytes(data)
    (args.out / "uapi-ioctl-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
