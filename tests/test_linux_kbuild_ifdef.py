#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""GNU Make differential, unknown-profile and malformed ifdef/ifndef controls."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "kbuild_activation_ifdef", ROOT / "tools/linux_kbuild_object_activation.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SOURCE = b"""obj-y += baseline.o
ifdef CONFIG_X
obj-y += defined.o
else
obj-y += undefined.o
endif
ifndef CONFIG_X
obj-y += absent.o
else
obj-y += present.o
endif
ifndef CONFIG_X
obj-y += first.o
else ifdef CONFIG_Y
obj-y += second.o
else
obj-y += third.o
endif
ifdef CONFIG_X
obj-y += known-first.o
else ifndef CONFIG_UNKNOWN
obj-y += known-unreachable.o
else
obj-y += known-unreachable-else.o
endif
ifndef CONFIG_UNKNOWN
obj-y += unknown-first.o
else ifdef CONFIG_X
obj-y += unknown-second.o
else
obj-y += unknown-last.o
endif
obj-y += final.o
"""
UNKNOWN = {"unknown-first.o", "unknown-second.o", "unknown-last.o"}
WANTED = {"baseline.o", "defined.o", "present.o", "second.o", "known-first.o", "final.o"}


def scan(source, profile):
    rows, counts = mod.analyze(source, b"Makefile", b"a" * 40, profile)
    found = {}
    for item in rows:
        name = base64.b64decode(item["token_b64"]).decode("ascii")
        assert name not in found, "fixture tokens must be distinct"
        found[name] = item["status"]
        start, end = item["start_byte"], item["end_byte"]
        assert hashlib.sha256(source[start:end]).hexdigest() == item["raw_sha256"]
        assert item["blob_oid"] == "a" * 40
    return found, counts


def oracle(path, x, y):
    (path / "Makefile").write_bytes(SOURCE)
    footer = b"""
.PHONY: __check
__check:
\t@printf '%s\\n' '$(obj-y)'
"""
    run = subprocess.run(
        ["make", "-rR", "--no-print-directory", "-f", "Makefile", "-f", "-",
         "__check", "CONFIG_X=" + x, "CONFIG_Y=" + y],
        cwd=path, input=footer, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=True,
    )
    return set(run.stdout.decode("ascii").split())


def main():
    with tempfile.TemporaryDirectory(prefix="hia-kbuild-ifdef-") as tmp:
        path = Path(tmp)
        for x in ("y", "m", "n"):
            for y in ("y", "m", "n"):
                profile = {b"CONFIG_X": x.encode("ascii"),
                           b"CONFIG_Y": y.encode("ascii")}
                found, counts = scan(SOURCE, profile)
                active = {name for name, status in found.items()
                          if status == "ACTIVE_LEXICAL_LITERAL"}
                assert active == WANTED, (x, y, active)
                assert all(found[name] == "UNRESOLVED_SCOPE_OR_CONFIG"
                           for name in UNKNOWN)
                assert found["known-unreachable.o"] == "INACTIVE_LEXICAL_LITERAL"
                assert found["known-unreachable-else.o"] == "INACTIVE_LEXICAL_LITERAL"
                assert counts["unsupported_conditional_syntax"] == 0, counts
                assert counts["unsupported_elseif_syntax"] == 0, counts
                assert counts["elseif_arms"] == 3, counts
                assert counts["unclosed_constructs"] == 0, counts
                assert oracle(path, x, y) - UNKNOWN == WANTED
                # Dishonest control: treating CONFIG_X=n as undefined would
                # disagree with real GNU Make for 'ifdef CONFIG_X'.
                if x == "n":
                    assert "defined.o" in oracle(path, x, y)
                    assert "undefined.o" not in oracle(path, x, y)
        absent, _ = scan(SOURCE, {})
        assert absent["baseline.o"] == "ACTIVE_LEXICAL_LITERAL"
        for name in ("defined.o", "undefined.o", "absent.o", "present.o",
                     "first.o", "second.o", "third.o"):
            assert absent[name] == "UNRESOLVED_SCOPE_OR_CONFIG", (name, absent[name])
        # Unsupported syntax must not be read as a definite false condition.
        malformed = (b"obj-y += before.o\\nifdef $(CONFIG_X)\\n"
                     b"obj-y += wrong.o\\nelse\\nobj-y += other.o\\nendif\\n")
        malformed = malformed.replace(b"\\n", b"\n")
        entries, stats = scan(malformed, {b"CONFIG_X": b"y"})
        assert stats["unsupported_conditional_syntax"] == 1
        assert entries["wrong.o"] == entries["other.o"] == "UNRESOLVED_SCOPE_OR_CONFIG"
        # A syntactically impossible duplicate else invalidates the whole file.
        duplicate = (b"obj-y += before.o\nifdef CONFIG_X\n"
                     b"obj-y += true.o\nelse\nobj-y += false.o\n"
                     b"else ifndef CONFIG_Y\nobj-y += late.o\nendif\n")
        entries, stats = scan(duplicate, {b"CONFIG_X": b"y", b"CONFIG_Y": b"n"})
        assert stats["duplicate_or_post_else_clause"] == 1
        assert all(status != "ACTIVE_LEXICAL_LITERAL" for status in entries.values())
    print("KBUILD_IFDEF_GNU_MAKE_DIFFERENTIAL: PASS; 9 known profiles, "
          "unknown/invalid/negative controls; FULL_LINUX_REWRITE: HOLD")


if __name__ == "__main__":
    main()
