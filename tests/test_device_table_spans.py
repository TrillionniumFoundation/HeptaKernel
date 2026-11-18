#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent byte-offset tests for multiline pinned device table mentions."""
from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "linux_inventory", ROOT / "tools/linux_inventory.py")
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   text=True).strip()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hk-driver-spans-") as folder:
        repo = Path(folder) / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        first = repo / "drivers/net/driver.c"
        first.parent.mkdir(parents=True)
        content = (
            b"MODULE_DEVICE_TABLE(pci, basic);\n"
            b"MODULE_DEVICE_TABLE(\n  usb,\n  spread\n);\n"
            b"MODULE_DEVICE_TABLE\n(\n  of,\n  spaced\n);\n"
            b"MODULE_DEVICE_TABLE(acpi, );\n"
            b"// MODULE_DEVICE_TABLE(pci, commented);\n"
            b"MODULE_DEVICE_TABLE(pci, missing\n"
        )
        first.write_bytes(content)
        odd = os.fsencode(str(repo)) + b"/drivers/net/odd\n\xff.c"
        with open(odd, "wb") as output:
            output.write(b"MODULE_DEVICE_TABLE(usb, strange);\n")
        (repo / "drivers/net/excluded.txt").write_bytes(
            b"MODULE_DEVICE_TABLE(pci, excluded);\n")
        git(repo, "add", "-A")
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=Driver Test",
             "-c", "user.email=driver@example.invalid",
             "commit", "-qm", "seed"], check=True)
        pinned = git(repo, "rev-parse", "HEAD")
        entries = inventory.enumerate_entries(repo, pinned)
        import json
        records = [
            json.loads(line)
            for line in inventory.enumerate_device_table_invocations(
                repo, pinned, entries).splitlines()
        ]
        assert len(records) == 7, len(records)
        assert sum(r["status"] == "LEXICAL_ARGUMENTS" for r in records) == 5
        assert sum(r["status"] == "UNPARSED" for r in records) == 1
        assert sum(r["status"] == "TRUNCATED" for r in records) == 1
        assert sum(r["end_line"] > r["start_line"] for r in records) == 2
        assert all(r["end_byte"] > r["start_byte"] for r in records)
        original = {
            os.fsencode("drivers/net/driver.c"): content,
            b"drivers/net/odd\n\xff.c": b"MODULE_DEVICE_TABLE(usb, strange);\n",
        }
        for item in records:
            raw_path = base64.b64decode(item["path_b64"])
            raw = base64.b64decode(item["raw_b64"])
            blob = original[raw_path]
            assert raw == blob[item["start_byte"]:item["end_byte"]]
            assert item["start_line"] == blob.count(
                b"\n", 0, item["start_byte"]) + 1
            assert item["end_line"] == blob.count(
                b"\n", 0, item["end_byte"] - 1) + 1
            if item["status"] == "LEXICAL_ARGUMENTS":
                assert base64.b64decode(item["bus_b64"])
                assert base64.b64decode(item["symbol_b64"])
            else:
                assert item["bus_b64"] is None
                assert item["symbol_b64"] is None
        assert sum(r["path"] is None for r in records) == 1
        assert [r["start_line"] for r in records if r["path"] ==
                "drivers/net/driver.c"] == [1, 2, 6, 11, 12, 13]
        assert [r["status"] for r in records if r["path"] ==
                "drivers/net/driver.c"] == [
                    "LEXICAL_ARGUMENTS", "LEXICAL_ARGUMENTS",
                    "LEXICAL_ARGUMENTS", "UNPARSED",
                    "LEXICAL_ARGUMENTS", "TRUNCATED",
                ]
        # Replaying after a dirty worktree must not alter exact Git-object data.
        first.write_bytes(b"MODULE_DEVICE_TABLE(pci, POISON);\n")
        replay = inventory.enumerate_device_table_invocations(
            repo, pinned, entries)
        assert replay == b"".join(inventory.json_line(x) for x in records)
        # Legacy same-line rows retain their original format and scope.
        legacy = inventory.enumerate_device_table_mentions(
            repo, pinned, entries).splitlines()
        assert len(legacy) == 4, len(legacy)
    print("PINNED_MULTILINE_DEVICE_TABLE_SPANS: PASS 7")
    print("UNPARSED_AND_TRUNCATED: PASS")
    print("RAW_BYTE_PATH_AND_IMMUTABLE_OBJECT: PASS")


if __name__ == "__main__":
    main()
