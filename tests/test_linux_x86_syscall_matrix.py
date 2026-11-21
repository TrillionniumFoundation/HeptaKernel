#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Hostile syscall projection tests; no local kernel installation or execution."""
from __future__ import annotations

import base64
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_x86_syscall_matrix import X32_BIT, project
import json


def row(line: int, raw: bytes) -> dict:
    return {
        "line": line,
        "raw_b64": base64.b64encode(raw).decode("ascii"),
        "columns_b64": [base64.b64encode(x).decode("ascii")
                        for x in raw.partition(b"#")[0].split()],
        "status": "LEXICAL_ROW",
        "blob_oid": "a" * 40,
    }


class ProjectionTests(unittest.TestCase):
    def test_x32_inherits_common_and_uses_high_bit(self):
        records = [
            row(7, b"0 common read sys_read"),
            row(8, b"1 64 write sys_write"),
            row(9, b"2 common missing"),
            row(10, b"512 x32 ioctl compat_sys_ioctl"),
            row(11, b"60 common exit sys_exit - noreturn # comment"),
        ]
        a, b, counts = project(records)
        native = list(map(json.loads, a.splitlines()))
        x32 = list(map(json.loads, b.splitlines()))
        self.assertEqual([r["source_number"] for r in native], [0, 1, 2, 60])
        self.assertEqual([r["source_number"] for r in x32], [0, 2, 512, 60])
        self.assertEqual([r["dispatch_number"] for r in x32],
                         [X32_BIT, X32_BIT | 2, X32_BIT | 512, X32_BIT | 60])
        self.assertEqual(counts, {
            "original_source_rows": 5, "common_rows": 3,
            "native_only_rows": 1, "x32_only_rows": 1,
            "native_dispatch_obligations": 4, "x32_dispatch_obligations": 4,
            "native_missing_declared_handler": 1, "x32_missing_declared_handler": 1,
            "native_noreturn_declarations": 1, "x32_noreturn_declarations": 1,
        })
        self.assertEqual(native[2]["entry_status"], "NO_ENTRY_DECLARED")
        self.assertEqual(native[2]["implementation_status"], "NOT_IMPLEMENTED")
        self.assertTrue(x32[-1]["noreturn_declaration"])
        self.assertEqual(project(records), (a, b, counts))

    def test_refuse_duplicates_ambiguous_abi_columns_and_raw_tampering(self):
        good = [row(1, b"0 common foo sys_foo"), row(2, b"512 x32 bar compat_sys_bar")]
        for bad in [
            good + [row(3, b"0 64 alias sys_alias")],
            good + [row(1, b"3 64 same_line sys_x")],
            [row(1, b"0 32 invalid sys_invalid")],
            [row(1, b"01 common leading_zero sys_x")],
            [row(1, b"1073741824 common too_big sys_x")],
            [row(1, b"0 common malformed sys_x compat_only")],
            [row(1, b"0 common malformed sys_x - not_noreturn")],
        ]:
            with self.subTest(rows=bad), self.assertRaises(ValueError):
                project(bad)
        dirty = copy.deepcopy(good)
        dirty[0]["raw_b64"] = base64.b64encode(b"0 common replaced sys_replaced").decode()
        with self.assertRaisesRegex(ValueError, "source row"):
            project(dirty)
        dirty = copy.deepcopy(good)
        dirty[0]["status"] = "UNPARSED"
        with self.assertRaises(ValueError):
            project(dirty)


if __name__ == "__main__":
    unittest.main()
