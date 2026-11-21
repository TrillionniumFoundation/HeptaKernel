#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exact-source x86-64/x32 syscall table *obligation* projection.

The x32 dispatch set contains every 'common' row in syscall_64.tbl as well
as the separately numbered x32 rows. The x32 high bit is represented as a
dispatch-number encoding, not an implemented syscall. No libc, kernel
behavior, compat semantics, Kconfig activation or ENOSYS result is inferred.
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

TABLE = b"arch/x86/entry/syscalls/syscall_64.tbl"
X32_BIT = 0x40000000
NUM = re.compile(rb"(?:0|[1-9][0-9]*)\Z")
NAME = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, timeout=40,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def jsonl(rows: list[dict]) -> bytes:
    return b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
                    for row in rows)


def project(rows: list[dict]) -> tuple[bytes, bytes, dict]:
    """Project exactly one source row into each applicable dispatch ABI.

    Reject ambiguous numbers, invalid columns, duplicate source lines and
    number collisions. An absent kernel entry point remains explicitly absent.
    """
    native, x32 = [], []
    seen_numbers: set[int] = set()
    seen_lines: set[int] = set()
    categories = Counter()
    for row in rows:
        raw = decode(row["raw_b64"])
        fields = raw.partition(b"#")[0].split()
        if [encode(field) for field in fields] != row["columns_b64"] or row["status"] != "LEXICAL_ROW":
            raise ValueError("source row does not match immutable lexical ledger")
        if (len(fields) not in (3, 4, 6) or not NUM.fullmatch(fields[0])
                or fields[1] not in (b"common", b"64", b"x32")
                or not NAME.fullmatch(fields[2])
                or (len(fields) >= 4 and not NAME.fullmatch(fields[3]))
                or (len(fields) == 6 and (fields[4] != b"-" or fields[5] != b"noreturn"))):
            raise ValueError("unrecognized x86 syscall table row")
        number = int(fields[0])
        line = row["line"]
        if (number >= X32_BIT or number in seen_numbers or type(line) is not int
                or line <= 0 or line in seen_lines):
            raise ValueError("duplicate, invalid or out-of-range syscall number/line")
        seen_numbers.add(number)
        seen_lines.add(line)
        abi = fields[1].decode("ascii")
        categories[abi] += 1
        handler = fields[3].decode("ascii") if len(fields) >= 4 else None
        base = {
            "source_path_b64": encode(TABLE),
            "source_blob_oid": row["blob_oid"],
            "source_line": line,
            "source_raw_b64": row["raw_b64"],
            "source_abi": abi,
            "source_number": number,
            "name": fields[2].decode("ascii"),
            "declared_entry": handler,
            "entry_status": "DECLARED_ENTRY_NOT_IMPLEMENTED" if handler
                            else "NO_ENTRY_DECLARED",
            "noreturn_declaration": len(fields) == 6,
            "implementation_status": "NOT_IMPLEMENTED",
        }
        if abi in ("64", "common"):
            native.append({**base, "dispatch_abi": "x86_64", "dispatch_number": number})
        if abi in ("x32", "common"):
            x32.append({**base, "dispatch_abi": "x32", "dispatch_number": number | X32_BIT})
    if len(seen_numbers) != len(rows) or sum(categories.values()) != len(rows):
        raise ValueError("dropped x86 syscall source obligation")
    if (len(native) != categories["common"] + categories["64"]
            or len(x32) != categories["common"] + categories["x32"]):
        raise ValueError("incorrect x32 common-row inheritance")
    if len({r["dispatch_number"] for r in native}) != len(native) or len(
            {r["dispatch_number"] for r in x32}) != len(x32):
        raise ValueError("dispatch number alias")
    native_data, x32_data = jsonl(native), jsonl(x32)
    counts = {
        "original_source_rows": len(rows),
        "common_rows": categories["common"],
        "native_only_rows": categories["64"],
        "x32_only_rows": categories["x32"],
        "native_dispatch_obligations": len(native),
        "x32_dispatch_obligations": len(x32),
        "native_missing_declared_handler": sum(r["declared_entry"] is None for r in native),
        "x32_missing_declared_handler": sum(r["declared_entry"] is None for r in x32),
        "native_noreturn_declarations": sum(r["noreturn_declaration"] for r in native),
        "x32_noreturn_declarations": sum(r["noreturn_declaration"] for r in x32),
    }
    return native_data, x32_data, counts


