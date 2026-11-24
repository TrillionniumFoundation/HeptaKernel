#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
import base64
import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tree_check", ROOT / "tools/linux_inventory_tree_identity.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def main():
    with tempfile.TemporaryDirectory() as td:
        def git(*args, data=None):
            return subprocess.check_output(["git", "-C", td, *args], input=data)
        git("init", "-q")
        blob = git("hash-object", "-w", "--stdin", data=b"source").strip()
        empty = git("mktree", data=b"").strip()
        subtree = git("mktree", "-z", data=b"100644 blob " + blob + b"\tbad\xff\n\0").strip()
        root = git("mktree", "-z", data=(
            b"040000 tree " + subtree + b"\tx\0" +
            b"100755 blob " + blob + b"\tx.c\0" +
            b"120000 blob " + blob + b"\tsymlink\0" +
            b"040000 tree " + empty + b"\tempty\0")).strip().decode()
        leaves, dirs = [], []
        # Git is the independent oracle, not the implementation's serializer.
        for record in git("ls-tree", "-r", "-t", "-z", root).split(b"\0"):
            if not record:
                continue
            meta, path = record.split(b"\t", 1)
            mode, kind, oid = meta.decode().split()
            row = {"path_b64": base64.b64encode(path).decode(),
                   "mode": mode, "type": kind, "oid": oid}
            (dirs if kind == "tree" else leaves).append(row)
        assert module.reconstruct(leaves, dirs, root)["leaf_rows"] == 3
        assert module.reconstruct(leaves[::-1], dirs[::-1], root)["directory_rows"] == 2
        cases = [(leaves[:-1], dirs), (leaves, dirs[:-1]),
                 (leaves + [leaves[0]], dirs), (leaves, dirs + [dirs[0]])]
        bad = copy.deepcopy(leaves)
        bad[0]["oid"] = "0" * 40
        cases.append((bad, dirs))
        bad = copy.deepcopy(leaves)
        bad[0]["mode"] = "100755" if bad[0]["mode"] == "100644" else "100644"
        cases.append((bad, dirs))
        bad = copy.deepcopy(leaves)
        bad[0]["path_b64"] = base64.b64encode(b"forged/leaf").decode()
        cases.append((bad, dirs))
        for l, d in cases:
            try:
                module.reconstruct(l, d, root)
            except ValueError:
                pass
            else:
                raise AssertionError("accepted corrupt inventory")
        print("TREE_IDENTITY: PASS 3 leaves, 2 directories, 7 corruption controls")
if __name__ == "__main__":
    main()
