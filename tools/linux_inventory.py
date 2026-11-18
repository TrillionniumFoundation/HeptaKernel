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
# Lexically record every Kconfig include directive, without guessing how its
# environment variables, relative path or conditional reachability resolve.
SOURCE_EDGE = re.compile(rb"^[ \t]*(source|rsource|osource|orsource)[ \t]+(.+?)[ \t]*$")
OID = re.compile(rb"^[0-9a-f]{40}$")
# Source-line inventory only: no C preprocessing or claim of ABI reachability.
UAPI_DEFINE = re.compile(
    rb"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b"
)
# Lexical macro mentions only: this does not evaluate C preprocessing,
# recover table elements, or attest to PCI/USB/OF/ACPI device IDs.
DEVICE_TABLE = re.compile(
    rb"MODULE_DEVICE_TABLE[ \t]*\([ \t]*([A-Za-z_][A-Za-z0-9_]*)"
    rb"[ \t]*,[ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]*\)"
)


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


def is_syscall_table(path: bytes) -> bool:
    """Exact upstream syscall table path family, not an implementation."""
    return path == b"scripts/syscall.tbl" or (
        b"/syscalls/" in path and path.endswith(b".tbl")
    )


def is_abi_source(path: bytes) -> bool:
    return is_syscall_table(path) or path == b"include/uapi/asm-generic/unistd.h"



def enumerate_device_table_mentions(
        repo: Path, commit: str, entries: list[tuple[bytes, dict]]) -> bytes:
    """Find same-line MODULE_DEVICE_TABLE mentions in pinned C/H/Rust blobs.

    Git grep reads the immutable commit tree, not a mutable worktree. Its
    NUL-delimited path and line fields preserve newlines/non-UTF8 in names.
    A match in a comment or inactive conditional is deliberately retained.
    """
    command = [
        "git", "-C", str(repo), "grep", "--no-color", "-n", "-z",
        "-I", "-E", r"MODULE_DEVICE_TABLE[[:space:]]*\(",
        commit, "--", "*.c", "*.h", "*.rs",
    ]
    run = subprocess.run(command, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, check=False)
    if run.returncode not in (0, 1):
        raise RuntimeError("pinned device-table Git grep failed: " +
                           run.stderr.decode("utf-8", "replace"))
    by_path = {path: record for path, record in entries}
    prefix = commit.encode("ascii") + b":"
    records = []
    offset = 0
    while offset < len(run.stdout):
        path_end = run.stdout.find(b"\x00", offset)
        line_end = run.stdout.find(b"\x00", path_end + 1)
        text_end = run.stdout.find(b"\n", line_end + 1)
        if min(path_end, line_end, text_end) < 0:
            raise ValueError("truncated NUL-delimited Git grep match")
        tagged = run.stdout[offset:path_end]
        number = run.stdout[path_end + 1:line_end]
        raw = run.stdout[line_end + 1:text_end]
        if not tagged.startswith(prefix) or not number.isdigit() or int(number) < 1:
            raise ValueError("malformed immutable device-table match")
        path = tagged[len(prefix):]
        record = by_path.get(path)
        if not record or record["mode"] not in ("100644", "100755"):
            raise ValueError("device-table match absent from pinned regular blobs")
        match = DEVICE_TABLE.search(raw)
        records.append((path, int(number), {
            **encode_path(path), "blob_oid": record["oid"],
            "line": int(number),
            "raw_b64": base64.b64encode(raw).decode("ascii"),
            "status": "LEXICAL_ARGUMENTS" if match else "UNPARSED",
            "bus_b64": (base64.b64encode(match.group(1)).decode("ascii")
                        if match else None),
            "symbol_b64": (base64.b64encode(match.group(2)).decode("ascii")
                           if match else None),
        }))
        offset = text_end + 1
    records.sort(key=lambda row: (row[0], row[1]))
    if len({(p, line) for p, line, _ in records}) != len(records):
        raise ValueError("duplicate device-table source line")
    return b"".join(json_line(record) for _, _, record in records)




