#!/usr/bin/env python3
"""Independent byte-level oracle for one HIA dual-zone page claim.

The two HIA PMM-compatible states are 65 bytes each: 64-byte header and
one bitmap byte for exactly eight pages. No Python parser/executor or host
allocator is used to implement the claimed native operation.
"""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import random
import struct

from test_arena_router import object_text

MAGIC = 3552580688320940353
LIMIT = 1 << 52
PAGE = 4096
ZONE_BYTES = 65


def zone(base, reserved, used, *, free_override=None):
    assert 0 <= reserved <= 8 and 0 <= used <= 255
    bitmap = used | ((1 << reserved) - 1)
    free = 8 - bitmap.bit_count() if free_override is None else free_override
    return (struct.pack("<5Q", MAGIC, 8, base, reserved, free)
            + bytes(24) + bytes((bitmap,)))


def pair(bitmap0=0, bitmap1=0, reserved0=0, reserved1=0,
         base0=0x400000, base1=0x600000):
    return (zone(base0, reserved0, bitmap0)
            + zone(base1, reserved1, bitmap1))


def model(request, reply_len, state):
    if reply_len < 16:
        return 1, None, state
    if len(request) not in (0, 8):
        return 2, 0, state
    if len(state) != 2 * ZONE_BYTES:
        return 4, 0, state
    parsed = []
    for off in (0, ZONE_BYTES):
        magic, pages, base, reserved, free = struct.unpack_from("<5Q", state, off)
        bits = state[off + 64]
        if not (magic == MAGIC and pages == 8 and reserved <= 8
                and free <= 8 and base < LIMIT and base % PAGE == 0
                and 8 * PAGE <= LIMIT - base
                and state[off+40:off+64] == bytes(24)
                and bits & ((1 << reserved)-1) == (1 << reserved)-1
                and free == 8 - bits.bit_count()):
            return 4, 0, state
        parsed.append((off, base, bits, reserved))
    (_, b0, _, _), (_, b1, _, _) = parsed
    if b0 < b1 + 8*PAGE and b1 < b0 + 8*PAGE:
        return 4, 0, state
    if request:
        address, = struct.unpack("<Q", request)
        if address % PAGE:
            return 6, 0, state
        for off, base, bits, reserved in parsed:
            if base <= address < base + 8*PAGE:
                index = (address - base) // PAGE
                if index < reserved or not (bits & (1 << index)):
                    return 6, 0, state
                new = bytearray(state)
                new[off+64] &= ~(1 << index)
                free, = struct.unpack_from("<Q", state, off+32)
                struct.pack_into("<Q", new, off+32, free+1)
                return 0, address, bytes(new)
        return 6, 0, state
    for off, base, bits, reserved in parsed:
        for i in range(8):
            if not bits & (1 << i):
                new = bytearray(state)
                new[off+64] |= 1 << i
                free, = struct.unpack_from("<Q", state, off+32)
                struct.pack_into("<Q", new, off+32, free-1)
                return 0, base+i*PAGE, bytes(new)
    return 5, 0, state


