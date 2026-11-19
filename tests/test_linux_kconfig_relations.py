#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial tests for exact Kconfig lexical line/origin binding."""
import base64
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_kconfig_relations import collect, extract  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


class KconfigRelationTests(unittest.TestCase):
    DATA = (b"config GOOD\n"
            b"\tbool \"Real\"\n"
            b"\tdepends on X && (Y || Z)\n"
            b"\tselect HELPER if X\n"
            b"\timply ALTERNATIVE if Y\n"
            b"\tdefault y if X\n"
            b"\trange 0 100 if M\n"
            b"\tprompt \"User visible\" if X\n"
            b"\tvisible if X\n"
            b"\tdef_bool y if X\n"
            b"\tdef_tristate m if A\n"
            b"\thelp\n"
            b"\t  select MISLEADING_HELP\n"
            b"# select COMMENTED\n"
            b"\tselect MACRO $(MAKE) if X # raw\n"
            b"\tdefault value \\\n"
            b"\t  if CONTINUED\n")

    def test_exact_raw_byte_ranges_not_semantic_graph(self):
        rows = list(extract(self.DATA))
        self.assertEqual([r["kind"] for r in rows],
                         ["depends_on", "select", "imply", "default", "range",
                          "prompt", "visible_if", "def_bool", "def_tristate",
                          "select", "select", "default"])
        self.assertIn(b"MISLEADING_HELP",
                      [base64.b64decode(r["operand_b64"]) for r in rows])
        self.assertNotIn(b"COMMENTED",
                         [base64.b64decode(r["operand_b64"]) for r in rows])
        physical = self.DATA.split(b"\n")
        for row in rows:
            raw = physical[row["line"] - 1]
            self.assertEqual(base64.b64decode(row["raw_b64"]), raw)
            self.assertEqual(self.DATA[row["byte_at"]:row["byte_end"]],
                             raw[len(raw) - len(raw.lstrip(b" \t")):])
            self.assertEqual(self.DATA[:row["byte_at"]].count(b"\n") + 1,
                             row["line"])

    def test_immutable_git_and_wrong_head_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Kconfig Test")
            git(repo, "config", "user.email", "test@example.invalid")
            src = repo / "arch/x86/Kconfig"
            src.parent.mkdir(parents=True)
            src.write_bytes(self.DATA)
            (repo / "Kconfig.extra").write_bytes(b"depends on EXTRA\n")
            (repo / "Kconfig.link").symlink_to("arch/x86/Kconfig")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "first")
            pinned = git(repo, "rev-parse", "HEAD").decode()
            before, report = collect(repo, pinned)
            self.assertEqual(report["counts"]["kconfig_paths"], 3)
            self.assertEqual(report["counts"]["unreadable_kconfig_paths"], 1)
            self.assertEqual(report["counts"]["relation_line_candidates"], 13)
            self.assertEqual(hashlib.sha256(before).hexdigest(),
                             report["source_sha256"])
            src.write_bytes(b"select FORGED_WORKTREE\n")
            self.assertEqual(collect(repo, pinned)[0], before)
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "second")
            with self.assertRaisesRegex(ValueError, "HEAD mismatch"):
                collect(repo, pinned)
            with self.assertRaisesRegex(ValueError, "full lowercase"):
                collect(repo, pinned[:12])


if __name__ == "__main__":
    unittest.main()
