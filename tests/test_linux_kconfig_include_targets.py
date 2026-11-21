#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent Git-source, boundary and negative controls for Kconfig targets."""
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
from linux_kconfig_include_targets import collect, literal_target  # noqa: E402


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


class KconfigLiteralTargetsTests(unittest.TestCase):
    def test_literal_anchor_optional_escape_and_nonregular(self):
        paths = {b"sub/Kconfig": {"mode": "100644", "type": "blob", "oid": "1" * 40},
                 b"foo/link": {"mode": "120000", "type": "blob", "oid": "2" * 40}}
        oracle = [
            ("source", b'"sub/Kconfig"', "TRACKED_REGULAR_LITERAL", b"sub/Kconfig"),
            ("rsource", b'"../sub/Kconfig"', "TRACKED_REGULAR_LITERAL", b"sub/Kconfig"),
            ("rsource", b'"link"', "TRACKED_NONREGULAR_LITERAL", b"foo/link"),
            ("source", b'"missing"', "REQUIRED_UNTRACKED_LITERAL", b"missing"),
            ("osource", b'"missing"', "OPTIONAL_UNTRACKED_LITERAL", b"missing"),
            ("source", b'"../../escape"', "OUTSIDE_TRACKED_TREE", None),
            ("source", b'"/root"', "OUTSIDE_TRACKED_TREE", None),
            ("source", b'"arch/$SRCARCH/Kconfig"', "UNRESOLVED_VARIABLE_GLOB_OR_ESCAPE", None),
            ("source", b'"drivers/*/Kconfig"', "UNRESOLVED_VARIABLE_GLOB_OR_ESCAPE", None),
            ("source", b'"broken', "UNRESOLVED_LITERAL_SYNTAX", None),
            ("source", b'"bad"extra', "UNRESOLVED_LITERAL_SYNTAX", None),
        ]
        for kind, operand, status, target in oracle:
            with self.subTest(kind=kind, operand=operand):
                observed, name, hit = literal_target(b"foo/Kconfig", kind, operand, paths)
                self.assertEqual((observed, name), (status, target))
                self.assertEqual(hit is not None, status.startswith("TRACKED_"))

    def test_immutable_origin_projection_and_wrong_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Kconfig Test")
            git(repo, "config", "user.email", "test@example.test")
            (repo / "foo").mkdir()
            (repo / "sub").mkdir()
            (repo / "sub/Kconfig").write_bytes(b"config HELLO\n")
            (repo / "foo/link").symlink_to("../sub/Kconfig")
            source = (b'source "sub/Kconfig"\n'
                      b'rsource "link"\n'
                      b'osource "optional/Kconfig"\n'
                      b'orsource "../sub/Kconfig"\n'
                      b'source "arch/$SRCARCH/Kconfig"\n'
                      b'source "../../escape"\n'
                      b'source "missing"\n')
            (repo / "foo/Kconfig").write_bytes(source)
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "fixture")
            commit = git(repo, "rev-parse", "HEAD").decode()
            root = git(repo, "rev-parse", "HEAD^{tree}").decode()
            entries = []
            for raw in git(repo, "ls-tree", "-r", "-z", "-l", "HEAD").split(b"\0"):
                if not raw:
                    continue
                metadata, path = raw.split(b"\t", 1)
                mode, kind, oid, size = metadata.split()
                entries.append({"path_b64": base64.b64encode(path).decode(),
                                "mode": mode.decode(), "type": kind.decode(),
                                "oid": oid.decode(), "size": int(size)})
            source_ledger = b"".join((json.dumps(x, sort_keys=True) + "\n").encode() for x in entries)
            parent = next(x for x in entries if base64.b64decode(x["path_b64"]) == b"foo/Kconfig")
            edges = []
            for number, line in enumerate(source.splitlines(), 1):
                kind, operand = line.split(b" ", 1)
                edges.append({"path_b64": parent["path_b64"], "blob_oid": parent["oid"],
                              "line": number, "kind": kind.decode(),
                              "operand_b64": base64.b64encode(operand).decode()})
            edge_ledger = b"".join((json.dumps(x, sort_keys=True) + "\n").encode() for x in edges)
            manifest = {"linux_commit": commit, "linux_root_tree": root,
                        "source_paths_sha256": hashlib.sha256(source_ledger).hexdigest(),
                        "kconfig_source_edges_sha256": hashlib.sha256(edge_ledger).hexdigest(),
                        "counts": {"tracked_paths": len(entries), "kconfig_source_edges": len(edges)}}
            content, report = collect(repo, commit, source_ledger, edge_ledger, manifest)
            rows = [json.loads(row) for row in content.splitlines()]
            self.assertEqual([x["resolution"] for x in rows], [
                "TRACKED_REGULAR_LITERAL", "TRACKED_NONREGULAR_LITERAL",
                "OPTIONAL_UNTRACKED_LITERAL", "TRACKED_REGULAR_LITERAL",
                "UNRESOLVED_VARIABLE_GLOB_OR_ESCAPE", "OUTSIDE_TRACKED_TREE",
                "REQUIRED_UNTRACKED_LITERAL"])
            self.assertEqual(report["counts"]["all_lexical_edges"], len(edges))
            self.assertFalse(report["inventory_complete"])
            self.assertEqual(report["source_sha256"], hashlib.sha256(content).hexdigest())
            (repo / "foo/Kconfig").write_bytes(b'source "forged"\n')
            self.assertEqual(collect(repo, commit, source_ledger, edge_ledger, manifest)[0], content)
            bad = json.loads(json.dumps(edges))
            bad[0]["operand_b64"] = base64.b64encode(b'"forged"').decode()
            poisoned = b"".join((json.dumps(x, sort_keys=True) + "\n").encode() for x in bad)
            poisoned_manifest = {**manifest, "kconfig_source_edges_sha256": hashlib.sha256(poisoned).hexdigest()}
            with self.assertRaisesRegex(ValueError, "differs"):
                collect(repo, commit, source_ledger, poisoned, poisoned_manifest)
            with self.assertRaisesRegex(ValueError, "ledger"):
                collect(repo, commit, source_ledger, edge_ledger, {**manifest, "source_paths_sha256": "0"*64})
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "changed HEAD")
            with self.assertRaisesRegex(ValueError, "HEAD"):
                collect(repo, commit, source_ledger, edge_ledger, manifest)


if __name__ == "__main__":
    unittest.main()