def native(path, cases):
    fn = ctypes.CDLL(str(path.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    for n, (request, rlen, state) in enumerate(cases):
        src = ctypes.create_string_buffer(b"\xa9"*32 + request + b"\xa9"*32)
        reply = ctypes.create_string_buffer(b"\xb7"*(32+rlen+32))
        memory = ctypes.create_string_buffer(b"\xc3"*32 + state + b"\xc3"*32)
        src_before = bytes(src)
        status = fn(ctypes.addressof(src)+32, len(request),
                    ctypes.addressof(reply)+32, rlen,
                    ctypes.addressof(memory)+32, len(state))
        expected, value, next_state = model(request, rlen, state)
        assert status == expected, (n, status, expected, state.hex())
        assert bytes(src) == src_before, n
        raw_reply = bytes(reply)
        assert raw_reply[:32] == b"\xb7"*32, n
        assert raw_reply[32+rlen:32+rlen+32] == b"\xb7"*32, n
        assert raw_reply[32+16:32+rlen] == b"\xb7"*max(0,rlen-16), n
        if value is None:
            assert raw_reply[32:32+rlen] == b"\xb7"*rlen, n
        else:
            assert struct.unpack_from("<2Q", raw_reply, 32) == (status, value), n
        raw_state = bytes(memory)
        assert raw_state[:32] == b"\xc3"*32, n
        assert raw_state[32+len(state):32+len(state)+32] == b"\xc3"*32, n
        assert raw_state[32:32+len(state)] == next_state, (n, status)
    return len(cases)


def cases():
    tests = []
    valid = pair()
    for length in (0, 1, 15, 16, 17, 32):
        tests.append((b"", length, valid))
    tests += [
        (b"\0", 16, valid),
        (b"bad", 16, valid),
        (b"", 16, valid[:-1]),
        (b"", 16, valid+b"\0"),
        (b"", 16, b""),
        (b"", 16, pair(255, 255)),
        (b"", 16, pair(255, 0)),
        (b"", 16, pair(255, 0, reserved0=8, reserved1=0)),
        (b"", 16, pair(0, 0, reserved0=8, reserved1=8)),
        (b"", 16, pair(0, 0, base0=0x400000, base1=0x401000)),
        (b"", 16, pair(0, 0, base0=LIMIT-32768, base1=0)),
        (b"", 16, pair(0, 0, base0=LIMIT-28672)),
    ]
    rng = random.Random(0x202611220923)
    for _ in range(1600):
        r0, r1 = rng.randrange(9), rng.randrange(9)
        b0, b1 = rng.randrange(256), rng.randrange(256)
        base0, base1 = rng.choice([
            (0, 32768), (0x400000, 0x600000),
            (0x600000, 0x400000), (LIMIT-32768, 0),
        ])
        state = pair(b0,b1,r0,r1,base0,base1)
        tests.append((b"", rng.choice([16,16,16,17,32]), state))
        if rng.randrange(3) == 0:
            bad = bytearray(state)
            # Violate exactly one of the checked provenance/state invariants.
            at = rng.choice([0,8,16,24,32,40,64,65,73,81,89,97,105,129])
            bad[at] ^= (1 << rng.randrange(8))
            tests.append((b"",16,bytes(bad)))
    # Repeated claims must consume the first zone before the second.
    evolving = pair()
    for _ in range(18):
        tests.append((b"",16,evolving))
        _, _, evolving = model(b"",16,evolving)

    # Release a genuinely claimed page; then reject its double free.
    for selected in (0x400000, 0x401000, 0x600000, 0x601000):
        p = pair(0b00000011, 0b00000011, reserved0=1, reserved1=1)
        req = struct.pack("<Q", selected)
        tests.append((req, 16, p))
        status, _, after = model(req, 16, p)
        if status == 0:
            tests.append((req, 16, after))
            tests.append((b"", 16, after))
    # Both valid reserved prefixes and an exhausted zone must refuse frees.
    tests.extend([
        (struct.pack("<Q",0x400000),16,pair(255,255,reserved0=1,reserved1=1)),
        (struct.pack("<Q",0x600000),16,pair(255,255,reserved0=1,reserved1=1)),
        (struct.pack("<Q",0x400001),16,pair(3,3)),
        (struct.pack("<Q",0x408000),16,pair(3,3)),
        (struct.pack("<Q",0x5ff000),16,pair(3,3)),
        (struct.pack("<Q",0xfffffffffffff000),16,pair(3,3)),
        (struct.pack("<Q",0x400000),1,pair(3,3)),
        (struct.pack("<Q",0x401000),16,pair(3,3)[:-1]),
        (struct.pack("<Q",0x401000),16,pair(3,3,base0=0x400000,base1=0x401000)),
    ])
    # Seeded releases vary the zone, selected bit, reserved prefixes,
    # physical interval order and all byte-level guard conditions.
    for _ in range(640):
        reserved0, reserved1 = rng.randrange(9), rng.randrange(9)
        bitmap0, bitmap1 = rng.randrange(256), rng.randrange(256)
        bases = rng.choice([(0x400000,0x600000),
                            (0x600000,0x400000),
                            (LIMIT-32768,0x400000)])
        p = pair(bitmap0,bitmap1,reserved0,reserved1,*bases)
        base = rng.choice(bases)
        candidate = base + rng.randrange(8)*PAGE
        if rng.randrange(5) == 0:
            candidate += rng.choice([1,4095])
        elif rng.randrange(9) == 0:
            candidate = rng.choice([0x12345000, LIMIT, LIMIT-1])
        request = struct.pack("<Q",candidate)
        tests.append((request,rng.choice([16,16,17,32]),p))
    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("library", type=Path)
    ap.add_argument("--object", type=Path)
    ap.add_argument("--dishonest", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("build/pmm-dual-claim-report.json"))
    args = ap.parse_args()
    if args.dishonest:
        corrupt = bytearray(pair())
        corrupt[40] = 1
        want, _, _ = model(b"",16,bytes(corrupt))
        assert want == 4
        fn = ctypes.CDLL(str(args.library.resolve())).f0
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64]*3
        fn.restype = ctypes.c_uint32
        req = ctypes.create_string_buffer(b"\0")
        reply = ctypes.create_string_buffer(16)
        state = ctypes.create_string_buffer(bytes(corrupt))
        observed = fn(req,0,reply,16,state,len(corrupt))
        assert observed != want, (observed,want)
        print(json.dumps({"status":"DETECTED","dishonest_native_hia":observed,"oracle":want}))
        return
    assert args.object is not None
    assert object_text(args.object) == object_text(args.library)
    record = {
        "schema":"heptakernel.pmm-dual-claim-native.v1",
        "scope":"single-owner sequential one-call first-free page claim from two bounded PMM-compatible eight-page zones; not atomic, SMP or Linux allocator",
        "source_sha256":hashlib.sha256(Path("src/pmm_dual_claim.hepta").read_bytes()).hexdigest(),
        "object_sha256":hashlib.sha256(args.object.read_bytes()).hexdigest(),
        "library_sha256":hashlib.sha256(args.library.read_bytes()).hexdigest(),
        "object_text_matches_library":True,
        "qemu_tested":False,
    }
    try:
        record["cases"] = native(args.library, cases())
        record["status"] = "PASS"
    except BaseException as exc:
        record["status"],record["error"] = "FAIL",repr(exc)
        raise
    finally:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n")
        print(json.dumps(record,sort_keys=True))


if __name__ == "__main__":
    main()
