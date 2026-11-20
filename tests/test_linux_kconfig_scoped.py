#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial immutable-Git tests of Kconfig owner candidate classification."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_kconfig_scoped import classify_blob, collect  # noqa: E402
from linux_kconfig_relations import extract  # noqa: E402


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


DATA = (
    b"config BASE\n"
    b"\tbool \"Base\"\n"
    b"\tdepends on A && B\n"
    b"\thelp\n"
    b"\t  select HELP_FAKE\n"
    b"\tdefault y\n"
    b"menu \"group\"\n"
    b"\tdepends on MENU_SCOPE\n"
    b"endmenu\n"
    b"menuconfig OTHER\n"
    b"\tselect CHOSEN if X\n"
    b"\tdefault y \\\n"
    b"\tdepends on CONTINUED_FAKE\n"
    b"\timply TRUE\n"
    b"# select COMMENTED\n"
)


class KconfigScopedTests(unittest.TestCase):
    def test_scope_labels_and_source_byte_identity(self):
        rows = classify_blob(DATA)
        self.assertEqual(len(rows), len(list(extract(DATA))))
        self.assertEqual([r["line"] for r in rows], [3, 5, 6, 8, 11, 12, 13, 14])
        self.assertEqual([r["scope_status"] for r in rows], [
            "SCOPED_LEXICAL_CANDIDATE", "HELP_TEXT_LEXICAL_ONLY",
            "SCOPED_LEXICAL_CANDIDATE", "UNBOUND_LEXICAL_CANDIDATE",
            "SCOPED_LEXICAL_CANDIDATE", "SCOPED_LEXICAL_CANDIDATE",
            "UNRESOLVED_CONTINUATION", "SCOPED_LEXICAL_CANDIDATE",
        ])
        self.assertEqual([r["owner"] for r in rows],
                         ["BASE", None, "BASE", None, "OTHER", "OTHER", None, "OTHER"])
        self.assertEqual([r["owner_declaration_line"] for r in rows],
                         [1, None, 1, None, 10, 10, None, 10])
        for row in rows:
            original = DATA.split(b"\n")[row["line"] - 1]
            self.assertEqual(base64.b64decode(row["raw_b64"]), original)
            self.assertEqual(DATA[row["byte_at"]:row["byte_end"]],
                             original.lstrip(b" \t"))
        self.assertNotIn("COMMENTED", json.dumps(rows))
        self.assertEqual(classify_blob(DATA), rows)

    def test_mixed_indent_and_help_body_remain_conservative(self):
        blob = (b"\tconfig A\n"
                b"  select NOT_BOUND\n"
                b"\t  depends on B\n"
                b"\t  ---help---\n"
                b"\t    imply HELP_ONLY\n"
                b"\t  default y\n"
                b"source \"other/Kconfig\"\n"
                b"\t  select POST_SOURCE\n")
        rows = classify_blob(blob)
        self.assertEqual([r["owner"] for r in rows],
                         [None, "A", None, "A", None])
        self.assertEqual(rows[2]["scope_status"], "HELP_TEXT_LEXICAL_ONLY")

    def test_pinned_git_blobs_ignore_worktree_mutation_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Kconfig Tester")
            git(repo, "config", "user.email", "noreply@example.invalid")
            src = repo / "arch/x86/Kconfig"
            src.parent.mkdir(parents=True)
            src.write_bytes(DATA)
            (repo / "Kconfig.alias").symlink_to("arch/x86/Kconfig")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "fixed Kconfig fixtures")
            pinned = git(repo, "rev-parse", "HEAD").decode()
            first, report = collect(repo, pinned)
            self.assertEqual(report["counts"]["kconfig_paths"], 2)
            self.assertEqual(report["counts"]["unreadable_kconfig_paths"], 1)
            self.assertEqual(report["counts"]["property_candidates"], 8)
            self.assertEqual(report["counts"]["SCOPED_LEXICAL_CANDIDATE"], 5)
            self.assertEqual(hashlib.sha256(first).hexdigest(),
                             report["source_sha256"])
            self.assertFalse(report["inventory_complete"])
            self.assertFalse(report["full_rewrite_complete"])
            for raw in first.splitlines():
                row = json.loads(raw)
                self.assertEqual(row["blob_oid"], git(repo, "rev-parse", "HEAD:arch/x86/Kconfig").decode())
                self.assertEqual(base64.b64decode(row["path_b64"]), b"arch/x86/Kconfig")
            src.write_bytes(b"config FORGED\n\tdepends on MALICE\n")
            self.assertEqual(collect(repo, pinned)[0], first)
            with self.assertRaisesRegex(ValueError, "exact 40-digit"):
                collect(repo, pinned[:12])
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "changed")
            with self.assertRaisesRegex(ValueError, "HEAD mismatch"):
                collect(repo, pinned)


if __name__ == "__main__":
    unittest.main()
