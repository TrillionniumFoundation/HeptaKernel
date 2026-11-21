#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent small-Git-tree and hostile-profile tests for root Kconfig crawl."""
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
from linux_kconfig_include_targets import literal_target  # noqa: E402
from linux_kconfig_root_closure import build, digest, jsonl, projection  # noqa: E402


def enc(value: bytes) -> str:
    return base64.b64encode(value).decode()


def git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


def paths_fixture():
    names = (b"Kconfig", b"arch/x86/Kconfig", b"arch/x86/sub/Kconfig",
             b"drivers/Kconfig", b"help/decoy", b"optional/link")
    return {
        p: {"path_b64": enc(p), "mode": "120000" if p == b"optional/link" else "100644",
            "type": "blob", "oid": (hex(i + 1)[2:] * 40)[:40], "size": 20}
        for i, p in enumerate(names)
    }


def edge(paths, path, line, kind, operand, context="DIRECTIVE_LEXICAL_CANDIDATE"):
    status, target, hit = literal_target(path, kind, operand, paths)
    return {"path_b64": enc(path), "blob_oid": paths[path]["oid"], "line": line,
            "kind": kind, "operand_b64": enc(operand), "resolution": status,
            "source_context": context, "target_path_b64": enc(target) if target else None,
            "target_oid": hit["oid"] if hit else None,
            "target_mode": hit["mode"] if hit else None}


