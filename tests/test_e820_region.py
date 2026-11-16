#!/usr/bin/env python3
"""Independent contract model for the actual native HIA E820 region admission gate."""
import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

PAGE = 4096
LIMIT = 1 << 52
MAX = (1 << 64) - 1


def object_text(path):
    data = Path(path).read_bytes()
    assert data[:6] == b"\x7fELF\x02\x01"
    offset = struct.unpack_from("<Q", data, 40)[0]
    width, count, strings = struct.unpack_from("<3H", data, 58)
    heads = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * width) for i in range(count)]
    names = data[heads[strings][4]:heads[strings][4] + heads[strings][5]]
    for h in heads:
        if names[h[0]:].split(b"\0", 1)[0] == b".text":
            return data[h[4]:h[4] + h[5]]
    raise AssertionError("missing ELF .text")


def oracle(data, reply_length):
    if reply_length < 16:
        return 1, None
    if len(data) < 24:
        return 2, 0
    base, pages, count = struct.unpack_from("<3Q", data)
    if count > 128 or len(data) != 24 + count * 24:
        return 2, 0
    if not (1 <= pages <= 65536 and base % PAGE == 0
            and base < LIMIT and pages * PAGE <= LIMIT - base):
        return 6, 0
    end = base + pages * PAGE
    usable = []
    has_exclusion = False
    for i in range(count):
        x, length, kind, attr = struct.unpack_from("<QQII", data, 24 + i * 24)
        if length == 0 or x > MAX - length:
            return 6, 0
        enabled = bool(attr & 1)
        nonvolatile = bool(attr & 2)  # ACPI 3.0 extended E820 attribute bit 1
        if enabled and kind == 1 and not nonvolatile:
            usable.append((x, x + length))
        if enabled and (kind != 1 or nonvolatile) and x < end and x + length > base:
            has_exclusion = True
    # Independent sorted-interval oracle; HIA uses repeated unsorted scans.
    cursor = base
    for low, high in sorted(usable):
        if low > cursor:
            break
        cursor = max(cursor, high)
        if cursor >= end:
            break
    return (0, pages) if cursor >= end and not has_exclusion else (5, 0)


def encode(base, pages, rows, count=None):
    return struct.pack("<3Q", base, pages, len(rows) if count is None else count) + b"".join(
        struct.pack("<QQII", *r) for r in rows)


