#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial fixture for exact Git-tree source inventory, without a network."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("linux_inventory", ROOT / "tools/linux_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def put(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)


def fixture(root: Path) -> tuple[str, Path]:
    root.mkdir()
    git(root, "init", "-q")
    put(root, "arch/x86/Kconfig",
        "# config COMMENTED\n"
        "config CORE\n"
        "\tbool \"Core\"\n"
        "menuconfig MENU\n"
        "  config CORE\n"
        "source \"other/Kconfig\"\n"
        "rsource \"sub/Kconfig\"\n"
        "osource \"$OPTIONAL/Kconfig\"\n"
        "orsource \"maybe/Kconfig\"\n"
        "# source \"ignored/Kconfig\"\n"
        "  source \"nested/with#symbol/Kconfig\"  \n")
    put(root, "arch/x86/Kconfig.extra", "  config SECOND\n")
    put(root, "include/uapi/linux/demo.h",
        "int feature;\n"
        "#define UAPI_NUMBER 42\n"
        " #  define UAPI_CALL(x) ((x) + 1) \\\n"
        "    + 3\n"
        "// #define COMMENTED 1\n"
        "#if 0\n"
        "#define INACTIVE 3\n"
        "#endif\n")
    put(root, "arch/x86/include/uapi/asm/unistd.h",
        "/* abi */\n# define _NR_foo 7\n")
    put(root, "arch/x86/entry/syscalls/syscall_64.tbl", "0 common read sys_read\n"
        "1 common write sys_write # inline comment\n"
        "# 2 common ignored sys_ignored\n"
        "broken\n"
        "3 x32 mmap sys_mmap compat_sys_mmap\n")
    put(root, "drivers/net/demo.c",
        "/* driver */\\n"
        "MODULE_DEVICE_TABLE(pci, demo_ids);\\n"
        "// MODULE_DEVICE_TABLE(usb, commented_ids);\\n"
        "MODULE_DEVICE_TABLE(weird, );\\n"
        "MODULE_DEVICE_TABLE (of, other_ids);\\n")
    put(root, "with\\backslash.c", "test\n")
    put(root, "line\nfeed.c", "test\n")
    (root / "alias").symlink_to("arch/x86/Kconfig")
    opaque_name = os.fsencode(str(root)) + b"/nonutf8_\xff.c"
    with open(opaque_name, "wb") as stream:
        stream.write(b"\0\xff")
    git(root, "add", "-A")
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Inventory Test",
                    "-c", "user.email=test@example.invalid", "commit", "-qm", "seed"],
                   check=True)
    seed = git(root, "rev-parse", "HEAD")
    git(root, "update-index", "--add", "--cacheinfo",
        "160000," + seed + ",vendor/opaque-submodule")
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Inventory Test",
                    "-c", "user.email=test@example.invalid", "commit", "-qm", "gitlink"],
                   check=True)
    commit = git(root, "rev-parse", "HEAD")
    lock = root.parent / "fixture-lock.json"
    lock.write_text(json.dumps({"linux": {"commit": commit}}))
    return commit, lock