class KconfigRootClosureTests(unittest.TestCase):
    def test_profile_variable_expansion_root_and_relative_cycles(self):
        p = paths_fixture()
        rows = [
            edge(p, b"Kconfig", 1, "source", b'"arch/$(SRCARCH)/Kconfig"'),
            edge(p, b"Kconfig", 2, "source", b'"help/decoy"', "HELP_TEXT_LEXICAL_ONLY"),
            edge(p, b"Kconfig", 3, "osource", b'"optional/link"'),
            edge(p, b"Kconfig", 4, "source", b'"arch/$(UNKNOWN)/Kconfig"'),
            edge(p, b"arch/x86/Kconfig", 1, "rsource", b'"sub/Kconfig"'),
            edge(p, b"arch/x86/Kconfig", 2, "source", b'"drivers/Kconfig"'),
            edge(p, b"arch/x86/sub/Kconfig", 1, "rsource", b'"../../x86/Kconfig"'),
            edge(p, b"drivers/Kconfig", 1, "source", b'"Kconfig"'),
            edge(p, b"help/decoy", 1, "source", b'"not/reachable"'),
        ]
        rows_out, files, counts = projection(p, rows, {"SRCARCH": "x86", "HEADER_ARCH": "x86"})
        reached = {base64.b64decode(x["path_b64"]): x["depth"] for x in files}
        self.assertEqual(reached, {b"Kconfig": 0, b"arch/x86/Kconfig": 1,
                                   b"arch/x86/sub/Kconfig": 2, b"drivers/Kconfig": 2})
        self.assertEqual(rows_out[0]["profile_source"], "EXPLICIT_VARIABLE_BINDING")
        self.assertEqual(rows_out[0]["root_route"], "FOLLOWED_TRACKED_FILE")
        self.assertEqual(rows_out[1]["root_route"], "NON_DIRECTIVE_CONTEXT")
        self.assertEqual(rows_out[2]["profile_resolution"], "TRACKED_NONREGULAR_LITERAL")
        self.assertEqual(rows_out[2]["root_route"], "REACHED_UNRESOLVED_OR_UNFOLLOWABLE")
        self.assertEqual(rows_out[3]["profile_resolution"], "UNRESOLVED_VARIABLE_GLOB_OR_ESCAPE")
        self.assertEqual(rows_out[-1]["root_route"], "SOURCE_NOT_REACHED")
        self.assertEqual(sum(counts.values()), len(rows_out))
        self.assertEqual(len(files), len(reached))

    def test_ambiguous_paths_invalid_profile_and_tampered_ledger(self):
        paths = paths_fixture()
        rows = [edge(paths, b"Kconfig", 1, "source", b'"arch/$SRCARCH/Kconfig"')]
        for bad in ({"SRCARCH": "../x86", "HEADER_ARCH": "x86"},
                    {"SRCARCH": "x86"}, {"SRCARCH": "x86", "HEADER_ARCH": "x86/" }):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                projection(paths, rows, bad)
        mutated = [dict(rows[0], target_oid="0" * 40)]
        with self.assertRaisesRegex(ValueError, "forged"):
            projection(paths, mutated, {"SRCARCH": "x86", "HEADER_ARCH": "x86"})
        nonregular = dict(paths)
        nonregular[b"Kconfig"] = {**paths[b"Kconfig"], "mode": "120000"}
        with self.assertRaisesRegex(ValueError, "root"):
            projection(nonregular, rows, {"SRCARCH": "x86", "HEADER_ARCH": "x86"})

    def test_exact_git_head_digest_and_poisoned_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "source"
            inv = Path(tmp) / "inventory"
            repo.mkdir()
            inv.mkdir()
            git(repo, "init", "-q")
            git(repo, "config", "user.name", "Test")
            git(repo, "config", "user.email", "test@invalid.example")
            (repo / "arch/x86").mkdir(parents=True)
            (repo / "Kconfig").write_bytes(b'source "arch/$(SRCARCH)/Kconfig"\n')
            (repo / "arch/x86/Kconfig").write_bytes(b'osource "missing"\n')
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "fixed fixture")
            commit = git(repo, "rev-parse", "HEAD").decode()
            tree = git(repo, "rev-parse", "HEAD^{tree}").decode()
            entries = []
            for raw in git(repo, "ls-tree", "-r", "-z", "-l", "HEAD").split(b"\0"):
                if not raw:
                    continue
                metadata, path = raw.split(b"\t", 1)
                mode, kind, oid, size = metadata.split()
                entries.append({"path_b64": enc(path), "mode": mode.decode(), "type": kind.decode(),
                                "oid": oid.decode(), "size": int(size)})
            paths = {base64.b64decode(x["path_b64"]): x for x in entries}
            all_edges = [
                edge(paths, b"Kconfig", 1, "source", b'"arch/$(SRCARCH)/Kconfig"'),
                edge(paths, b"arch/x86/Kconfig", 1, "osource", b'"missing"'),
            ]
            sources, literal_rows = jsonl(entries), jsonl(all_edges)
            raw_edges = b"original-lexical-ledger-for-hash-binding\n"
            report = {"linux_commit": commit, "linux_root_tree": tree,
                      "source_paths_sha256": digest(sources),
                      "kconfig_source_edges_sha256": digest(raw_edges),
                      "counts": {"tracked_paths": len(entries)}}
            literal_report = {
                "linux_commit": commit, "linux_root_tree": tree,
                "upstream_paths_sha256": digest(sources),
                "upstream_edges_sha256": digest(raw_edges),
                "source_sha256": digest(literal_rows),
                "status": "PARTIAL_LITERAL_TARGETS_NOT_ACTIVE_KCONFIG_GRAPH",
                "counts": {"all_lexical_edges": len(all_edges)}}
            for name, data in (("source-paths.jsonl", sources),
                               ("kconfig-literal-targets.jsonl", literal_rows),
                               ("report.json", json.dumps(report).encode()),
                               ("kconfig-literal-targets-report.json", json.dumps(literal_report).encode())):
                (inv / name).write_bytes(data)
            data, files, generated = build(repo, inv, "x86", "x86")
            self.assertEqual(generated["status"], "PARTIAL_POSSIBLE_ROOT_GRAPH_NOT_EVALUATED_KCONFIG")
            self.assertEqual(generated["counts"]["reachable_regular_files"], 2)
            self.assertEqual(generated["profile_edges_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(generated["reachable_files_sha256"], hashlib.sha256(files).hexdigest())
            self.assertFalse(generated["full_rewrite_complete"])
            (repo / "Kconfig").write_bytes(b'source "forged"\n')
            self.assertEqual(build(repo, inv, "x86", "x86")[0], data)
            poisoned = json.loads(json.dumps(literal_report))
            poisoned["source_sha256"] = "0" * 64
            (inv / "kconfig-literal-targets-report.json").write_text(json.dumps(poisoned))
            with self.assertRaisesRegex(ValueError, "tampered"):
                build(repo, inv, "x86", "x86")
            (inv / "kconfig-literal-targets-report.json").write_text(json.dumps(literal_report))
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "moved")
            with self.assertRaisesRegex(ValueError, "differs"):
                build(repo, inv, "x86", "x86")


if __name__ == "__main__":
    unittest.main()
