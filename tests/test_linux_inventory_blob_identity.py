#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
import base64
import copy
import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from linux_inventory_blob_identity import audit_objects, consume_batch, expectations
from linux_inventory_tree_identity import reconstruct


def reject(operation):
    try:
        operation()
    except ValueError:
        return
    raise AssertionError("accepted corrupted blob evidence")


def main():
    with tempfile.TemporaryDirectory() as folder:
        def git(*args, data=None):
            return subprocess.check_output(["git", "-C", folder, *args], input=data)
        git("init", "-q")
        payloads = [b"", b"\x00\xff\n", bytes(range(256)) * 4097]
        ids = [git("hash-object", "-w", "--stdin", data=data).strip()
               for data in payloads]
        fake_gitlink = b"9" * 40
        root = git("mktree", "-z", "--missing", data=(
            b"100644 blob " + ids[0] + b"\tempty\0" +
            b"100755 blob " + ids[1] + b"\texec\0" +
            b"120000 blob " + ids[1] + b"\tlink\0" +
            b"100644 blob " + ids[2] + b"\tlarge\xff\n\0" +
            b"160000 commit " + fake_gitlink + b"\texternal\0")).strip().decode()
        leaves = []
        for row in git("ls-tree", "-r", "-z", "-l", root).split(b"\0"):
            if not row:
                continue
            meta, path = row.split(b"\t", 1)
            mode, kind, oid, size = meta.decode().split()
            leaves.append({"path_b64": base64.b64encode(path).decode(),
                           "mode": mode, "type": kind, "oid": oid,
                           "size": None if size == "-" else int(size)})
        assert reconstruct(leaves, [], root)["leaf_rows"] == 5
        records, external = audit_objects(Path(folder), leaves)
        independent = {oid.decode(): hashlib.sha256(data).hexdigest()
                       for oid, data in zip(ids, payloads)}
        assert {r["oid"]: r["content_sha256"] for r in records} == independent
        assert len(records) == 3 and sum(r["paths"] for r in records) == 4
        assert external == [{"path_b64": base64.b64encode(b"external").decode(),
                             "oid": fake_gitlink.decode()}]
        assert audit_objects(Path(folder), leaves[::-1])[0] == records
        for mutation in ("size", "bool", "wrong-type", "missing"):
            bad = copy.deepcopy(leaves)
            row = next(r for r in bad if r["oid"] == ids[0].decode())
            if mutation == "size": row["size"] += 1
            elif mutation == "bool": row["size"] = False
            elif mutation == "wrong-type": row["type"] = "tree"
            else: row["oid"] = "1" * 40
            reject(lambda: audit_objects(Path(folder), bad))
        inconsistent = copy.deepcopy(leaves)
        repeated = [row for row in inconsistent if row["oid"] == ids[1].decode()]
        repeated[0]["size"] += 1
        reject(lambda: expectations(inconsistent))
        oid = ids[1].decode()
        data = payloads[1]
        expected = {oid: [len(data), 1]}
        frame = f"{oid} blob {len(data)}\n".encode() + data + b"\n"
        assert list(consume_batch(io.BytesIO(frame), expected))[0]["content_sha256"] == independent[oid]
        for malformed in (frame[:-2], frame[:-1], frame + b"extra",
                          frame.replace(b"blob", b"tree", 1),
                          frame.replace(data, b"\x00\xfe\n", 1),
                          frame.replace(oid.encode(), b"0" * 40, 1)):
            reject(lambda: list(consume_batch(io.BytesIO(malformed), expected)))
        print("BLOB_CONTENT_IDENTITY: PASS 3 unique blobs, 4 blob paths, 1 external gitlink, 11 corruption controls")


if __name__ == "__main__":
    main()
