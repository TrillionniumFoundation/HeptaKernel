#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial arch profile matrix provenance and no-silent-drop tests."""
from __future__ import annotations

import base64
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_kconfig_include_targets import literal_target, encode
from linux_kconfig_root_closure import digest, jsonl, projection
from linux_kconfig_profile_matrix import assemble


def fixture(arch: str):
    paths = {}
    for idx, name in enumerate((b"Kconfig", b"arch/x86/Kconfig", b"arch/arm/Kconfig", b"drivers/Kconfig")):
        paths[name] = {"path_b64": encode(name), "oid": ("%040x" % (idx+1)),
                       "mode": "100644", "type": "blob", "size": 40}
    records = []
    for parent, number, kind, operand in (
            (b"Kconfig", 1, "source", b'"arch/$(SRCARCH)/Kconfig"'),
            (b"arch/x86/Kconfig", 2, "source", b'"drivers/Kconfig"'),
            (b"arch/arm/Kconfig", 3, "osource", b'"not/tracked"'),
            (b"drivers/Kconfig", 4, "source", b'"Kconfig"')):
        status, target, hit = literal_target(parent, kind, operand, paths)
        records.append({"path_b64": encode(parent), "blob_oid": paths[parent]["oid"],
                        "line": number, "kind": kind, "operand_b64": encode(operand),
                        "source_context": "DIRECTIVE_LEXICAL_CANDIDATE",
                        "resolution": status, "target_path_b64": encode(target) if target else None,
                        "target_oid": hit["oid"] if hit else None,
                        "target_mode": hit["mode"] if hit else None})
    out, files, counts = projection(paths, records, {"SRCARCH": arch, "HEADER_ARCH": arch})
    edges, reached = jsonl(out), jsonl(files)
    report = {"linux_commit": "a"*40, "linux_root_tree": "b"*40,
              "source_literal_sha256": "c"*64, "source_paths_sha256": "d"*64,
              "profile": {"SRCARCH": arch, "HEADER_ARCH": arch},
              "profile_edges_sha256": digest(edges), "reachable_files_sha256": digest(reached),
              "status": "PARTIAL_POSSIBLE_ROOT_GRAPH_NOT_EVALUATED_KCONFIG",
              "inventory_complete": False, "full_rewrite_complete": False,
              "counts": {"all_lexical_edges": len(out),
                         "reachable_regular_files": len(files), **counts}}
    return arch, edges, reached, report


class MatrixTests(unittest.TestCase):
    def test_two_architectures_union_intersection_and_cycles(self):
        a, b = fixture("x86"), fixture("arm")
        members, union, profiles, counts = assemble([a, b])
        self.assertEqual(counts, {"architecture_profiles": 2,
                                  "membership_rows": 5, "union_reachable_files": 4,
                                  "intersection_reachable_files": 1})
        self.assertEqual([p["arch_profile"] for p in profiles], ["x86", "arm"])
        self.assertEqual(len(members.splitlines()), 5)
        self.assertEqual(len(union.splitlines()), 4)
        self.assertEqual(assemble([a, b]), (members, union, profiles, counts))
        self.assertNotEqual(digest(a[2]), digest(b[2]))

    def test_refuse_duplicate_profiles_and_tampered_bytes(self):
        x = fixture("x86")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            assemble([x, x])
        bad = list(fixture("arm"))
        bad[3] = copy.deepcopy(bad[3])
        bad[3]["profile_edges_sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError, "unbound"):
            assemble([x, tuple(bad)])
        bad = list(fixture("arm"))
        bad[3] = copy.deepcopy(bad[3])
        bad[3]["linux_root_tree"] = "0"*40
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            assemble([x, tuple(bad)])
        bad = list(fixture("arm"))
        bad[3] = copy.deepcopy(bad[3])
        bad[3]["full_rewrite_complete"] = True
        with self.assertRaisesRegex(ValueError, "falsely"):
            assemble([x, tuple(bad)])


if __name__ == "__main__":
    unittest.main()
