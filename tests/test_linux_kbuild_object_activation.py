#!/usr/bin/env python3
"""Independent GNU make + original Git blob oracle for partial object activation."""
from __future__ import annotations
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kbuild_activation", ROOT / "tools/linux_kbuild_object_activation.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).strip()


def create(repo):
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "drivers").mkdir()
    (repo / "Makefile").write_bytes(b"""obj-y += always.o
obj-$(CONFIG_X) += conditional.o
ifeq ($(CONFIG_X),y)
obj-y += yes.o
else
obj-y += no.o
endif
ifneq ($(CONFIG_X),m)
obj-y += notmod.o
endif
ifeq ($(CONFIG_OTHER),y)
obj-y += unknown.o
endif
ifeq ($(CONFIG_X),y)
  ifeq ($(CONFIG_OTHER),y)
obj-y += nested-unknown.o
  endif
endif
obj-y += ambiguous-$(DYNAMIC).o
obj-y += ../escape.o
# obj-y += commented.o
	obj-y += recipe-not-object.o
obj-y += continued.o \
  continued2.o
""")
    (repo / "drivers/Kbuild").write_bytes(b"obj-y := fixture.o\nifdef CONFIG_UNMODELED\nobj-y += unmodeled.o\nendif\n")
    (repo / "drivers/Kbuild.alias").symlink_to("Kbuild")
    name = os.fsencode(repo) + b"/odd_\xff"
    os.mkdir(name)
    with open(name + b"/Makefile", "wb") as out:
        out.write(b"obj-y += odd.o\r\n# opaque \xff\0\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Kbuild Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "locked"], check=True)
    return git(repo, "rev-parse", "HEAD").decode()


def make_objects(repo, state):
    # GNU make is the independent executable oracle for the supported lines.
    commands = b"\n.PHONY: __oracle\n__oracle:\n\t@printf 'Y:%s\\nM:%s\\n' '$(obj-y)' '$(obj-m)'\n"
    run = subprocess.run(["make", "--no-print-directory", "-f", "Makefile", "-f", "-", "__oracle", "CONFIG_X=" + state], input=commands, cwd=repo, check=True, stdout=subprocess.PIPE)
    return run.stdout.decode()


def rows_of(path):
    return [json.loads(s) for s in path.read_bytes().splitlines()]


def audit(repo, out, sha, state, compare_make=True):
    report = json.loads((out / "report.json").read_bytes())
    assert report["linux_commit"] == sha
    assert report["full_linux_acceptance"] == "HOLD"
    assert not report["active_objects_proven_linked"]
    raw = (out / "kbuild-object-candidates.jsonl").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["records_sha256"]
    rows = rows_of(out / "kbuild-object-candidates.jsonl")
    def names(status, path=b"Makefile"):
        return [base64.b64decode(r["token_b64"]) for r in rows
                if base64.b64decode(r["path_b64"]) == path and r["status"] == status]
    active = set(names("ACTIVE_LEXICAL_LITERAL"))
    inactive = set(names("INACTIVE_LEXICAL_LITERAL"))
    unresolved = set(names("UNRESOLVED_SCOPE_OR_CONFIG") + names("UNRESOLVED_OBJECT_EXPRESSION"))
    assert b"always.o" in active
    assert b"unknown.o" in unresolved
    assert b"nested-unknown.o" in (unresolved if state == "y" else inactive)
    assert b"ambiguous-$(DYNAMIC).o" in unresolved and b"../escape.o" in unresolved
    assert b"commented.o" not in active | inactive | unresolved
    assert b"recipe-not-object.o" not in active | inactive | unresolved
    if state == "y":
        assert {b"conditional.o", b"yes.o", b"notmod.o", b"continued.o", b"continued2.o"} <= active
        assert b"no.o" in inactive
    elif state == "m":
        assert b"conditional.o" in active and b"no.o" in active and b"notmod.o" in inactive
    else:
        assert b"conditional.o" in inactive and b"no.o" in active and b"notmod.o" in active
    # Source-byte independent oracle: every row anchored to the actual immutable blob.
    for r in rows:
        original = subprocess.check_output(["git", "-C", str(repo), "cat-file", "blob", r["blob_oid"]])
        assert hashlib.sha256(original[r["start_byte"]:r["end_byte"]]).hexdigest() == r["raw_sha256"]
        assert r["start_byte"] < r["end_byte"]
    if not compare_make:
        return len(rows)
    output = make_objects(repo, state)
    oracle_y = output.split("Y:",1)[1].split("\nM:",1)[0].split()
    oracle_m = output.split("M:",1)[1].splitlines()[0].split()
    for item in ("always.o", "continued.o", "continued2.o"):
        assert item in oracle_y and item.encode() in active
    assert ("conditional.o" in oracle_y) == (state == "y")
    assert ("conditional.o" in oracle_m) == (state == "m")
    assert (b"conditional.o" in active) == (state in ("y", "m"))
    assert ("yes.o" in oracle_y) == (state == "y")
    assert ("no.o" in oracle_y) == (state != "y")
    return len(rows)


def main():
    with tempfile.TemporaryDirectory(prefix="hia-kbuild-activation-") as tmp:
        home = Path(tmp)
        repo = home / "pinned"
        sha = create(repo)
        lock = home / "lock.json"
        lock.write_text(json.dumps({"linux":{"commit":sha}}))
        n = 0
        pristine = (repo / "Makefile").read_bytes()
        for state in ("y", "m", "n"):
            (repo / "Makefile").write_bytes(pristine)
            profile = home / (state + ".json")
            profile.write_text(json.dumps({"schema":"heptakernel.kbuild-explicit-profile.v1","values":{"CONFIG_X":state}}))
            first, second = home / (state+"1"), home / (state+"2")
            mod.build(repo, lock, profile, first)
            n += audit(repo, first, sha, state)
            (repo / "Makefile").write_text("obj-y += POISON.o\n")
            mod.build(repo, lock, profile, second)
            audit(repo, second, sha, state, compare_make=False)
            for f in ("report.json", "kbuild-object-candidates.jsonl"):
                assert (first / f).read_bytes() == (second / f).read_bytes()
        bad = home / "bad.json"
        for values in ({"CONFIG_X":"unknown"}, {"BAD":"y"}, {"CONFIG_X":True}):
            bad.write_text(json.dumps({"schema":"heptakernel.kbuild-explicit-profile.v1","values":values}))
            try:
                mod.parse_profile(bad.read_bytes())
            except ValueError:
                pass
            else:
                raise AssertionError("malformed profile accepted")
        for invalid in (b'{"schema":"heptakernel.kbuild-explicit-profile.v1","values":{"CONFIG_X":"y","CONFIG_X":"n"}}', b'{' + b' ' * (128*1024) + b'}'):
            try:
                mod.parse_profile(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("duplicate or oversized explicit profile accepted")
        wrong = home / "wrong.json"
        wrong.write_text(json.dumps({"linux":{"commit":"0"*40}}))
        try:
            mod.build(repo, wrong, profile, home / "wrong-output")
        except ValueError:
            pass
        else:
            raise AssertionError("unlocked source accepted")
    print("KBUILD_PARTIAL_OBJECT_ACTIVATION: PASS; 3 GNU make profiles, original blob oracle, hostile controls; LINUX: HOLD; rows",n)

if __name__ == "__main__":
    main()