def campaign(path):
    library = ctypes.CDLL(str(path.resolve()))
    entry = library.f0
    entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    entry.restype = ctypes.c_uint32
    checks = 0
    case_names = []

    def call(data, reply_length=16):
        nonlocal checks
        # Distinct disjoint external capability regions; readback proves purity.
        raw = ctypes.create_string_buffer(b"\xaa" * 32 + data + b"\xaa" * 32)
        reply = ctypes.create_string_buffer(b"\xbb" * (reply_length + 64))
        state = ctypes.create_string_buffer(b"\xcc" * 64)
        original_raw = bytes(raw)
        original_state = bytes(state)
        returned = entry(ctypes.addressof(raw) + 32, len(data),
                         ctypes.addressof(reply) + 32, reply_length,
                         state, len(state))
        expected, value = oracle(data, reply_length)
        assert returned == expected, (checks, returned, expected, data.hex())
        assert bytes(raw) == original_raw, (checks, "request mutated")
        assert bytes(state) == original_state, (checks, "state mutated")
        rb = bytes(reply)
        assert rb[:32] == b"\xbb" * 32
        assert rb[32 + reply_length:] == b"\xbb" * 32 + b"\0"
        if reply_length < 16:
            assert rb[32:32 + reply_length] == b"\xbb" * reply_length
        else:
            assert struct.unpack("<2Q", rb[32:48]) == (expected, value)
            assert rb[48:32 + reply_length] == b"\xbb" * (reply_length - 16)
        checks += 1

    usable = [(0, LIMIT, 1, 1)]
    fixed = [
        (encode(0, 1, usable), 16),
        (encode(0, 65536, usable), 16),
        (encode(LIMIT - PAGE, 1, usable), 16),
        (encode(0, 0, usable), 16),
        (encode(1, 1, usable), 16),
        (encode(LIMIT - PAGE, 2, usable), 16),
        (encode(0, 65537, usable), 16),
        (encode(0, 1, []), 16),
        (encode(0, 1, [(0, PAGE, 1, 0)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 1), (PAGE, PAGE, 2, 1)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 1), (0, PAGE, 2, 1)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 1), (0, PAGE, 2, 0)]), 16),
        (encode(PAGE, 1, [(0, 2 * PAGE, 1, 1), (0, PAGE, 2, 1)]), 16),
        (encode(0, 2, [(0, PAGE, 1, 1), (PAGE, PAGE, 1, 1)]), 16),
        (encode(0, 2, [(0, PAGE, 1, 1), (PAGE, PAGE, 1, 1), (0, 2*PAGE, 1, 1)]), 16),
        (encode(0, 1, [(MAX, 2, 1, 1)]), 16),
        (encode(0, 1, [(0, 0, 1, 1)]), 16),
        (encode(0, 1, [(0, PAGE, 0, 1)]), 16),
        (encode(0, 1, [(0, PAGE, 3, 1)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 2)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 3)]), 16),  # persistent RAM is unavailable
        (encode(0, 1, [(0, PAGE, 1, 1), (0, PAGE, 1, 3)]), 16),
        (encode(0, 2, [(0, 2 * PAGE, 1, 1), (PAGE, 1, 1, 3)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 1), (0, PAGE, 1, 2)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 0xFFFFFFFD)]), 16),
        (encode(0, 1, [(0, PAGE, 1, 1), (PAGE, PAGE, 1, 3)]), 16),
        # Adjacent/overlapping, reverse-ordered and reserved fragments.
        (encode(0, 2, [(PAGE, PAGE, 1, 1), (0, PAGE, 1, 1)]), 16),
        (encode(0, 3, [(2 * PAGE, PAGE, 1, 1),
                       (0, 2 * PAGE, 1, 1)]), 16),
        (encode(0, 3, [(PAGE, 2 * PAGE, 1, 1),
                       (0, 2 * PAGE, 1, 1)]), 16),
        (encode(0, 3, [(2 * PAGE, PAGE, 1, 1),
                       (0, PAGE, 1, 1)]), 16),
        (encode(0, 2, [(0, PAGE, 1, 1),
                       (PAGE, PAGE, 1, 0)]), 16),
        (encode(0, 2, [(PAGE, PAGE, 1, 1),
                       (0, PAGE, 1, 1),
                       (PAGE, 1, 2, 1)]), 16),
        (encode(0, 2, [(PAGE, PAGE, 1, 1),
                       (0, PAGE, 1, 1),
                       (0, PAGE, 2, 0)]), 16),
        (encode(0, 2, [(0, 2 * PAGE, 1, 1),
                       (MAX, 2, 2, 1)]), 16),
        (encode(LIMIT - 3 * PAGE, 3,
                [(LIMIT - PAGE, PAGE, 1, 1),
                 (LIMIT - 3 * PAGE, 2 * PAGE, 1, 1)]), 16),
        (encode(0, 128, list(reversed(
            [(i * PAGE, PAGE, 1, 1) for i in range(128)]))), 16),
        (encode(0, 1, usable * 128), 16),
        (encode(0, 1, usable * 129), 16),
        (encode(0, 1, usable, count=128), 16),
        (encode(0, 1, usable, count=MAX), 16),
        (encode(0, 1, usable)[:-1], 16),
        (encode(0, 1, usable) + b"\0", 16),
        (b"", 16), (b"\0" * 23, 16),
        (encode(0, 1, usable), 0),
        (encode(0, 1, usable), 15),
        (encode(0, 1, usable), 17),
        (encode(0, 1, usable), 32),
    ]
    for data, rlen in fixed:
        call(data, rlen)
    case_names.append(f"{len(fixed)} deterministic positive, fragmented, geometry, overflow, attribute, nonvolatile precedence, overlap and rejection cases")
    rng = random.Random(0xE82020261116)
    for i in range(3000):
        pages = rng.choice([0, 1, 2, 3, 8, 65, 65536, 65537])
        base = rng.choice([0, PAGE, 0x100000, LIMIT - PAGE, MAX,
                           rng.randrange(0, 256) * PAGE, rng.randrange(0, 256) * PAGE + 1])
        rows = []
        for _ in range(rng.randrange(0, 30)):
            x = rng.choice([0, PAGE, 0x100000, base if base < LIMIT else 0,
                            rng.randrange(0, 512) * PAGE, MAX])
            length = rng.choice([0, 1, PAGE, PAGE * 2, PAGE * 1024, LIMIT, MAX])
            kind = rng.choice([0, 1, 1, 1, 2, 3, 4, MAX & 0xFFFFFFFF])
            attr = rng.choice([0, 1, 1, 1, 2, 3, 0xFFFFFFFF])
            rows.append((x, length, kind, attr))
        data = encode(base, pages, rows)
        if i % 31 == 0:
            data += b"\0"  # exact-length rejection
        if i % 37 == 0 and len(data) > 24:
            data = data[:-1]
        call(data, rng.choice([16, 16, 16, 16, 15, 24]))
    # Force multi-entry unions, gaps, disabled intervals and reservations.
    # Every map is shuffled; the independent oracle sorts before merging.
    for i in range(640):
        pages = rng.randrange(2, 33)
        base = rng.randrange(0, 512) * PAGE
        offsets = sorted({0, pages, *[rng.randrange(1, pages) for _ in range(8)]})
        rows = [(base + offsets[k] * PAGE,
                 (offsets[k+1] - offsets[k]) * PAGE, 1, 1)
                for k in range(len(offsets) - 1)]
        if i % 4 == 1:
            k = rng.randrange(len(rows))
            x, length, kind, attr = rows[k]
            rows[k] = (x, length, kind, 0)  # disabled coverage
        if i % 4 == 2:
            rows.append((base + rng.randrange(pages) * PAGE,
                         1, 2, 1))  # active reserved overlay
        if i % 4 == 3:
            k = rng.randrange(len(rows))
            x, length, kind, attr = rows[k]
            rows[k] = (x, length - 1, kind, attr)  # one-byte hole
        rng.shuffle(rows)
        call(encode(base, pages, rows))
    case_names.append("640 shuffled multi-entry RAM unions, disabled fragments, holes and reservation overlays")
    case_names.append("3000 fixed-seed independent-oracle traces including malformed lengths and unsorted overlapping maps")
    return checks, case_names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--report", type=Path, default=Path("build/e820-region-report.json"))
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    if args.expect_unsafe:
        # The deliberately incorrect HIA code must issue success for a region
        # overlapping an enabled E820 reservation. The independent oracle
        # must disagree, proving it is able to reject this false success.
        data = encode(0, 1, [(0, PAGE, 1, 1), (0, PAGE, 2, 1)])
        assert oracle(data, 16) == (5, 0)
        library = ctypes.CDLL(str(args.library.resolve()))
        entry = library.f0
        entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        entry.restype = ctypes.c_uint32
        request = ctypes.create_string_buffer(data)
        reply = ctypes.create_string_buffer(16)
        state = ctypes.create_string_buffer(16)
        returned = entry(request, len(data), reply, 16, state, 16)
        actual = struct.unpack("<2Q", reply.raw)
        assert (returned, *actual) == (0, 0, 1024), (returned, actual)
        assert (returned, actual[1]) != oracle(data, 16)
        print(json.dumps({"negative_control":"unsafe HIA always-allow E820",
                          "observed_status":returned,"oracle_status":5,"status":"REJECTED"}))
        return
    assert object_text(args.library) == object_text("build/e820-region.o")
    report = {"schema":"heptakernel.e820-region-native.v1", "scope":"canonicalized supplied E820 region admission, not firmware discovery", "linux_compatibility_tested":False, "boot_integration_tested":False,
              "source_sha256":hashlib.sha256(Path("src/e820_region.hepta").read_bytes()).hexdigest(),
              "object_sha256":hashlib.sha256(Path("build/e820-region.o").read_bytes()).hexdigest(),
              "library_sha256":hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "library_text_matches_hia_object":True}
    try:
        checks, cases = campaign(args.library)
        report.update(status="PASS",calls=checks,cases=cases)
    except BaseException as exc:
        report.update(status="FAIL",error=repr(exc))
        raise
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,sort_keys=True))

if __name__ == "__main__":
    main()
