#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent adversarial projection tests; no host kernel execution."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_x86_ia32_syscall_matrix import project

OID = "a" * 40


def row(line: int, raw: bytes) -> dict:
    fields = raw.partition(b"#")[0].split()
    return {
        "path_b64": base64.b64encode(
            b"arch/x86/entry/syscalls/syscall_32.tbl").decode("ascii"),
        "blob_oid": OID,
        "line": line,
        "raw_b64": base64.b64encode(raw).decode("ascii"),
        "columns_b64": [base64.b64encode(f).decode("ascii") for f in fields],
        "status": "LEXICAL_ROW",
    }


class Ia32Projection(unittest.TestCase):
    def test_primary_compat_missing_noreturn_and_source_provenance(self):
        rows = [
            row(10, b"0 i386 read sys_read"),
            row(11, b"1 i386 obsolete"),
            row(12, b"5 i386 open sys_open compat_sys_open # comment"),
            row(13, b"11 i386 execve sys_execve compat_sys_execve"),
            row(14, b"20 i386 exit sys_exit - noreturn"),
        ]
        payload, counts = project(rows, OID)
        self.assertEqual(counts, {
            "source_rows": 5, "missing_primary_entry": 1,
            "explicit_compat_overrides": 2, "noreturn_declarations": 1,
            "max_source_number": 20,
        })
        decoded = [json.loads(x) for x in payload.splitlines()]
        self.assertEqual([r["source_number"] for r in decoded], [0, 1, 5, 11, 20])
        self.assertEqual([r["entry_selection"] for r in decoded],
            ["PRIMARY_DECLARATION", "NO_DECLARED_ENTRY",
             "EXPLICIT_COMPAT_OVERRIDE", "EXPLICIT_COMPAT_OVERRIDE",
             "PRIMARY_DECLARATION"])
        self.assertEqual(decoded[2]["ia32_emulation_declared_entry"], "compat_sys_open")
        self.assertEqual(decoded[2]["native_declared_entry"], "sys_open")
        self.assertIsNone(decoded[1]["ia32_emulation_declared_entry"])
        self.assertTrue(decoded[4]["noreturn_declaration"])
        self.assertTrue(all(r["implementation_status"] == "NOT_IMPLEMENTED" for r in decoded))
        self.assertTrue(all(r["source_blob_oid"] == OID for r in decoded))
        self.assertEqual(project(rows, OID), (payload, counts))

    def test_reject_duplicate_number_line_bad_columns_and_invalid_abi(self):
        good = [row(1, b"0 i386 read sys_read"),
                row(2, b"1 i386 exit sys_exit - noreturn")]
        cases = [
            good + [row(3, b"0 i386 write sys_write")],
            good + [row(2, b"3 i386 alias sys_alias")],
            [row(1, b"01 i386 read sys_read")],
            [row(1, b"2147483648 i386 huge sys_huge")],
            [row(1, b"1 x32 io sys_io")],
            [row(1, b"2 i386 io sys_io extra another")],
            [row(1, b"2 i386 io sys_io compat_sys_io noreturn")],
            [row(1, b"2 i386 io sys_io - not_noreturn")],
            [row(1, b"2 i386 io invalid-field!")],
        ]
        for case in cases:
            with self.subTest(rows=case), self.assertRaises(ValueError):
                project(case, OID)

    def test_refuse_forged_blob_column_ledger_and_boolean_line(self):
        good = [row(1, b"0 i386 read sys_read")]
        for prop, value in [
            ("blob_oid", "b" * 40),
            ("status", "UNPARSED"),
            ("line", True),
            ("line", 0),
            ("columns_b64", []),
            ("raw_b64", base64.b64encode(b"0 i386 changed sys_changed").decode()),
        ]:
            with self.subTest(prop=prop):
                dirty = copy.deepcopy(good)
                dirty[0][prop] = value
                with self.assertRaises(ValueError):
                    project(dirty, OID)


if __name__ == "__main__":
    unittest.main()
