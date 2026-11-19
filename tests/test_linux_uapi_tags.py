#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial source/offset/origin tests of the separate lexical UAPI inventory."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_uapi_tags import collect, extract, tokens  # noqa: E402


def call(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


class UapiLexicalTests(unittest.TestCase):
    HEADER = (b'/* struct ghost { }; */\n'
              b'const char *s = "union lie { }";\n'
              b'// enum another { };\n'
              b'struct\n visible { int x; };\n'
              b'union anonymous { int y; };\n'
              b'enum sample { A = 1 };\n'
              b'struct visible *p;\n'
              b'struct forward;\n'
              b'__attribute__((unused)) struct { char c; };\n'
              b'char q = \'\\\'\';\n')

    def test_positions_definitions_and_no_false_comment_tokens(self):
        records = list(extract(self.HEADER))
        observed = [(r["tag"], base64.b64decode(r["name_b64"]) if r["name_b64"] else None,
                     r["classification"]) for r in records]
        self.assertEqual(observed, [
            ("struct", b"visible", "NAMED_DEFINITION"),
            ("union", b"anonymous", "NAMED_DEFINITION"),
            ("enum", b"sample", "NAMED_DEFINITION"),
            ("struct", b"visible", "NAMED_REFERENCE_OR_MACRO"),
            ("struct", b"forward", "NAMED_FORWARD_OR_ELABORATED"),
            ("struct", None, "ANONYMOUS_DEFINITION"),
        ])
        # Independent literal byte-position/readback oracle, without the lexer.
        offsets = [self.HEADER.find(b"struct\n visible"),
                   self.HEADER.find(b"union anonymous"),
                   self.HEADER.find(b"enum sample"),
                   self.HEADER.find(b"struct visible"),
                   self.HEADER.find(b"struct forward"),
                   self.HEADER.find(b"struct {")]
        self.assertEqual([r["byte_at"] for r in records], offsets)
        for row in records:
            at = row["byte_at"]
            self.assertEqual(self.HEADER[at:at + len(row["tag"])], row["tag"].encode())
            self.assertEqual(row["line"], self.HEADER[:at].count(b"\n") + 1)
            if row["name_byte_at"] is not None:
                name = base64.b64decode(row["name_b64"])
                self.assertEqual(self.HEADER[row["name_byte_at"]:row["name_byte_at"] + len(name)],
                                 name)

    def test_unterminated_source_is_rejected(self):
        for data in (b"struct ok; /* incomplete",
                     b"struct ok; \"incomplete",
                     b"struct ok; '\\"):
            with self.assertRaises(ValueError):
                list(tokens(data))

    def test_phase_two_splicing_comment_hiding_and_physical_origin(self):
        # A backslash-newline continues // comments and can split C identifiers,
        # including keywords. The original byte offsets must not be collapsed.
        source = (b'// ignored \\\nstruct phantom { };\n'
                  b'/\\\n* union hidden { }; */\n'
                  b'str\\\nuct visible { int a; };\n'
                  b'en\\\r\num state { A };\n'
                  b'union name\\\r\n_spliced { char b; };\n'
                  b'const char *s = "struct \\'
                  b'\n should_not_appear";\n')
        found = list(extract(source))
        self.assertEqual([(r["tag"],
                           base64.b64decode(r["name_b64"]) if r["name_b64"] else None)
                          for r in found],
                         [("struct", b"visible"), ("enum", b"state"),
                          ("union", b"name_spliced")])
        self.assertEqual([r["raw_span"] for r in found], [8, 7, 5])
        self.assertEqual([r["name_raw_span"] for r in found], [7, 5, 15])
        # Independent physical-to-logical source readback, including CRLF.
        for row in found:
            for offset, span, expected in (
                (row["byte_at"], row["raw_span"], row["tag"].encode()),
                (row["name_byte_at"], row["name_raw_span"],
                 base64.b64decode(row["name_b64"]))):
                raw = source[offset:offset + span]
                self.assertEqual(raw.replace(b"\\\r\n", b"")
                                    .replace(b"\\\n", b""), expected)
            self.assertEqual(row["line"],
                             source[:row["byte_at"]].count(b"\n") + 1)

    def test_splicing_before_comment_and_literal_completion(self):
        self.assertEqual(list(extract(b'// hide \\\nstruct shadow;')), [])
        self.assertEqual(list(extract(b'/\\\n* enum fake; */')), [])
        self.assertEqual(list(extract(b'"union \\'
                                      b'\n hidden"; struct visible;'))[0]["tag"],
                         "struct")
        for malformed in (b'struct visible; /\\\n* unterminated',
                          b'struct visible; "unterminated \\\n'):
            with self.assertRaises(ValueError):
                list(tokens(malformed))

    def test_immutable_pinned_git_blob_and_head_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            call(repo, "init", "-q")
            call(repo, "config", "user.name", "Inventory Test")
            call(repo, "config", "user.email", "inventory@example.test")
            header = repo / "include/uapi/linux/demo.h"
            header.parent.mkdir(parents=True)
            header.write_bytes(self.HEADER)
            arch = repo / "arch/x86/include/uapi/asm/second.h"
            arch.parent.mkdir(parents=True)
            arch.write_bytes(b"enum q { E };\n")
            ignored = repo / "drivers/demo.c"
            ignored.parent.mkdir(parents=True)
            ignored.write_bytes(b"struct dont_count { int x; };")
            call(repo, "add", ".")
            call(repo, "commit", "-qm", "fixture")
            commit = call(repo, "rev-parse", "HEAD").decode("ascii")
            original, report = collect(repo, commit)
            rows = [json.loads(x) for x in original.splitlines()]
            self.assertEqual(report["linux_commit"], commit)
            self.assertEqual(report["records"], 7)
            self.assertEqual(report["counts"]["headers"], 2)
            self.assertFalse(report["inventory_complete"])
            self.assertEqual(hashlib.sha256(original).hexdigest(), report["source_sha256"])
            self.assertTrue(all(b"drivers/" not in base64.b64decode(x["path_b64"]) for x in rows))
            # Editing the worktree does not affect immutable commit blobs.
            header.write_bytes(b"struct forgery { int bad; };")
            self.assertEqual(collect(repo, commit)[0], original)
            call(repo, "add", ".")
            call(repo, "commit", "-qm", "second fixture")
            with self.assertRaisesRegex(ValueError, "HEAD differs"):
                collect(repo, commit)


if __name__ == "__main__":
    unittest.main()
