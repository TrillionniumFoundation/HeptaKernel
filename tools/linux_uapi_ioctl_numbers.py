#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Strict x86-64 _IOC numeric *source candidates* from pinned UAPI lexical rows.

No C preprocessor, sizeof inference, host ioctl headers or arbitrary expression
evaluation. Unresolved invocations remain present and explicit. These numbers
are NOT evidence that a command is active, implemented, or supported.
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

# Python -I deliberately omits the executable directory from sys.path.
# Resolve only this sibling inventory tool, never host-installed modules.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_uapi_ioctl_macros import DEFINE, IO_CALL

INTEGER = re.compile(rb"(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([uUlL]*)\Z")
CHAR = re.compile(rb"'([^'\\]|\\[nrt0\\'])'\Z")
DIRECTIONS = {b"_IOC_NONE": 0, b"_IOC_WRITE": 1, b"_IOC_READ": 2}


def mask_comments(source: bytes) -> bytes:
    """Mask C comments without changing byte offsets or touching literals."""
    result = bytearray(source)
    i = 0
    quote = None
    while i < len(source):
        c = source[i]
        if quote is not None:
            if c == 92:
                for at in range(i, min(len(source), i + 2)):
                    if source[at] not in (10, 13):
                        result[at] = 32
                i += 2
                continue
            if c == quote:
                quote = None
            if c not in (10, 13):
                result[i] = 32
            i += 1
            continue
        if c in (34, 39):
            quote = c
            result[i] = 32
            i += 1
            continue
        if source[i:i + 2] == b"//":
            end = source.find(b"\n", i)
            if end < 0:
                end = len(source)
            for at in range(i, end):
                if source[at] not in (10, 13):
                    result[at] = 32
            i = end
            continue
        if source[i:i + 2] == b"/*":
            pos = source.find(b"*/", i + 2)
            end = len(source) if pos < 0 else pos + 2
            for at in range(i, end):
                if source[at] not in (10, 13):
                    result[at] = 32
            i = end
            continue
        i += 1
    return bytes(result)


def split_arguments(source: bytes, open_at: int) -> list[bytes] | None:
    """Only matching *literal* parentheses; no macros are expanded."""
    depth = 1
    begin = open_at + 1
    args = []
    quote = None
    i = begin
    while i < len(source):
        c = source[i]
        if quote is not None:
            if c == 92:
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in (34, 39):
            quote = c
        elif c == 40:
            depth += 1
        elif c == 41:
            depth -= 1
            if depth == 0:
                args.append(source[begin:i].strip())
                return args
        elif c == 44 and depth == 1:
            args.append(source[begin:i].strip())
            begin = i + 1
        i += 1
    return None


def literal(part: bytes) -> int | None:
    """Admit only a C integer, one-byte character or _IOC direction literal."""
    part = part.replace(b"\\\r\n", b"").replace(b"\\\n", b"").strip()
    while part.startswith(b"(") and part.endswith(b")"):
        # Peel only a balanced outer wrapper, never an expression.
        if split_arguments(part, 0) != [part[1:-1]]:
            break
        part = part[1:-1].strip()
    if part in DIRECTIONS:
        return DIRECTIONS[part]
    m = INTEGER.fullmatch(part)
    if m:
        value = m.group(1)
        base = 16 if value.lower().startswith(b"0x") else (
            8 if value.startswith(b"0") else 10)
        return int(value, base)
    m = CHAR.fullmatch(part)
    if m:
        token = m.group(1)
        if len(token) == 1:
            return token[0]
        return {b"\\n": 10, b"\\r": 13, b"\\t": 9, b"\\0": 0,
                b"\\\\": 92, b"\\'": 39}.get(token)
    return None


def project(name: str, args: list[bytes] | None) -> tuple[str, int | None]:
    if args is None:
        return "UNBALANCED_INVOCATION", None
    # Bad variants and typed _IOR/_IOW/_IOWR depend on sizeof/ABI type
    # semantics. Never silently use the current host's sizes.
    if name.endswith("_BAD"):
        return "ARCH_OR_SIZE_SEMANTICS_UNRESOLVED", None
    if name in ("_IOR", "_IOW", "_IOWR"):
        return "SIZEOF_TYPE_UNRESOLVED", None
    if name == "_IO" and len(args) == 2:
        numbers = [literal(p) for p in args]
        if None in numbers:
            return "EXPRESSION_UNRESOLVED", None
        typ, nr = numbers
        direction, size = 0, 0
    elif name == "_IOC" and len(args) == 4:
        numbers = [literal(p) for p in args]
        if None in numbers:
            return "EXPRESSION_UNRESOLVED", None
        direction, typ, nr, size = numbers
    else:
        return "ARITY_UNRESOLVED", None
    if not (0 <= direction < 4 and 0 <= typ < 256
            and 0 <= nr < 256 and 0 <= size < 16384):
        return "FIELD_RANGE_UNRESOLVED", None
    return "X86_64_GENERIC_NUMERIC_CANDIDATE", (
        (direction << 30) | (size << 16) | (typ << 8) | nr)


