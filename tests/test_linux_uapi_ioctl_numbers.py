#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Adversarial independent oracles for conservative ioctl-number candidates."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from linux_uapi_ioctl_macros import scan_defines
from linux_uapi_ioctl_numbers import build, literal, mask_comments, project, project_row


def fixture(root: Path):
    body = (
        b"#define TIO _IO('T', 1)\n"
        b"#define TREAD _IOR('T', 2, int)\n"
        b"#define TIOC _IOC(_IOC_READ, 'x', 3, 2)\n"
        b"#define TUNK _IO(MAGIC, 1)\n"
        b"#define TC /* _IO('T',5) */ _IO('x', 6)\n"
        b"#define TMULTI _IO(\\\n"
        b" 'T', 7)\n"
        b"#define BAD _IOC(_IOC_READ, 'x', 999, 2)\n"
        b"#define SIZE _IOC(0, 'A', 5, sizeof(int))\n"
        b"#define ARITY _IO('T')\n"
        b"#define NOEND _IO('T', 1\n"
        b"#define OCT _IO('T', 010)\n"
        b"#define STRING \"_IO('T', 12)\"\n"
    )
    rows = scan_defines(body)
    assert len(rows) == 12, len(rows)
    records = [{
        "path_b64": base64.b64encode(b"include/uapi/linux/synthetic.h").decode(),
        "blob_oid": "a" * 40,
        **row,
    } for row in rows]
    source = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":"))
                        + "\n").encode("ascii") for row in records)
    counts = {
        "ioctl_macro_definitions": len(records),
        "ioctl_calls": sum(len(row["io_calls"]) for row in records),
    }
    (root / "uapi-ioctl-macro-obligations.jsonl").write_bytes(source)
    (root / "uapi-ioctl-report.json").write_text(json.dumps({
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "records": len(records),
        "counts": counts,
        "linux_commit": "1" * 40,
        "linux_root_tree": "2" * 40,
    }))
    return records, source


def expect_error(func, fragment):
    try:
        func()
    except ValueError as ex:
        assert fragment in str(ex), (str(ex), fragment)
    else:
        raise AssertionError("unsafe inventory accepted: " + fragment)


def main():
    assert literal(b"'T'") == 84
    assert literal(b"010") == 8
    assert literal(b"0x20UL") == 32
    assert literal(b"_IOC_READ") == 2
    assert literal(b"(0x20)") == 32
    assert literal(b"-1") is None
    assert literal(b"7 | 1") is None
    assert project("_IO", [b"'T'", b"1"]) == (
        "X86_64_GENERIC_NUMERIC_CANDIDATE", 0x5401)
    assert project("_IOC", [b"_IOC_READ", b"'x'", b"3", b"2"]) == (
        "X86_64_GENERIC_NUMERIC_CANDIDATE", 0x80027803)
    assert project("_IOR", [b"'T'", b"2", b"int"])[0] == "SIZEOF_TYPE_UNRESOLVED"
    assert project("_IO", [b"0x100", b"1"])[0] == "FIELD_RANGE_UNRESOLVED"
    assert project("_IOC", [b"4", b"1", b"2", b"0"])[0] == "FIELD_RANGE_UNRESOLVED"
    assert project("_IOC", [b"0", b"1", b"2", b"16384"])[0] == "FIELD_RANGE_UNRESOLVED"
    masked = mask_comments(b"'/*' /* _IO(1,1) */ _IO(2,2)")
    assert masked.startswith(b"    ")
    assert b"_IO(1,1)" not in masked
    assert b"_IO(2,2)" in masked
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        records, original = fixture(root)
        data, report = build(root)
        cases = [json.loads(line) for line in data.splitlines()]
        assert len(cases) == report["invocations"] == 13
        assert report["source_rows"] == 12
        assert report["linux_commit"] == "1" * 40
        assert report["linux_root_tree"] == "2" * 40
        assert report["parent_source_sha256"] == hashlib.sha256(original).hexdigest()
        assert report["projection_sha256"] == hashlib.sha256(data).hexdigest()
        assert not report["full_rewrite_complete"] and not report["inventory_complete"]
        assert [x["status"] for x in cases] == [
            "X86_64_GENERIC_NUMERIC_CANDIDATE",
            "SIZEOF_TYPE_UNRESOLVED",
            "X86_64_GENERIC_NUMERIC_CANDIDATE",
            "EXPRESSION_UNRESOLVED",
            "NONCODE_LEXICAL_ONLY",
            "X86_64_GENERIC_NUMERIC_CANDIDATE",
            "X86_64_GENERIC_NUMERIC_CANDIDATE",
            "FIELD_RANGE_UNRESOLVED",
            "EXPRESSION_UNRESOLVED",
            "ARITY_UNRESOLVED",
            "UNBALANCED_INVOCATION",
            "X86_64_GENERIC_NUMERIC_CANDIDATE",
            "NONCODE_LEXICAL_ONLY",
        ]
        assert [x["number"] for x in cases if x["number"] is not None] == [
            0x5401, 0x80027803, 0x7806, 0x5407, 0x5408]
        assert all(x["preprocessor_reachability_verified"] is False
                   and x["linux_ioctl_implementation_verified"] is False for x in cases)
        for x in cases:
            row = records[next(i for i,r in enumerate(records)
                               if r["start_byte"] == x["source_start_byte"])]
            raw = base64.b64decode(row["raw_b64"])
            absolute = x["source_call_byte"] - row["start_byte"]
            assert raw[absolute:absolute+len(x["call"])] == x["call"].encode()
        # Remove an invocation while keeping stale signed source inventory:
        # its integrity hash, row count and oracle must not silently pass.
        path = root / "uapi-ioctl-macro-obligations.jsonl"
        path.write_bytes(original.replace(b"0x5401", b"0x5402") + b" ")
        expect_error(lambda: build(root), "source inventory hash mismatch")
        path.write_bytes(original)
        bad = dict(records[0], io_calls=["_IOC"])
        expect_error(lambda: project_row(bad), "diverged")
        (root / "uapi-ioctl-report.json").write_text(json.dumps({
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "records": len(records), "counts": {"ioctl_calls": 1},
            "linux_commit": "1" * 40, "linux_root_tree": "2" * 40,
        }))
        expect_error(lambda: build(root), "did not preserve source calls")
    print("UAPI_IOCTL_X86_64_INDEPENDENT_ORACLE: PASS")
    print("UAPI_IOCTL_REAL_ABI_IMPLEMENTATION: HOLD")


if __name__ == "__main__":
    main()
