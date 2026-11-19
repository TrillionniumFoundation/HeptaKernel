#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Byte-position-bound lexical C tag inventory for the pinned Linux UAPI tree.

This is a source inventory, not a C parser, preprocessor, reachable ABI or
HIA implementation. All comment/string tokens are excluded and all #if
branches remain visible. Reads immutable Git blobs, never worktree headers.
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
IDENT = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")
KEYWORDS = frozenset((b"struct", b"union", b"enum"))
SPACE = b" \t\r\n\v\f"


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *arguments],
                          check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE).stdout


def logical_bytes(data: bytes):
    """C phase-2 backslash/newline splicing with original byte offsets.

    Retain physical offsets even for keywords and names split across lines.
    This handles LF and CRLF, not trigraph replacement or preprocessing.
    """
    logical = bytearray()
    origins = []
    i, n = 0, len(data)
    while i < n:
        if data[i] == 92 and i + 1 < n and data[i + 1] == 10:
            i += 2
            continue
        if data[i] == 92 and data[i + 1:i + 3] == b"\r\n":
            i += 3
            continue
        logical.append(data[i])
        origins.append(i)
        i += 1
    return bytes(logical), origins


def tokens(data: bytes):
    """Yield (physical byte start, physical span length, logical token).

    Perform line splicing before comment/literal lexing. For a spliced token
    the original bytes span a larger interval than the logical token.
    """
    logical, origins = logical_bytes(data)
    i, n = 0, len(logical)
    while i < n:
        start, c = i, logical[i]
        if c in SPACE:
            i += 1
            continue
        if logical.startswith(b"//", i):
            end = logical.find(b"\n", i + 2)
            i = n if end < 0 else end + 1
            continue
        if logical.startswith(b"/*", i):
            end = logical.find(b"*/", i + 2)
            if end < 0:
                raise ValueError("unterminated UAPI block comment at byte "
                                 + str(origins[i]))
            i = end + 2
            continue
        if c in (34, 39):
            quote = c
            i += 1
            while i < n:
                if logical[i] == 92:
                    i += 2
                elif logical[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
            else:
                raise ValueError("unterminated UAPI literal at byte "
                                 + str(origins[start]))
            if i > n:
                raise ValueError("truncated UAPI literal escape")
            continue
        if 65 <= c <= 90 or 97 <= c <= 122 or c == 95:
            i += 1
            while i < n:
                v = logical[i]
                if (65 <= v <= 90 or 97 <= v <= 122 or 48 <= v <= 57
                        or v == 95):
                    i += 1
                else:
                    break
            yield origins[start], origins[i - 1] + 1 - origins[start], logical[start:i]
            continue
        yield origins[i], 1, logical[i:i + 1]
        i += 1

def extract(data: bytes):
    """Record every lexical struct/union/enum tag, including anonymous ones."""
    words = list(tokens(data))
    for index, (at, raw_len, word) in enumerate(words):
        if word not in KEYWORDS:
            continue
        name_at, name_raw_len, name, classification = None, None, None, "UNPARSED_TAG"
        if index + 1 < len(words):
            next_at, next_raw_len, next_word = words[index + 1]
            if IDENT.fullmatch(next_word):
                name_at, name_raw_len, name = next_at, next_raw_len, next_word
                follow = words[index + 2][1] if index + 2 < len(words) else b""
                classification = ("NAMED_DEFINITION" if follow == b"{" else
                                  "NAMED_FORWARD_OR_ELABORATED" if follow == b";" else
                                  "NAMED_REFERENCE_OR_MACRO")
            elif next_word == b"{":
                classification = "ANONYMOUS_DEFINITION"
        yield {"byte_at": at, "raw_span": raw_len,
               "line": data.count(b"\n", 0, at) + 1,
               "tag": word.decode("ascii"), "name_byte_at": name_at,
               "name_raw_span": name_raw_len,
               "name_b64": base64.b64encode(name).decode("ascii") if name else None,
               "classification": classification}


def collect(repo: Path, commit: str):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise ValueError("full lowercase commit pin required")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode():
        raise ValueError("repository HEAD differs from pinned Linux commit")
    if git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("pinned Linux object is not a commit")
    tree = git(repo, "rev-parse", commit + "^{tree}").strip().decode("ascii")
    listing = git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit)
    seen = set()
    records = []
    counts = Counter()
    for row in filter(None, listing.split(b"\0")):
        metadata, sep, path = row.partition(b"\t")
        if not sep or not path or path in seen:
            raise ValueError("missing/duplicate source path in Git tree")
        seen.add(path)
        fields = metadata.split()
        if len(fields) != 4 or not OID.fullmatch(fields[2]):
            raise ValueError("malformed immutable Git tree row")
        mode, kind, oid, size = fields
        if (kind not in (b"blob", b"commit")
                or mode not in (b"100644", b"100755", b"120000", b"160000")):
            raise ValueError("unexpected Git tree type/mode")
        parts = path.split(b"/")
        uapi = (len(parts) >= 3 and parts[:2] == [b"include", b"uapi"]) or (
            len(parts) >= 5 and parts[0] == b"arch"
            and parts[2:4] == [b"include", b"uapi"])
        if not (uapi and path.endswith(b".h")):
            continue
        counts["headers"] += 1
        if mode not in (b"100644", b"100755") or kind != b"blob":
            counts["unreadable_headers"] += 1
            continue
        if not size.isdigit():
            raise ValueError("header without immutable blob size")
        data = git(repo, "cat-file", "blob", oid.decode("ascii"))
        if len(data) != int(size):
            raise ValueError("header blob size mismatch")
        header = {"path_b64": base64.b64encode(path).decode("ascii"),
                  "blob_oid": oid.decode("ascii")}
        for row in extract(data):
            record = {**header, **row}
            records.append(record)
            counts[row["classification"]] += 1
    if not seen:
        raise ValueError("empty pinned Linux tree")
    # Git ls-tree returns paths in immutable byte order; keep positions stable.
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode():
        raise ValueError("HEAD changed during source inventory")
    if not records:
        raise ValueError("no UAPI tag tokens in pinned tree")
    output = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                      .encode("ascii") for row in records)
    return output, {"schema": "heptakernel.linux-uapi-tag-lexical.v2",
                    "status": "PARTIAL_SOURCE_LEXICAL_NOT_ABI_IMPLEMENTATION",
                    "linux_commit": commit, "linux_root_tree": tree,
                    "source_file": "uapi-tag-mentions.jsonl",
                    "source_sha256": hashlib.sha256(output).hexdigest(),
                    "records": len(records), "counts": dict(sorted(counts.items())),
                    "inventory_complete": False, "full_rewrite_complete": False,
                    "limitations": [
                        "Includes inactive conditional branches and macro tokens",
                        "Names, layout, reachability, typedef aliases and ABI export are not resolved",
                        "Unparsed tag contexts are retained; no Linux compatibility gate is closed"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    commit = lock["linux"]["commit"]
    source, report = collect(args.repo, commit)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / report["source_file"]).write_bytes(source)
    (args.out / "uapi-tag-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
