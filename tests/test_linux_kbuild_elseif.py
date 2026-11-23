#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent GNU Make and fail-closed negative controls for Kbuild else-if."""
from __future__ import annotations

import base64
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kbuild_object_activation", ROOT / "tools/linux_kbuild_object_activation.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SOURCE = b"""obj-y += baseline.o
ifeq ($(CONFIG_X),y)
obj-y += first-y.o
else ifeq ($(CONFIG_X),m)
obj-y += second-m.o
else ifneq ($(CONFIG_X),n)
obj-y += impossible.o
else
obj-y += final-n.o
endif
ifneq ($(CONFIG_X),m)
obj-y += not-m.o
else ifeq ($(CONFIG_X),m)
obj-y += yes-m.o
endif
ifeq ($(CONFIG_UNKNOWN),y)
obj-y += unknown-first.o
else ifeq ($(CONFIG_X),y)
obj-y += unknown-second.o
else
obj-y += unknown-last.o
endif
ifeq ($(CONFIG_X),y)
obj-y += known-first.o
else ifdef CONFIG_UNKNOWN
obj-y += unknown-skipped.o
else
obj-y += unknown-after.o
endif
obj-y += after.o
"""


def read_rows(source: bytes, profile: dict[bytes, bytes]):
    rows, counts = module.analyze(source, b"Makefile", b"a" * 40, profile)
    lookup = {}
    for row in rows:
        token = base64.b64decode(row["token_b64"])
        assert token not in lookup, "fixture intentionally uses unique tokens"
        lookup[token.decode("ascii")] = row["status"]
        assert row["blob_oid"] == "a" * 40
        assert row["start_byte"] < row["end_byte"] <= len(source)
    return lookup, counts


def make_objects(path: Path, value: str):
    (path / "Makefile").write_bytes(SOURCE)
    footer = b"""
.PHONY: __audit
__audit:
\t@printf '%s\\n' '$(obj-y)'
"""
    result = subprocess.run(
        ["make", "-rR", "--no-print-directory", "-f", "Makefile",
         "-f", "-", "__audit", "CONFIG_X=" + value],
        cwd=path, input=footer, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return set(result.stdout.decode("ascii").split())


def main():
    counts = {}
    with tempfile.TemporaryDirectory(prefix="hepta-kbuild-elseif-") as tmp:
        root = Path(tmp)
        expected = {
            "y": {"baseline.o", "first-y.o", "not-m.o", "known-first.o", "after.o"},
            "m": {"baseline.o", "second-m.o", "yes-m.o", "after.o"},
            "n": {"baseline.o", "final-n.o", "not-m.o", "after.o"},
        }
        unknown = {"unknown-first.o", "unknown-second.o", "unknown-last.o",
                   "unknown-skipped.o", "unknown-after.o"}
        for value, wanted in expected.items():
            profile = {b"CONFIG_X": value.encode("ascii")}
            rows, stats = read_rows(SOURCE, profile)
            assert stats["elseif_arms"] == 5, stats
            assert stats["unclosed_constructs"] == 0, stats
            assert stats["unsupported_elseif_syntax"] == 1, stats
            # The unknown CONFIG means none of these expressions can be
            # proven active, even if the following else-if is true.
            assert all(rows[name] != "ACTIVE_LEXICAL_LITERAL" for name in unknown)
            assert rows["unknown-skipped.o"] == (
                "INACTIVE_LEXICAL_LITERAL" if value == "y" else "UNRESOLVED_SCOPE_OR_CONFIG"
            )
            active = {name for name, status in rows.items()
                      if status == "ACTIVE_LEXICAL_LITERAL"}
            assert active == wanted, (value, sorted(active), sorted(wanted))
            # GNU Make is independent of the scanned ternary interpreter.
            # Its empty CONFIG_UNKNOWN follows an actual false arm, whereas
            # the scanner correctly keeps unspecified values unresolved.
            oracle = make_objects(root, value)
            assert wanted <= oracle, (value, wanted, oracle)
            assert not (oracle & ({"impossible.o"} | ({"second-m.o"} if value != "m" else set())))
            counts[value] = (len(rows), len(active))
        unprovided, _ = read_rows(SOURCE, {})
        assert unprovided["baseline.o"] == "ACTIVE_LEXICAL_LITERAL"
        assert unprovided["first-y.o"] == "UNRESOLVED_SCOPE_OR_CONFIG"
        assert unprovided["second-m.o"] == "UNRESOLVED_SCOPE_OR_CONFIG"
        assert unprovided["final-n.o"] == "UNRESOLVED_SCOPE_OR_CONFIG"
        # An impossible duplicate else or malformed clause taints the whole
        # file; even a preexisting ACTIVE row must be demoted.
        invalid = (
            b"obj-y += old.o\nifeq ($(CONFIG_X),y)\n"
            b"obj-y += first.o\nelse\nobj-y += second.o\n"
            b"else ifeq ($(CONFIG_X),m)\nobj-y += third.o\nendif\n"
        )
        bad_rows, bad = read_rows(invalid, {b"CONFIG_X": b"y"})
        assert bad["duplicate_or_post_else_clause"] == 1 and bad["unclosed_constructs"] > 0
        assert all(status != "ACTIVE_LEXICAL_LITERAL" for status in bad_rows.values())
        malformed = b"obj-y += pre.o\nifeq ($(CONFIG_X),y)\nelse garbage\nobj-y += post.o\nendif\n"
        bad_rows, bad = read_rows(malformed, {b"CONFIG_X": b"y"})
        assert bad["malformed_else_clause"] == 1 and bad["unclosed_constructs"] > 0
        assert all(status != "ACTIVE_LEXICAL_LITERAL" for status in bad_rows.values())
        orphan_rows, orphan = read_rows(b"obj-y += pre.o\nelse\nobj-y += post.o\n", {})
        assert orphan["unmatched_else"] == 1
        assert all(status != "ACTIVE_LEXICAL_LITERAL" for status in orphan_rows.values())
    print("KBUILD_ELSEIF_GNU_MAKE_DIFFERENTIAL: PASS", counts,
          "unknown and malformed fail-closed; LINUX: HOLD")


if __name__ == "__main__":
    main()
