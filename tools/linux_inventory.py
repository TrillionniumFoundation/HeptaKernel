#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Enumerate the *entire* pinned Linux Git tree without lossy path parsing.

This is a source/Kconfig lexical inventory, NOT a Linux implementation or a
complete dependency, ABI, driver-ID, device, or behavioral inventory.
Output consists of immutable-object identities and raw-byte-safe paths.
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

DECLARATION = re.compile(rb"^[ \t]*(config|menuconfig)[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b")
OID = re.compile(rb"^[0-9a-f]{40}$")


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def json_line(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("ascii")


def encode_path(path: bytes) -> dict:
    value = {"path_b64": base64.b64encode(path).decode("ascii")}
    try:
        value["path"] = path.decode("utf-8")
    except UnicodeDecodeError:
        value["path"] = None
    return value


def enumerate_entries(repo: Path, commit: str) -> list[tuple[bytes, dict]]:
    raw = git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit)
    seen = set()
    result = []
    for entry in raw.split(b"\x00"):
        if not entry:
            continue
        metadata, separator, path = entry.partition(b"\t")
        if separator != b"\t" or not path or path in seen:
            raise ValueError("malformed or duplicated Git tree path")
        seen.add(path)
        fields = metadata.split()
        if len(fields) != 4:
            raise ValueError("invalid ls-tree -l entry")
        mode, kind, oid, size = fields
        if not OID.fullmatch(oid) or kind not in (b"blob", b"commit"):
            raise ValueError("unsupported Git tree entry")
        if (kind == b"commit") != (mode == b"160000"):
            raise ValueError("Gitlink type/mode mismatch")
        if kind == b"blob" and mode not in (b"100644", b"100755", b"120000"):
            raise ValueError("unsupported Git blob mode")
        if size != b"-" and not size.isdigit():
            raise ValueError("malformed Git size")
        if kind == b"blob" and size == b"-":
            raise ValueError("blob missing size")
        if kind == b"commit" and size != b"-":
            raise ValueError("gitlink must not advertise file bytes")
        record = {
            **encode_path(path),
            "mode": mode.decode("ascii"),
            "type": kind.decode("ascii"),
            "oid": oid.decode("ascii"),
            "size": None if size == b"-" else int(size),
        }
        result.append((path, record))
    result.sort(key=lambda item: item[0])
    if not result:
        raise ValueError("empty Git tree")
    return result



def enumerate_directory_objects(repo: Path, commit: str) -> list[tuple[bytes, dict]]:
    """All recursive directory names and exact immutable tree object IDs."""
    raw = git(repo, "ls-tree", "--full-tree", "-r", "-t", "-z", commit)
    result = []
    seen = set()
    for entry in raw.split(b"\x00"):
        if not entry:
            continue
        metadata, separator, path = entry.partition(b"\t")
        if separator != b"\t" or not path:
            raise ValueError("malformed recursive Git directory entry")
        parts = metadata.split()
        if len(parts) != 3:
            raise ValueError("malformed recursive Git directory metadata")
        mode, kind, oid = parts
        if kind != b"tree":
            continue
        if mode != b"040000" or not OID.fullmatch(oid) or path in seen:
            raise ValueError("invalid or duplicate directory object")
        seen.add(path)
        result.append((path, {**encode_path(path), "mode": "040000",
                              "type": "tree", "oid": oid.decode("ascii")}))
    result.sort(key=lambda item: item[0])
    return result


def is_kconfig(path: bytes) -> bool:
    base = path.rsplit(b"/", 1)[-1]
    return base == b"Kconfig" or base.startswith(b"Kconfig.")


def is_uapi(path: bytes) -> bool:
    parts = path.split(b"/")
    return ((len(parts) >= 3 and parts[:2] == [b"include", b"uapi"])
            or (len(parts) >= 5 and parts[0] == b"arch"
                and parts[2:4] == [b"include", b"uapi"]))


def is_abi_source(path: bytes) -> bool:
    return (b"/syscalls/" in path and path.endswith(b".tbl")) or (
        path in (b"scripts/syscall.tbl", b"include/uapi/asm-generic/unistd.h")
    )


