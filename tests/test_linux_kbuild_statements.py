#!/usr/bin/env python3
"""Adversarial Git-object and exact-source-byte oracle for Kbuild inventory."""
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
spec = importlib.util.spec_from_file_location(
    "linux_kbuild_statements", ROOT / "tools/linux_kbuild_statements.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def git(repo, *args):
    raw = subprocess.check_output(["git", "-C", str(repo), *args])
    return raw if args[:2] == ("cat-file", "blob") else raw.strip()


def create(repo):
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "drivers/net").mkdir(parents=True)
    (repo / "arch/x86").mkdir(parents=True)
    (repo / "Makefile").write_bytes(
        b"obj-$(CONFIG_CORE) += core.o \\\n"
        b"  more.o\n"
        b"# a commented obj-$(CONFIG_FAKE) += bad.o\n"
        b"include scripts/Makefile.lib\n"
        b"core-y := real.o\n")
    (repo / "drivers/net/Kbuild").write_bytes(
        b"obj-y += net/\nobj-$(CONFIG_NET) += driver.o\n")
    (repo / "arch/x86/Makefile.test").write_bytes(
        b"ifdef CONFIG_ARCH\nobj-$(CONFIG_ARCH) += a.o\nendif\n"
        b"obj-$(CONFIG_NO_EQUALS) missing.o\n")
    (repo / "drivers/net/Kbuild.link").symlink_to("Kbuild")
    name = os.fsencode(repo) + b"/drivers/odd_\xff"
    os.mkdir(name)
    with open(name + b"/Makefile", "wb") as out:
        out.write(b"obj-$(CONFIG_BINARY) += p.o\r\n"
                  b"# opaque:\x00\xff\n")
    (repo / "README").write_text("not a kbuild source\n")
    git(repo, "add", "-A")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Kbuild Test",
                    "-c", "user.email=kbuild@example.invalid",
                    "commit", "-qm", "original"], check=True)
    commit = git(repo, "rev-parse", "HEAD").decode()
    return commit


def audit(repo, output, commit):
    report = json.loads((output / "report.json").read_bytes())
    assert report["linux_commit"] == commit
    assert report["status"] == "SOURCE_ONLY_NOT_KBUILD_EVALUATION"
    assert report["full_linux_acceptance"] == "HOLD"
    assert not report["kbuild_dependency_resolution"]
    assert not report["full_linux_rewrite_complete"]
    files_data = (output / "kbuild-files.jsonl").read_bytes()
    rec_data = (output / "kbuild-statements.jsonl").read_bytes()
    assert hashlib.sha256(files_data).hexdigest() == report["files_sha256"]
    assert hashlib.sha256(rec_data).hexdigest() == report["statements_sha256"]
    files = [json.loads(x) for x in files_data.splitlines()]
    records = [json.loads(x) for x in rec_data.splitlines()]
    paths = [base64.b64decode(x["path_b64"]) for x in files]
    assert paths == sorted(paths)
    assert len(files) == 5
    assert report["counts"]["regular_sources"] == 4
    assert report["counts"]["unreadable_paths"] == 1
    assert b"drivers/odd_\xff/Makefile" in paths
    assert any(x["path"] is None for x in files)
    assert all(x["status"] in {
        "BLANK", "COMMENT", "LEXICAL_ASSIGNMENT",
        "OTHER_UNRESOLVED_MAKE_SYNTAX"} for x in records)
    assert sum(x["end_line"] > x["start_line"] for x in records) == 1
    assert sum(x["status"] == "LEXICAL_ASSIGNMENT" for x in records) == 5
    assert sum(x["status"] == "OTHER_UNRESOLVED_MAKE_SYNTAX" for x in records) == 3
    assert sum(x["status"] == "COMMENT" for x in records) == 2
    paths_seen = set()
    for f in files:
        path = base64.b64decode(f["path_b64"])
        matching = [r for r in records if base64.b64decode(r["path_b64"]) == path]
        assert path not in paths_seen
        paths_seen.add(path)
        if f["mode"] == "120000":
            assert not matching
            continue
        blob = git(repo, "cat-file", "blob", f["oid"])
        assert f["size"] == len(blob)
        cursor = 0
        for r in matching:
            raw = base64.b64decode(r["raw_b64"])
            assert r["blob_oid"] == f["oid"]
            assert r["start_byte"] == cursor
            assert blob[cursor:r["end_byte"]] == raw
            cursor = r["end_byte"]
        assert cursor == len(blob)
        assert b"".join(base64.b64decode(x["raw_b64"])
                        for x in matching) == blob
    obj = next(x for x in records
               if base64.b64decode(x["path_b64"]) == b"Makefile"
               and x["start_line"] == 1)
    assert obj["end_line"] == 2
    assert base64.b64decode(obj["lhs_b64"]) == b"obj-$(CONFIG_CORE)"
    assert obj["operator"] == "+="
    assert base64.b64decode(obj["rhs_b64"]) == b"core.o  more.o"
    assert obj["config_refs_b64"] == [
        base64.b64encode(b"CONFIG_CORE").decode()]


def main():
    with tempfile.TemporaryDirectory(prefix="hepta-kbuild-fixture-") as tmp:
        root = Path(tmp)
        repo = root / "upstream"
        commit = create(repo)
        lock = root / "lock.json"
        lock.write_text(json.dumps({"linux": {"commit": commit}}))
        first = root / "first"
        mod.build(repo, lock, first)
        audit(repo, first, commit)

        (repo / "Makefile").write_text("obj-y += POISON.o\n")
        second = root / "second"
        mod.build(repo, lock, second)
        audit(repo, second, commit)
        for n in ("kbuild-files.jsonl", "kbuild-statements.jsonl", "report.json"):
            assert (first / n).read_bytes() == (second / n).read_bytes()

        wrong = root / "wrong.json"
        wrong.write_text(json.dumps({"linux": {"commit": "0" * 40}}))
        rejected = root / "must-not-exist"
        try:
            mod.build(repo, wrong, rejected)
        except ValueError as exc:
            assert "HEAD mismatch" in str(exc)
        else:
            raise AssertionError("wrong immutable Linux commit accepted")
        assert not rejected.exists()
    print("KBUILD_SOURCE_ONLY: PASS; paths=5, regular=4, source replay exact; LINUX: HOLD")


if __name__ == "__main__":
    main()