def run(repo: Path, inventory: Path, lock_file: Path, vendor_file: Path) -> dict:
    lock = json.loads(lock_file.read_bytes())
    report = json.loads((inventory / "report.json").read_bytes())
    commit = lock["linux"]["commit"]
    if (git(repo, "rev-parse", "HEAD").strip().decode("ascii") != commit
            or report["linux_commit"] != commit
            or git(repo, "rev-parse", "HEAD^{tree}").strip().decode("ascii")
               != report["linux_root_tree"]):
        raise ValueError("pinned Linux HEAD/tree mismatch")
    paths_data = (inventory / "source-paths.jsonl").read_bytes()
    rows_data = (inventory / "syscall-table-rows.jsonl").read_bytes()
    if (digest(paths_data) != report["source_paths_sha256"]
            or digest(rows_data) != report["syscall_table_rows_sha256"]):
        raise ValueError("original inventory SHA-256 mismatch")
    targets = [record for record in map(json.loads, paths_data.splitlines())
               if decode(record["path_b64"]) == TABLE]
    if len(targets) != 1 or targets[0]["mode"] not in ("100644", "100755"):
        raise ValueError("missing regular pinned x86 syscall table")
    target = targets[0]
    blob = git(repo, "cat-file", "blob", target["oid"])
    if len(blob) != target["size"]:
        raise ValueError("pinned Git syscall blob size mismatch")
    vendor = vendor_file.read_bytes()
    if vendor == blob:
        vendor_status = "EXACT_GIT_BLOB"
    elif not blob.endswith(b"\n") and vendor == blob + b"\n":
        # The vendored fixture has one editorial trailing LF absent from the
        # locked upstream blob. Keep the *upstream* bytes authoritative.
        vendor_status = "VENDORED_EXTRA_TRAILING_LF"
    else:
        raise ValueError("unexpected vendored syscall content divergence")
    original = [rec for rec in map(json.loads, rows_data.splitlines())
                if decode(rec["path_b64"]) == TABLE]
    original_lines = [
        (number, raw) for number, raw in enumerate(blob.split(b"\n"), 1)
        if raw.partition(b"#")[0].strip()
    ]
    if len(original) != len(original_lines) or not original:
        raise ValueError("truncated x86 syscall source rows")
    for rec, (line, raw) in zip(original, original_lines):
        if (rec["blob_oid"] != target["oid"] or rec["line"] != line
                or decode(rec["raw_b64"]) != raw):
            raise ValueError("forged original syscall source row")
    if len(original) != lock["inventories"]["x86_64_table_rows"]:
        raise ValueError("pinned syscall count changed")
    native, x32, counts = project(original)
    if (counts["native_dispatch_obligations"] != lock["inventories"]["native_x86_64_table_rows"]
            or counts["x32_only_rows"] != lock["inventories"]["x32_special_table_rows"]):
        raise ValueError("original ABI lock disagrees with exact projection")
    if git(repo, "rev-parse", "HEAD").strip().decode("ascii") != commit:
        raise ValueError("Linux HEAD moved after ABI projection")
    result = {
        "schema": "heptakernel.x86-dual-syscall-source-obligations.v1",
        "status": "SOURCE_ONLY_NO_IMPLEMENTATION_OR_KCONFIG_EVALUATION",
        "linux_commit": commit,
        "linux_root_tree": report["linux_root_tree"],
        "source_blob_oid": target["oid"],
        "source_blob_sha256": digest(blob),
        "vendor_status": vendor_status,
        "vendor_sha256": digest(vendor),
        "source_ledger_sha256": digest(rows_data),
        "native_sha256": digest(native),
        "x32_sha256": digest(x32),
        "x32_dispatch_bit": X32_BIT,
        "counts": counts,
        "inventory_complete": False,
        "full_rewrite_complete": False,
        "limitations": [
            "Original 422 source rows remain intact and are not implementation counts",
            "The x32 ABI inherits common rows and separately numbers x32-specific rows",
            "No compat calling convention, generated syscall dispatch, Kconfig or behavior is evaluated",
            "No HIA syscall handlers, ELF userspace, or kernel privilege backend is implemented",
        ],
    }
    (inventory / "syscall-x86-native-obligations.jsonl").write_bytes(native)
    (inventory / "syscall-x32-obligations.jsonl").write_bytes(x32)
    (inventory / "syscall-x86-dual-report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--vendor", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.repo, args.inventory, args.lock, args.vendor), sort_keys=True))


if __name__ == "__main__":
    main()
