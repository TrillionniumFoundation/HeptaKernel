#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Reconstruct Git tree identities from inventory rows, independent of ls-tree.

The root binds names, modes and object IDs, not the reported blob sizes,
Kconfig reachability, driver IDs or Linux behavior.
"""
import argparse
import base64
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

PINNED_COMMIT = "7595a62d45ee1a2297eafa5f2ef5d0a45142d84d"
PINNED_TREE = "d07c331ebf5acbde9ebf9caea9eac6e33b07ad77"
MODES = {"040000": ("tree", b"40000"), "100644": ("blob", b"100644"),
         "100755": ("blob", b"100755"), "120000": ("blob", b"120000"),
         "160000": ("commit", b"160000")}


def reconstruct(leaves, directories, root):
    if not re.fullmatch("[0-9a-f]{40}", root):
        raise ValueError("invalid trusted tree")
    nodes = {}
    children = defaultdict(list)
    for rows, is_directory in ((directories, True), (leaves, False)):
        for row in rows:
            path = base64.b64decode(row["path_b64"], validate=True)
            if (not path or b"\0" in path or
                    any(x in (b"", b".", b"..") for x in path.split(b"/"))):
                raise ValueError("invalid path")
            if path in nodes:
                raise ValueError("duplicate path")
            mode = row["mode"]
            if mode not in MODES or (mode == "040000") != is_directory:
                raise ValueError("invalid mode")
            kind, encoded_mode = MODES[mode]
            if row["type"] != kind or not re.fullmatch("[0-9a-f]{40}", row["oid"]):
                raise ValueError("invalid object identity")
            oid = bytes.fromhex(row["oid"])
            nodes[path] = (is_directory, oid)
            parent, _, name = path.rpartition(b"/")
            key = name + (b"/" if is_directory else b"\0")
            children[parent].append((key, encoded_mode + b" " + name + b"\0" + oid))
    for parent in children:
        if parent and (parent not in nodes or not nodes[parent][0]):
            raise ValueError("missing directory parent")
    # Git sorts directories as if their names ended in slash, unlike a
    # simple path sort. Check every directory including explicit empty trees.
    roots = [(p, oid.hex()) for p, (directory, oid) in nodes.items() if directory]
    roots.append((b"", root))
    for path, expected in roots:
        raw = b"".join(entry for _, entry in sorted(children[path]))
        actual = hashlib.sha1(b"tree " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if actual != expected:
            raise ValueError("tree identity mismatch: " + repr(path))
    return {"leaf_rows": len(nodes) - len(roots) + 1,
            "directory_rows": len(roots) - 1, "root_tree": root}


def verify(folder):
    report = json.loads((folder / "report.json").read_bytes())
    if report["linux_commit"] != PINNED_COMMIT or report["linux_root_tree"] != PINNED_TREE:
        raise ValueError("wrong pinned commit/tree")
    def read(name, field):
        raw = (folder / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != report[field]:
            raise ValueError("manifest digest mismatch: " + name)
        return list(map(json.loads, raw.splitlines()))
    result = reconstruct(read("source-paths.jsonl", "source_paths_sha256"),
                         read("directory-objects.jsonl", "directory_objects_sha256"),
                         PINNED_TREE)
    return {"status": "PASS_TREE_IDENTITY_ONLY", "linux_commit": PINNED_COMMIT,
            **result, "inventory_complete": False, "full_rewrite_complete": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.inventory), sort_keys=True))