def build(repo: Path, lock: Path, destination: Path) -> dict:
    pinned = json.loads(lock.read_text(encoding="utf-8"))["linux"]["commit"]
    if not isinstance(pinned, str) or not re.fullmatch(r"[0-9a-f]{40}", pinned):
        raise ValueError("lock must contain a full lowercase Git SHA-1 commit")
    actual = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    if actual != pinned:
        raise ValueError(f"HEAD mismatch: pinned={pinned} actual={actual}")
    if git(repo, "cat-file", "-t", pinned) != b"commit\n":
        raise ValueError("pinned object is not a Git commit")
    tree = git(repo, "rev-parse", f"{pinned}^{{tree}}").decode("ascii").strip()
    entries = enumerate_entries(repo, pinned)
    directories = enumerate_directory_objects(repo, pinned)

    source_lines = bytearray()
    kconfig_lines = bytearray()
    uapi_lines = bytearray()
    directory_bytes = b"".join(json_line(record) for _, record in directories)
    path_counts = Counter()
    kconfig_declarations = 0
    kconfig_files = 0
    kconfig_unreadable = []
    kconfig_names = set()
    for path, record in entries:
        source_lines.extend(json_line(record))
        path_counts["tracked_paths"] += 1
        path_counts["mode_" + record["mode"]] += 1
        if path.startswith(b"drivers/"):
            path_counts["driver_tree_entries"] += 1
        if is_uapi(path):
            path_counts["uapi_tree_entries"] += 1
            uapi_lines.extend(json_line(record))
        if is_abi_source(path):
            path_counts["selected_syscall_abi_sources"] += 1
        if not is_kconfig(path):
            continue
        kconfig_files += 1
        if record["mode"] not in ("100644", "100755"):
            kconfig_unreadable.append(encode_path(path))
            continue
        # Read the exact object named by the Git tree, never mutable worktree
        # contents; do not use host filesystem path decoding or symlink traversal.
        contents = git(repo, "cat-file", "blob", record["oid"])
        if len(contents) != record["size"]:
            raise ValueError("Kconfig blob size mismatch")
        for line_number, line in enumerate(contents.splitlines(), start=1):
            match = DECLARATION.match(line)
            if not match:
                continue
            name = match.group(2).decode("ascii")
            kconfig_names.add(name)
            kconfig_declarations += 1
            kconfig_lines.extend(json_line({
                **encode_path(path),
                "line": line_number,
                "kind": match.group(1).decode("ascii"),
                "symbol": name,
                "blob_oid": record["oid"],
            }))

    source_bytes = bytes(source_lines)
    kconfig_bytes = bytes(kconfig_lines)
    uapi_bytes = bytes(uapi_lines)
    report = {
        "schema": "heptakernel.pinned-linux-tree-inventory.v1",
        "status": "PARTIAL_SOURCE_INVENTORY_NOT_LINUX_IMPLEMENTATION",
        "linux_commit": pinned,
        "linux_root_tree": tree,
        "source_paths_file": "source-paths.jsonl",
        "source_paths_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "kconfig_declarations_file": "kconfig-declarations.jsonl",
        "kconfig_declarations_sha256": hashlib.sha256(kconfig_bytes).hexdigest(),
        "directory_objects_file": "directory-objects.jsonl",
        "directory_objects_sha256": hashlib.sha256(directory_bytes).hexdigest(),
        "uapi_entries_file": "uapi-paths.jsonl",
        "uapi_entries_sha256": hashlib.sha256(uapi_bytes).hexdigest(),
        "counts": {
            **dict(sorted(path_counts.items())),
            "directory_tree_objects": len(directories),
            "kconfig_paths": kconfig_files,
            "kconfig_declarations": kconfig_declarations,
            "distinct_kconfig_symbol_names": len(kconfig_names),
            "unparsed_kconfig_paths": len(kconfig_unreadable),
        },
        "unparsed_kconfig": kconfig_unreadable,
        "limitations": [
            "Kconfig symbols are lexical declarations only: no includes, "
            "dependency resolution, architecture selection or config satisfiability.",
            "UAPI and syscall sources are path inventories, not parsed ABI or "
            "structure layouts; driver IDs and devices are not yet mapped.",
            "Tracked blobs, symlinks and gitlinks are all included; generated "
            "files, external submodules, firmware and runtime behavior are not.",
            "The 17 full-acceptance gates and 422 x86-64 baseline syscall "
            "obligations remain unchanged and unverified.",
        ],
        "inventory_complete": False,
        "linux_full_rewrite_complete": False,
    }
    destination.mkdir(parents=True, exist_ok=True)
    # Write the provenance report last so a missing/truncated output cannot
    # accidentally be paired with a complete-looking report.
    (destination / "source-paths.jsonl").write_bytes(source_bytes)
    (destination / "kconfig-declarations.jsonl").write_bytes(kconfig_bytes)
    (destination / "directory-objects.jsonl").write_bytes(directory_bytes)
    (destination / "uapi-paths.jsonl").write_bytes(uapi_bytes)
    (destination / "report.json").write_bytes(
        json.dumps(report, ensure_ascii=True, sort_keys=True,
                   indent=2).encode("ascii") + b"\n"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path,
                        default=Path("compatibility/linux-source-lock.json"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.repo.resolve(), args.lock.resolve(), args.out.resolve())
    print(json.dumps({
        "status": report["status"],
        "linux_commit": report["linux_commit"],
        "linux_root_tree": report["linux_root_tree"],
        "counts": report["counts"],
        "source_paths_sha256": report["source_paths_sha256"],
        "kconfig_declarations_sha256": report["kconfig_declarations_sha256"],
        "directory_objects_sha256": report["directory_objects_sha256"],
        "uapi_entries_sha256": report["uapi_entries_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