def project_row(row: dict) -> list[dict]:
    raw = base64.b64decode(row["raw_b64"], validate=True)
    define = DEFINE.match(raw)
    if define is None or define.group(1).decode("ascii") != row["macro"]:
        raise ValueError("original row is not its claimed macro")
    tail = raw[define.end():]
    masked = mask_comments(tail)
    hits = list(IO_CALL.finditer(tail))
    if [m.group(1).decode("ascii") for m in hits] != row["io_calls"]:
        raise ValueError("original lexical call inventory has diverged")
    result = []
    for ordinal, hit in enumerate(hits):
        name = hit.group(1).decode("ascii")
        start = define.end() + hit.start()
        # Regex consumes the opening parenthesis, whose offset is end()-1.
        if masked[hit.start():hit.start() + 1] == b" ":
            status, numeric = "NONCODE_LEXICAL_ONLY", None
        else:
            args = split_arguments(tail, hit.end() - 1)
            status, numeric = project(name, args)
        result.append({
            "path_b64": row["path_b64"], "blob_oid": row["blob_oid"],
            "source_start_byte": row["start_byte"],
            "source_end_byte": row["end_byte"],
            "macro": row["macro"], "ordinal": ordinal,
            "call": name, "source_call_byte": row["start_byte"] + start,
            "status": status, "number": numeric,
            "preprocessor_reachability_verified": False,
            "linux_ioctl_implementation_verified": False,
        })
    return result


def build(inventory: Path) -> tuple[bytes, dict]:
    source = (inventory / "uapi-ioctl-macro-obligations.jsonl").read_bytes()
    original = json.loads((inventory / "uapi-ioctl-report.json").read_bytes())
    if hashlib.sha256(source).hexdigest() != original["source_sha256"]:
        raise ValueError("pinned source inventory hash mismatch")
    rows = [json.loads(line) for line in source.splitlines()]
    if not rows or len(rows) != original["records"]:
        raise ValueError("missing or truncated original source inventory")
    result = []
    counter = Counter()
    for row in rows:
        projected = project_row(row)
        if len(projected) != len(row["io_calls"]):
            raise ValueError("dropped ioctl source invocation")
        result.extend(projected)
        counter.update(x["status"] for x in projected)
    if len(result) != original["counts"]["ioctl_calls"]:
        raise ValueError("numeric projection did not preserve source calls")
    data = b"".join((json.dumps(x, sort_keys=True, separators=(",", ":"))
                     + "\n").encode("ascii") for x in result)
    report = {
        "schema": "heptakernel.linux-uapi-ioctl-x86_64-candidates.v1",
        "status": "PARTIAL_X86_64_NUMERIC_SOURCE_CANDIDATES_NO_ABI_CLOSURE",
        "linux_commit": original["linux_commit"],
        "linux_root_tree": original["linux_root_tree"],
        "parent_source_sha256": original["source_sha256"],
        "projection_sha256": hashlib.sha256(data).hexdigest(),
        "source_rows": len(rows), "invocations": len(result),
        "counts": dict(sorted(counter.items())),
        "inventory_complete": False, "full_rewrite_complete": False,
        "limitations": [
            "No C preprocessor evaluation, active-config reachability or macro-expansion resolution",
            "Only literal _IO and _IOC integer/character operands receive candidate values",
            "Typed sizeof, ABI layouts and _BAD variants are explicitly unresolved",
            "x86-64 generic _IOC layout only; other architectures require separate profiles",
            "No command handler, compat translation or Linux ioctl implementation verified",
        ],
    }
    return data, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    a = parser.parse_args()
    data, report = build(a.inventory)
    (a.inventory / "uapi-ioctl-x86_64-candidates.jsonl").write_bytes(data)
    (a.inventory / "uapi-ioctl-x86_64-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("UAPI_IOCTL_X86_64_SOURCE_PROJECTION: PASS", report["invocations"],
          "numeric", report["counts"].get("X86_64_GENERIC_NUMERIC_CANDIDATE", 0))
    print("UAPI_IOCTL_REAL_ABI_IMPLEMENTATION: HOLD")


if __name__ == "__main__":
    main()