# A second, position-bound inventory includes multiline lexical invocations.
# Unlike the legacy same-line report, this records the exact byte span in the
# pinned Git blob; it does not claim preprocessor expansion or active drivers.
DEVICE_CALL_START = re.compile(rb"MODULE_DEVICE_TABLE[ \t\r\n]*\(")
DEVICE_CALL_FULL = re.compile(
    rb"MODULE_DEVICE_TABLE[ \t\r\n]*\([ \t\r\n]*"
    rb"([A-Za-z_][A-Za-z_0-9]*)[ \t\r\n]*,[ \t\r\n]*"
    rb"([A-Za-z_][A-Za-z_0-9]*)[ \t\r\n]*\)"
)
DEVICE_SPAN_LIMIT = 4096


def enumerate_device_table_invocations(
        repo: Path, commit: str, entries: list[tuple[bytes, dict]]) -> bytes:
    """Index same-line and multiline macro calls by immutable blob byte span.

    This lexer deliberately also retains comments and inactive #if branches.
    Arbitrarily long/malformed calls are marked TRUNCATED/UNPARSED rather
    than inferred from a different line or silently omitted.
    """
    command = [
        "git", "-C", str(repo), "grep", "--no-color", "-l", "-z",
        "-I", "-F", "MODULE_DEVICE_TABLE", commit,
        "--", "*.c", "*.h", "*.rs",
    ]
    listing = subprocess.run(command, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, check=False)
    if listing.returncode not in (0, 1):
        raise RuntimeError("pinned driver invocation Git grep failed: " +
                           listing.stderr.decode("utf-8", "replace"))
    records = []
    by_path = dict(entries)
    prefix = commit.encode("ascii") + b":"
    visited = set()
    for tagged in filter(None, listing.stdout.split(b"\x00")):
        if not tagged.startswith(prefix):
            raise ValueError("unexpected pinned driver grep prefix")
        path = tagged[len(prefix):]
        if path in visited:
            raise ValueError("duplicate pinned driver source file")
        visited.add(path)
        reference = by_path.get(path)
        if reference is None or reference["mode"] not in ("100644", "100755"):
            raise ValueError("driver candidate absent from pinned regular tree")
        blob = git(repo, "cat-file", "blob", reference["oid"])
        if len(blob) != reference["size"]:
            raise ValueError("driver source Git blob size mismatch")
        for start_match in DEVICE_CALL_START.finditer(blob):
            start = start_match.start()
            scan_end = min(len(blob), start_match.end() + DEVICE_SPAN_LIMIT)
            close = blob.find(b")", start_match.end(), scan_end)
            end = close + 1 if close >= 0 else scan_end
            raw = blob[start:end]
            parsed = DEVICE_CALL_FULL.fullmatch(raw) if close >= 0 else None
            status = ("TRUNCATED" if close < 0 else
                      "LEXICAL_ARGUMENTS" if parsed else "UNPARSED")
            records.append((path, start, {
                **encode_path(path),
                "blob_oid": reference["oid"],
                "start_byte": start,
                "end_byte": end,
                "start_line": blob.count(b"\n", 0, start) + 1,
                "end_line": blob.count(b"\n", 0, end - 1) + 1,
                "raw_b64": base64.b64encode(raw).decode("ascii"),
                "status": status,
                "bus_b64": (base64.b64encode(parsed.group(1)).decode("ascii")
                            if parsed else None),
                "symbol_b64": (base64.b64encode(parsed.group(2)).decode("ascii")
                               if parsed else None),
            }))
    records.sort(key=lambda item: (item[0], item[1]))
    if len({(path, byte) for path, byte, _ in records}) != len(records):
        raise ValueError("duplicate driver macro byte offset")
    return b"".join(json_line(record) for _, _, record in records)

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
    source_edge_lines = bytearray()
    syscall_rows = bytearray()
    uapi_macros = bytearray()
    source_edge_counts = Counter()
    uapi_lines = bytearray()
    directory_bytes = b"".join(json_line(record) for _, record in directories)
    path_counts = Counter()
    kconfig_declarations = 0
    kconfig_files = 0
    kconfig_unreadable = []
    kconfig_names = set()
    syscall_table_files = 0
    syscall_table_rows = 0
    syscall_table_unparsed_rows = 0
    unreadable_syscall_tables = []
    uapi_header_files = 0
    uapi_macro_rows = 0
    unreadable_uapi_headers = []
    for path, record in entries:
        source_lines.extend(json_line(record))
        path_counts["tracked_paths"] += 1
        path_counts["mode_" + record["mode"]] += 1
        if path.startswith(b"drivers/"):
            path_counts["driver_tree_entries"] += 1
        if is_uapi(path):
            path_counts["uapi_tree_entries"] += 1
            uapi_lines.extend(json_line(record))
            if path.endswith(b".h"):
                uapi_header_files += 1
                if record["mode"] not in ("100644", "100755"):
                    unreadable_uapi_headers.append(encode_path(path))
                else:
                    header = git(repo, "cat-file", "blob", record["oid"])
                    if len(header) != record["size"]:
                        raise ValueError("UAPI header Git blob size mismatch")
                    for number, raw in enumerate(header.split(b"\n"), 1):
                        macro = UAPI_DEFINE.match(raw)
                        if not macro:
                            continue
                        uapi_macro_rows += 1
                        uapi_macros.extend(json_line({
                            **encode_path(path), "blob_oid": record["oid"],
                            "line": number,
                            "name_b64": base64.b64encode(macro.group(1)).decode("ascii"),
                            "raw_b64": base64.b64encode(raw).decode("ascii"),
                            "status": "LEXICAL_DEFINE",
                        }))
        if is_abi_source(path):
            path_counts["selected_syscall_abi_sources"] += 1
        if is_syscall_table(path):
            syscall_table_files += 1
            if record["mode"] not in ("100644", "100755"):
                unreadable_syscall_tables.append(encode_path(path))
            else:
                blob = git(repo, "cat-file", "blob", record["oid"])
                if len(blob) != record["size"]:
                    raise ValueError("syscall table Git blob size mismatch")
                # Lossless rows, including formats we cannot interpret.
                for number, raw in enumerate(blob.split(b"\n"), start=1):
                    statement = raw.split(b"#", 1)[0].strip()
                    if not statement:
                        continue
                    columns = statement.split()
                    parsed = len(columns) >= 3
                    syscall_table_rows += 1
                    syscall_table_unparsed_rows += int(not parsed)
                    syscall_rows.extend(json_line({
                        **encode_path(path), "blob_oid": record["oid"],
                        "line": number,
                        "raw_b64": base64.b64encode(raw).decode("ascii"),
                        "columns_b64": [base64.b64encode(v).decode("ascii")
                                        for v in columns],
                        "status": "LEXICAL_ROW" if parsed else "UNPARSED",
                    }))
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
            edge = SOURCE_EDGE.match(line)
            if edge:
                kind = edge.group(1).decode("ascii")
                source_edge_counts[kind] += 1
                source_edge_lines.extend(json_line({
                    **encode_path(path),
                    "line": line_number,
                    "kind": kind,
                    "operand_b64": base64.b64encode(edge.group(2)).decode("ascii"),
                    "blob_oid": record["oid"],
                }))
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
    source_edges_bytes = bytes(source_edge_lines)
    uapi_bytes = bytes(uapi_lines)
    uapi_macro_bytes = bytes(uapi_macros)
    syscall_bytes = bytes(syscall_rows)
    device_table_bytes = enumerate_device_table_mentions(repo, pinned, entries)
    device_rows = [json.loads(line) for line in device_table_bytes.splitlines()]
    invocation_bytes = enumerate_device_table_invocations(repo, pinned, entries)
    invocation_rows = [json.loads(line) for line in invocation_bytes.splitlines()]
    report = {
        "schema": "heptakernel.pinned-linux-tree-inventory.v1",
        "status": "PARTIAL_SOURCE_INVENTORY_NOT_LINUX_IMPLEMENTATION",
        "linux_commit": pinned,
        "linux_root_tree": tree,
        "source_paths_file": "source-paths.jsonl",
        "source_paths_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "kconfig_declarations_file": "kconfig-declarations.jsonl",
        "kconfig_declarations_sha256": hashlib.sha256(kconfig_bytes).hexdigest(),
        "kconfig_source_edges_file": "kconfig-source-edges.jsonl",
        "kconfig_source_edges_sha256": hashlib.sha256(source_edges_bytes).hexdigest(),
        "directory_objects_file": "directory-objects.jsonl",
        "directory_objects_sha256": hashlib.sha256(directory_bytes).hexdigest(),
        "uapi_entries_file": "uapi-paths.jsonl",
        "uapi_entries_sha256": hashlib.sha256(uapi_bytes).hexdigest(),
        "uapi_macro_rows_file": "uapi-macro-rows.jsonl",
        "uapi_macro_rows_sha256": hashlib.sha256(uapi_macro_bytes).hexdigest(),
        "syscall_table_rows_file": "syscall-table-rows.jsonl",
        "syscall_table_rows_sha256": hashlib.sha256(syscall_bytes).hexdigest(),
        "module_device_table_mentions_file": "module-device-table-mentions.jsonl",
        "module_device_table_mentions_sha256": hashlib.sha256(device_table_bytes).hexdigest(),
        "module_device_table_invocations_file": "module-device-table-invocations.jsonl",
        "module_device_table_invocations_sha256": hashlib.sha256(invocation_bytes).hexdigest(),
        "counts": {
            **dict(sorted(path_counts.items())),
            "directory_tree_objects": len(directories),
            "kconfig_paths": kconfig_files,
            "kconfig_declarations": kconfig_declarations,
            "kconfig_source_edges": sum(source_edge_counts.values()),
            **{"kconfig_source_" + k: source_edge_counts[k]
               for k in ("source", "rsource", "osource", "orsource")},
            "distinct_kconfig_symbol_names": len(kconfig_names),
            "unparsed_kconfig_paths": len(kconfig_unreadable),
            "uapi_header_files": uapi_header_files,
            "uapi_macro_rows": uapi_macro_rows,
            "unreadable_uapi_header_files": len(unreadable_uapi_headers),
            "syscall_table_files": syscall_table_files,
            "syscall_table_rows": syscall_table_rows,
            "syscall_table_unparsed_rows": syscall_table_unparsed_rows,
            "unreadable_syscall_table_files": len(unreadable_syscall_tables),
            "module_device_table_mentions": len(device_rows),
            "module_device_table_unparsed": sum(
                row["status"] == "UNPARSED" for row in device_rows),
            "module_device_table_invocations": len(invocation_rows),
            "module_device_table_multiline": sum(
                row["end_line"] > row["start_line"] for row in invocation_rows),
            "module_device_table_invocations_unparsed": sum(
                row["status"] != "LEXICAL_ARGUMENTS" for row in invocation_rows),
        },
        "unparsed_kconfig": kconfig_unreadable,
        "unreadable_syscall_tables": unreadable_syscall_tables,
        "unreadable_uapi_headers": unreadable_uapi_headers,
        "limitations": [
            "Kconfig symbols and source edges are lexical only: no include expansion, "
            "dependency resolution, architecture selection or config satisfiability.",
            "UAPI macro rows cover tracked regular .h files only, without "
            "C preprocessing, #if reachability, continued-line expansion, "
            "struct layouts or arch-generated header semantics. Syscall rows "
            "are lexical, not executable dispatch. Driver IDs and device "
            "mappings remain unqualified.",
            "MODULE_DEVICE_TABLE mentions are lexical source references, not "
            "resolved hardware IDs or proven active driver match tables; "
            "same-line C/H/Rust text matches exclude binary blobs and "
            "multi-line calls and retain comments/inactive conditions.",
            "The separate position-bound invocation inventory includes multiline "
            "whitespace calls but is still lexical; function-like comments, "
            "preprocessor expansion, inactive branches, C tokens between macro "
            "name and parentheses, binary files, and spans beyond the bounded "
            "scan are not resolved to hardware IDs.",
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
    (destination / "kconfig-source-edges.jsonl").write_bytes(source_edges_bytes)
    (destination / "directory-objects.jsonl").write_bytes(directory_bytes)
    (destination / "uapi-paths.jsonl").write_bytes(uapi_bytes)
    (destination / "uapi-macro-rows.jsonl").write_bytes(uapi_macro_bytes)
    (destination / "syscall-table-rows.jsonl").write_bytes(syscall_bytes)
    (destination / "module-device-table-mentions.jsonl").write_bytes(device_table_bytes)
    (destination / "module-device-table-invocations.jsonl").write_bytes(invocation_bytes)
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
        "kconfig_source_edges_sha256": report["kconfig_source_edges_sha256"],
        "directory_objects_sha256": report["directory_objects_sha256"],
        "uapi_entries_sha256": report["uapi_entries_sha256"],
        "uapi_macro_rows_sha256": report["uapi_macro_rows_sha256"],
        "syscall_table_rows_sha256": report["syscall_table_rows_sha256"],
        "module_device_table_mentions_sha256": report["module_device_table_mentions_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
