#!/usr/bin/env python3
"""Independent offline Git fixture for pinned recursive inventory exporter."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from pinned_inventory import collect, parse_tree, sha256


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "repo"
        root.mkdir()
        git(root, "init", "-q")
        git(root, "config", "user.email", "test@example.invalid")
        git(root, "config", "user.name", "Fixture")
        for directory in ("drivers/demo", "arch/x86/include/uapi/asm", "include/uapi/linux"):
            (root / directory).mkdir(parents=True)
        (root / "drivers/demo/Kconfig").write_text(
            "config DEMO\n\tbool \"demo\"\nmenuconfig DEMO_EXTRA\n")
        (root / "drivers/demo/test\tfile.c").write_text("int main(void) {return 0;}\n")
        (root / "arch/x86/include/uapi/asm/unistd.h").write_text("#define __NR_test 1\n")
        (root / "include/uapi/linux/demo.h").write_text("#define DEMO 42\n")
        git(root, "add", ".")
        git(root, "commit", "-qm", "fixture")
        commit = git(root, "rev-parse", "HEAD")
        first = collect(root, commit, Path(td) / "out1")
        second = collect(root, commit, Path(td) / "out2")
        assert first == second
        assert first["upstream_tree_sha"] == git(root, "rev-parse", "HEAD^{tree}")
        assert first["tracked_counts"]["blob"] == 4
        assert first["kconfig_symbol_occurrences"] == 2
        assert first["uapi_header_path_count"] == 2
        data = gzip.decompress((Path(td) / "out1/git-tree-entries.jsonl.gz").read_bytes())
        rows = [json.loads(line) for line in data.splitlines()]
        assert any(bytes.fromhex(row["path_hex"]) == b"drivers/demo/test\tfile.c" for row in rows)
        assert all(len(row["git_oid"]) == 40 for row in rows)
        assert sha256(data)
        assert list(parse_tree(b"100644 blob " + b"0" * 40 + b"\tx\ny\x00"))[0][-1] == b"x\ny"
        assert not first["full_rewrite_complete"]
        assert not first["driver_hardware_ids_complete"]
        for bad in ("0" * 40, commit[:30] + "0" * 10):
            try:
                collect(root, bad, Path(td) / "bad")
            except (RuntimeError, subprocess.CalledProcessError):
                pass
            else:
                raise AssertionError("wrong commit accepted")
        print("pinned recursive Linux inventory offline Git fixture PASS")


if __name__ == "__main__":
    main()
