#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exact Git-object provenance for the pinned i386/IA32_EMULATION syscall ABI.

This is a source-obligation ledger, not a kernel syscall implementation.
The optional fifth column selects a separately declared compat entry; it
does not establish the actual Kconfig activation or calling convention.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess

TABLE = b"arch/x86/entry/syscalls/syscall_32.tbl"
NUM = re.compile(rb"(?:0|[1-9][0-9]*)\Z")
IDENT = re.compile(rb"[A-Za-z_][A-Za-z_0-9]*\Z")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def dec(data: str) -> bytes:
    return base64.b64decode(data, validate=True)


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args], check=True, timeout=40,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def jsonl(rows: list[dict]) -> bytes:
    return b"".join(
        (json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
        for r in rows
    )


def project(rows: list[dict], source_oid: str) -> tuple[bytes, dict]:
    """Project every numbered row; reject even one ambiguous or forged row."""
    seen_lines: set[int] = set()
    seen_numbers: set[int] = set()
    output = []
    for row in rows:
        raw = dec(row["raw_b64"])
        fields = raw.partition(b"#")[0].split()
        if (row["columns_b64"] != [enc(v) for v in fields]
                or row["status"] != "LEXICAL_ROW"
                or row["blob_oid"] != source_oid
                or not isinstance(row["line"], int)
                or isinstance(row["line"], bool)
                or row["line"] < 1 or row["line"] in seen_lines):
            raise ValueError("forged i386 lexical source row")
        if (len(fields) not in (3, 4, 5, 6)
                or not NUM.fullmatch(fields[0])
                or fields[1] != b"i386"
                or not IDENT.fullmatch(fields[2])
                or any(not IDENT.fullmatch(v) for v in fields[3:4])
                or (len(fields) >= 5 and fields[4] != b"-"
                    and not IDENT.fullmatch(fields[4]))
                or (len(fields) == 6 and
                    (fields[4] != b"-" or fields[5] != b"noreturn"))):
            raise ValueError("invalid i386 syscall columns")
        number = int(fields[0])
        if number >= (1 << 31) or number in seen_numbers:
            raise ValueError("duplicate or out-of-range i386 syscall number")
        seen_numbers.add(number)
        seen_lines.add(row["line"])
        primary = fields[3].decode("ascii") if len(fields) >= 4 else None
        override = (fields[4].decode("ascii") if len(fields) >= 5
                    and fields[4] != b"-" else None)
        selected = override or primary
        output.append({
            "source_path_b64": enc(TABLE),
            "source_blob_oid": source_oid,
            "source_line": row["line"],
            "source_raw_b64": row["raw_b64"],
            "source_abi": "i386",
            "source_number": number,
            "name": fields[2].decode("ascii"),
            "native_declared_entry": primary,
            "compat_declared_entry": override,
            "ia32_emulation_declared_entry": selected,
            "entry_selection": ("EXPLICIT_COMPAT_OVERRIDE" if override else
                                "PRIMARY_DECLARATION" if primary else
                                "NO_DECLARED_ENTRY"),
            "noreturn_declaration": len(fields) == 6,
            "implementation_status": "NOT_IMPLEMENTED",
        })
    if not output or len(output) != len(rows):
        raise ValueError("dropped i386 source row")
    counts = {
        "source_rows": len(rows),
        "missing_primary_entry": sum(r["native_declared_entry"] is None for r in output),
        "explicit_compat_overrides": sum(r["compat_declared_entry"] is not None for r in output),
        "noreturn_declarations": sum(r["noreturn_declaration"] for r in output),
        "max_source_number": max(r["source_number"] for r in output),
    }
    return jsonl(output), counts


def run(repo: Path, inventory: Path, lock_file: Path) -> dict:
    lock = json.loads(lock_file.read_bytes())
    summary = json.loads((inventory / "report.json").read_bytes())
    commit = lock["linux"]["commit"]
    head = git(repo, "rev-parse", "HEAD").strip().decode("ascii")
    root_tree = git(repo, "rev-parse", "HEAD^{tree}").strip().decode("ascii")
    if (head != commit or summary["linux_commit"] != commit
            or summary["linux_root_tree"] != root_tree):
        raise ValueError("pinned source HEAD/tree mismatch")
    paths_data = (inventory / "source-paths.jsonl").read_bytes()
    ledger_data = (inventory / "syscall-table-rows.jsonl").read_bytes()
    if (digest(paths_data) != summary["source_paths_sha256"]
            or digest(ledger_data) != summary["syscall_table_rows_sha256"]):
        raise ValueError("inventory provenance hash mismatch")
    matches = [r for r in map(json.loads, paths_data.splitlines())
               if dec(r["path_b64"]) == TABLE]
    if (len(matches) != 1 or matches[0]["type"] != "blob"
            or matches[0]["mode"] not in ("100644", "100755")):
        raise ValueError("i386 table missing or not a regular Git blob")
    item = matches[0]
    git_entry = git(repo, "ls-tree", "-z", commit, "--", TABLE.decode("ascii"))
    expected_entry = f"{item['mode']} blob {item['oid']}\t".encode("ascii") + TABLE + b"\x00"
    if git_entry != expected_entry:
        raise ValueError("i386 syscall table mode or object differs from pinned tree path")
    blob = git(repo, "cat-file", "blob", item["oid"])
    if len(blob) != item["size"]:
        raise ValueError("i386 source blob size mismatch")
    original = [r for r in map(json.loads, ledger_data.splitlines())
                if dec(r["path_b64"]) == TABLE]
    physical = [(i, raw) for i, raw in enumerate(blob.split(b"\n"), 1)
                if raw.partition(b"#")[0].strip()]
    if not physical or len(original) != len(physical):
        raise ValueError("i386 source ledger truncated")
    for row, (line, raw) in zip(original, physical):
        if row["line"] != line or dec(row["raw_b64"]) != raw:
            raise ValueError("i386 source ledger differs from pinned Git blob")
    output, counts = project(original, item["oid"])
    if (git(repo, "rev-parse", "HEAD").strip().decode("ascii") != commit
            or git(repo, "cat-file", "blob", item["oid"]) != blob):
        raise ValueError("i386 source changed during admission")
    result = {
        "schema": "heptakernel.ia32-syscall-source-obligations.v1",
        "status": "SOURCE_ONLY_NO_IMPLEMENTATION_OR_KCONFIG_EVALUATION",
        "linux_commit": commit,
        "linux_root_tree": root_tree,
        "source_blob_oid": item["oid"],
        "source_blob_sha256": digest(blob),
        "source_ledger_sha256": digest(ledger_data),
        "ia32_sha256": digest(output),
        "counts": counts,
        "inventory_complete": False,
        "full_rewrite_complete": False,
        "limitations": [
            "i386 source numbering and IA32_EMULATION declarations are not implemented handlers",
            "The optional compat override is a source declaration, not verified dispatch",
            "No Kconfig evaluation, ptrace ABI, register/errno translation, or userspace tests",
            "The separate x86_64 422-row and x32 obligations remain unchanged",
        ],
    }
    (inventory / "syscall-ia32-obligations.jsonl").write_bytes(output)
    (inventory / "syscall-ia32-report.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.repo, args.inventory, args.lock), sort_keys=True))


if __name__ == "__main__":
    main()