def inspect(report_dir: Path, commit: str) -> None:
    report = json.loads((report_dir / "report.json").read_text())
    assert report["linux_commit"] == commit
    assert report["status"] == "PARTIAL_SOURCE_INVENTORY_NOT_LINUX_IMPLEMENTATION"
    assert not report["inventory_complete"] and not report["linux_full_rewrite_complete"]
    paths = [json.loads(line) for line in
             (report_dir / "source-paths.jsonl").read_text().splitlines()]
    declarations = [json.loads(line) for line in
                    (report_dir / "kconfig-declarations.jsonl").read_text().splitlines()]
    directories = [json.loads(line) for line in
                   (report_dir / "directory-objects.jsonl").read_text().splitlines()]
    source_edges = [json.loads(line) for line in
                    (report_dir / "kconfig-source-edges.jsonl").read_text().splitlines()]
    uapi = [json.loads(line) for line in
            (report_dir / "uapi-paths.jsonl").read_text().splitlines()]
    syscall = [json.loads(line) for line in
               (report_dir / "syscall-table-rows.jsonl").read_text().splitlines()]
    macros = [json.loads(line) for line in
              (report_dir / "uapi-macro-rows.jsonl").read_text().splitlines()]
    device = [json.loads(line) for line in
              (report_dir / "module-device-table-mentions.jsonl").read_text().splitlines()]
    assert report["counts"]["module_device_table_mentions"] == len(device) == 4
    assert report["counts"]["module_device_table_unparsed"] == 1
    assert [x["line"] for x in device] == [2, 3, 4, 5]
    assert [x["status"] for x in device] == [
        "LEXICAL_ARGUMENTS", "LEXICAL_ARGUMENTS", "UNPARSED", "LEXICAL_ARGUMENTS"]
    assert [base64.b64decode(x["bus_b64"]) if x["bus_b64"] else None
            for x in device] == [b"pci", b"usb", None, b"of"]
    assert all(x["blob_oid"] == next(p["oid"] for p in
        [json.loads(v) for v in (report_dir / "source-paths.jsonl").read_text().splitlines()]
        if p["path"] == "drivers/net/demo.c") for x in device)
    assert report["counts"]["uapi_header_files"] == 2
    assert report["counts"]["unreadable_uapi_header_files"] == 0
    assert report["counts"]["uapi_macro_rows"] == len(macros) == 4
    assert [base64.b64decode(x["name_b64"]) for x in macros] == [
        b"_NR_foo", b"UAPI_NUMBER", b"UAPI_CALL", b"INACTIVE"]
    assert [x["line"] for x in macros] == [2, 2, 3, 7]
    assert all(x["status"] == "LEXICAL_DEFINE" for x in macros)
    assert all(x["blob_oid"] == next(p["oid"] for p in paths
        if x["path_b64"] == p["path_b64"]) for x in macros)
    assert base64.b64decode(macros[2]["raw_b64"]).startswith(b" #  define")
    assert not any(base64.b64decode(x["name_b64"]) == b"COMMENTED" for x in macros)
    assert report["counts"]["syscall_table_files"] == 1
    assert report["counts"]["syscall_table_rows"] == len(syscall) == 4
    assert report["counts"]["syscall_table_unparsed_rows"] == 1
    assert report["counts"]["unreadable_syscall_table_files"] == 0
    assert [r["line"] for r in syscall] == [1, 2, 4, 5]
    assert [r["status"] for r in syscall] == [
        "LEXICAL_ROW", "LEXICAL_ROW", "UNPARSED", "LEXICAL_ROW"]
    assert [base64.b64decode(r["raw_b64"]) for r in syscall] == [
        b"0 common read sys_read", b"1 common write sys_write # inline comment",
        b"broken", b"3 x32 mmap sys_mmap compat_sys_mmap"]
    assert [tuple(base64.b64decode(v) for v in r["columns_b64"])
            for r in syscall] == [
        (b"0", b"common", b"read", b"sys_read"),
        (b"1", b"common", b"write", b"sys_write"),
        (b"broken",),
        (b"3", b"x32", b"mmap", b"sys_mmap", b"compat_sys_mmap")]
    assert all(r["blob_oid"] == next(
        x["oid"] for x in paths if x["path"] ==
        "arch/x86/entry/syscalls/syscall_64.tbl") for r in syscall)
    assert len(paths) == report["counts"]["tracked_paths"] == 11
    assert len(declarations) == report["counts"]["kconfig_declarations"] == 4
    assert len(source_edges) == report["counts"]["kconfig_source_edges"] == 5
    assert [edge["kind"] for edge in source_edges] == [
        "source", "rsource", "osource", "orsource", "source"]
    assert [base64.b64decode(edge["operand_b64"]) for edge in source_edges] == [
        b'"other/Kconfig"', b'"sub/Kconfig"', b'"$OPTIONAL/Kconfig"',
        b'"maybe/Kconfig"', b'"nested/with#symbol/Kconfig"']
    assert [edge["line"] for edge in source_edges] == [6, 7, 8, 9, 11]
    assert all(edge["blob_oid"] == next(
        p["oid"] for p in paths if p["path"] == "arch/x86/Kconfig")
        for edge in source_edges)
    assert report["counts"]["distinct_kconfig_symbol_names"] == 3
    assert report["counts"]["uapi_tree_entries"] == len(uapi) == 2
    assert report["counts"]["directory_tree_objects"] == len(directories) > 0
    assert {base64.b64decode(x["path_b64"]) for x in uapi} == {
        b"include/uapi/linux/demo.h", b"arch/x86/include/uapi/asm/unistd.h"}
    assert all(x["mode"] == "040000" and x["type"] == "tree" for x in directories)
    assert all(len(x["oid"]) == 40 for x in directories)
    assert report["counts"]["selected_syscall_abi_sources"] == 1
    assert report["counts"]["mode_120000"] == 1
    assert report["counts"]["mode_160000"] == 1
    assert report["counts"]["kconfig_paths"] == 2
    assert report["counts"]["unparsed_kconfig_paths"] == 0
    assert all(not (d["symbol"] == "COMMENTED") for d in declarations)
    assert [d["symbol"] for d in declarations] == ["CORE", "MENU", "CORE", "SECOND"]
    assert {d["line"] for d in declarations} == {2, 4, 5, 1}
    raw_paths = [base64.b64decode(p["path_b64"]) for p in paths]
    assert len(set(raw_paths)) == len(raw_paths)
    assert raw_paths == sorted(raw_paths)
    assert b"nonutf8_\xff.c" in raw_paths
    assert b"line\nfeed.c" in raw_paths
    assert next(x for x in paths if base64.b64decode(x["path_b64"]) ==
                b"vendor/opaque-submodule")["size"] is None
    assert next(x for x in paths if base64.b64decode(x["path_b64"]) ==
                b"nonutf8_\xff.c")["path"] is None
    for file, field in [("source-paths.jsonl", "source_paths_sha256"),
                        ("kconfig-declarations.jsonl", "kconfig_declarations_sha256"),
                        ("kconfig-source-edges.jsonl", "kconfig_source_edges_sha256"),
                        ("directory-objects.jsonl", "directory_objects_sha256"),
                        ("uapi-paths.jsonl", "uapi_entries_sha256"),
                        ("uapi-macro-rows.jsonl", "uapi_macro_rows_sha256"),
                        ("syscall-table-rows.jsonl", "syscall_table_rows_sha256"),
                        ("module-device-table-mentions.jsonl", "module_device_table_mentions_sha256")]:
        assert hashlib.sha256((report_dir / file).read_bytes()).hexdigest() == report[field]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="heptakernel-linux-inventory-") as temp:
        parent = Path(temp)
        source = parent / "source"
        commit, lock = fixture(source)
        first = parent / "first"
        inventory.build(source, lock, first)
        inspect(first, commit)

        # Worktree mutation must not alter data extracted from immutable tree
        # objects at the pinned commit.
        put(source, "arch/x86/Kconfig", "config UNCOMMITTED_POISON\n")
        second = parent / "second"
        inventory.build(source, lock, second)
        for name in ("source-paths.jsonl", "kconfig-declarations.jsonl", "kconfig-source-edges.jsonl",
                     "directory-objects.jsonl", "uapi-paths.jsonl",
                     "uapi-macro-rows.jsonl",
                     "syscall-table-rows.jsonl", "module-device-table-mentions.jsonl",
                     "report.json"):
            assert (first / name).read_bytes() == (second / name).read_bytes()
        inspect(second, commit)

        bad_lock = parent / "wrong-lock.json"
        bad_lock.write_text(json.dumps({"linux": {"commit": "0" * 40}}))
        bad_out = parent / "must-not-exist"
        try:
            inventory.build(source, bad_lock, bad_out)
        except ValueError as e:
            assert "HEAD mismatch" in str(e)
        else:
            raise AssertionError("invalid Linux baseline was accepted")
        assert not bad_out.exists()

        # Reject a forged lock shaped like a tag or truncated SHA.
        bad_lock.write_text(json.dumps({"linux": {"commit": commit[:12]}}))
        try:
            inventory.build(source, bad_lock, bad_out)
        except ValueError as e:
            assert "full lowercase" in str(e)
        else:
            raise AssertionError("short commit identity was accepted")

    print(json.dumps({
        "status": "PASS", "fixture_tracked_paths": 11,
        "fixture_kconfig_declarations": 4,
        "fixture_kconfig_source_edges": 5,
        "fixture_syscall_table_rows": 4, "fixture_uapi_macro_rows": 4,
        "fixture_device_table_mentions": 4,
        "non_utf8_and_newline_paths": "PASS",
        "symlink_and_gitlink": "PASS", "immutable_blob_read": "PASS",
        "deterministic_byte_replay": "PASS", "wrong_sha_fail_closed": "PASS",
        "linux_full_rewrite_complete": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
