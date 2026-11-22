#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent byte-span and pinned-Git adversarial UAPI ioctl inventory tests."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_uapi_ioctl_macros import collect, scan_defines


def cmd(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.PIPE,
        text=True).strip()


def expect_error(callback, text: str) -> None:
    try:
        callback()
    except ValueError as exc:
        assert text in str(exc), (str(exc), text)
    else:
        raise AssertionError("bad inventory was silently admitted: " + text)


def test_lines() -> None:
    data = (
        b"// #define COMMENT _IO('x', 1)\n"
        b"#define A _IO('q', 1)\n"
        b"#define B(x) \\\n"
        b"    _IOWR('q', (x), struct foo) \\\n"
        b"    + _IOC(1,2,3,4)\n"
        b"#define C _IOR_BAD('v', 7, char)\r\n"
        b"#define D _IOC_READ\n"
        b"#define E (1 + _IOW('z', 3, int))\n"
        b"#define F _IO(1, 2) \\"
    )
    rows = scan_defines(data)
    assert [x["macro"] for x in rows] == ["A", "B", "C", "E", "F"]
    assert [x["io_calls"] for x in rows] == [
        ["_IO"], ["_IOWR", "_IOC"], ["_IOR_BAD"], ["_IOW"], ["_IO"]]
    assert [x["start_line"] for x in rows] == [2, 3, 6, 8, 9]
    assert [x["end_line"] for x in rows] == [2, 5, 6, 8, 9]
    assert rows[-1]["status"] == "UNTERMINATED_CONTINUATION"
    for item in rows:
        original = base64.b64decode(item["raw_b64"])
        assert data[item["start_byte"]:item["end_byte"]] == original
        assert original.startswith(b"#define ")
    assert scan_defines(b"#define NO _IOC_READ\n") == []
    assert scan_defines(b"#define NOT _IOR('x',2) \\\nMORE\n")[0]["end_line"] == 2
    # A trailing blank after the backslash must not silently join lines.
    test = b"#define O _IO('x',3) \\ \n#define P _IOR('z',2,int)\n"
    assert [x["macro"] for x in scan_defines(test)] == ["O", "P"]


def test_git() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = root / "linux"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "include/uapi/linux").mkdir(parents=True)
        (repo / "include/linux").mkdir(parents=True)
        source = b"#define EXAMPLE _IO('q', 1)\n#define IOCTL2 \\\n _IOW('q', 2, int)\n"
        (repo / "include/uapi/linux/demo.h").write_bytes(source)
        (repo / "include/linux/ignore.h").write_bytes(b"#define IGNORE _IO(1,1)\n")
        (repo / "include/uapi/linux/unrelated.h").write_bytes(b"#define OTHER 99\n")
        cmd(repo, "add", ".")
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Inventory",
                        "-c", "user.email=inventory@example.invalid",
                        "commit", "-qm", "fixed"], check=True)
        commit = cmd(repo, "rev-parse", "HEAD")
        tree = cmd(repo, "rev-parse", "HEAD^{tree}")
        lock = root / "lock.json"
        lock.write_text(json.dumps({"linux": {"commit": commit}}))
        payload, report = collect(repo, lock)
        rows = [json.loads(line) for line in payload.splitlines()]
        assert len(rows) == 2 and report["records"] == 2
        assert report["linux_commit"] == commit
        assert report["linux_root_tree"] == tree
        assert report["source_sha256"] == hashlib.sha256(payload).hexdigest()
        assert report["counts"]["uapi_headers"] == 2
        assert report["counts"]["readable_headers"] == 2
        assert report["counts"]["ioctl_calls"] == 2
        assert report["status"].startswith("PARTIAL_LEXICAL")
        assert not report["inventory_complete"] and not report["full_rewrite_complete"]
        assert [r["macro"] for r in rows] == ["EXAMPLE", "IOCTL2"]
        for row in rows:
            path = base64.b64decode(row["path_b64"])
            assert path == b"include/uapi/linux/demo.h"
            blob = subprocess.check_output(
                ["git", "-C", str(repo), "cat-file", "blob", row["blob_oid"]])
            assert blob[row["start_byte"]:row["end_byte"]] == base64.b64decode(row["raw_b64"])
        bad = root / "bad.json"
        bad.write_text(json.dumps({"linux": {"commit": "0" * 40}}))
        expect_error(lambda: collect(repo, bad), "HEAD mismatch")
        bad.write_text(json.dumps({"linux": {"commit": "../main"}}))
        expect_error(lambda: collect(repo, bad), "exact pinned Linux commit")
        (repo / "include/uapi/linux/demo.h").write_bytes(source + b"#define LATE _IO(3,4)\n")
        cmd(repo, "add", ".")
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Inventory",
                        "-c", "user.email=inventory@example.invalid",
                        "commit", "-qm", "changed"], check=True)
        expect_error(lambda: collect(repo, lock), "HEAD mismatch")
        (repo / "include/uapi/linux/demo.h").write_bytes(b"#define UNCOMMITTED _IO(8,9)\n")
        # Immutable Git blobs, not dirty worktree text, determine the report.
        latest = cmd(repo, "rev-parse", "HEAD")
        lock.write_text(json.dumps({"linux": {"commit": latest}}))
        payload2, report2 = collect(repo, lock)
        assert report2["records"] == 3
        assert b"UNCOMMITTED" not in payload2


if __name__ == "__main__":
    test_lines()
    test_git()
    print("UAPI_IOCTL_LEXICAL_SOURCE_ORACLE: PASS")
    print("UAPI_IOCTL_LINUX_IMPLEMENTATION: HOLD")
