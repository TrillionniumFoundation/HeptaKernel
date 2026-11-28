#!/usr/bin/env python3
"""Build the exact native HIA subject and compare it with a bigint oracle."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "clocksource_delta.hepta"
COMPILER = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
MAX64 = (1 << 64) - 1
MAX32 = (1 << 32) - 1


def sha(data):
    return hashlib.sha256(data).hexdigest()


def oracle(raw, size):
    if size < 24:
        return 1, None
    if len(raw) != 56:
        return 2, (2, 0, 0)
    old, now, mask, limit, mult, shift, fraction = struct.unpack("<7Q", raw)
    modulus = mask + 1
    if (modulus.bit_count() != 1 or not (0 < limit <= (modulus - 1) // 2)
        or max(old, now) >= modulus or not (0 < mult <= MAX32)
        or shift > 32 or fraction >= (1 << shift)):
        return 3, (3, 0, 0)
    delta = (now - old) % modulus
    if delta > limit:
        return 4, (4, 0, 0)
    ns, remainder = divmod(delta * mult + fraction, 1 << shift)
    if ns > MAX64:
        return 5, (5, 0, 0)
    return 0, (0, ns, remainder)


def main(compiler):
    source = SOURCE.read_bytes()
    assert sha(compiler.read_bytes()) == COMPILER, "compiler hash mismatch"
    with tempfile.TemporaryDirectory(prefix="clocksource-delta-") as directory:
        tmp = Path(directory)
        obj, so = tmp / "clock.o", tmp / "clock.so"
        machine = subprocess.check_output([str(compiler)], input=source, env={"PATH": ""})
        assert machine == subprocess.check_output([str(compiler)], input=source, env={"PATH": ""})
        obj.write_bytes(machine)
        assert not subprocess.check_output(["nm", "-u", obj])
        subprocess.run(["ld", "-shared", "-z", "noexecstack", "-o", so, obj], check=True)
        for binary, output in [(obj, tmp / "obj.text"), (so, tmp / "so.text")]:
            subprocess.run(["objcopy", "--dump-section", f".text={output}", binary], check=True)
        assert (tmp / "obj.text").read_bytes() == (tmp / "so.text").read_bytes()
        native = C.CDLL(str(so)).f0
        native.argtypes = [C.c_void_p, C.c_uint64] * 3
        native.restype = C.c_uint32
        counts = [0] * 6

        def check(raw, size=24):
            req = C.create_string_buffer(b"\x9c" * 16 + raw + b"\x9c" * 16)
            rep = C.create_string_buffer(b"\x65" * (size + 32))
            state = C.create_string_buffer(b"\xb7" * 33)
            req_before, rep_before, state_before = bytes(req), bytes(rep), bytes(state)
            rv = native(C.addressof(req) + 16, len(raw), C.addressof(rep) + 16, size,
                        C.addressof(state) + 16, 0)
            status, result = oracle(raw, size)
            expected = rep_before if result is None else (
                rep_before[:16] + struct.pack("<3Q", *result) + rep_before[40:])
            assert rv == status and bytes(rep) == expected, (raw.hex(), size, rv, status, result, bytes(rep).hex())
            assert bytes(req) == req_before and bytes(state) == state_before
            counts[status] += 1
            return result

        def probe(old, now, mask, limit, mult, shift, fraction, size=24):
            return check(struct.pack("<7Q", old, now, mask, limit, mult, shift, fraction), size)

        # Every mask width and shift. Exercise zero, endpoint, midpoint,
        # reversals and values immediately across the wrap/limit boundaries.
        for width in range(2, 65):
            mask = (1 << width) - 1
            limit = mask // 2
            for shift in range(33):
                base = 1 << shift
                for old in (0, mask, mask // 2):
                    for delta in (0, 1, limit, limit + 1, mask):
                        for mult in (1, 3, MAX32):
                            probe(old, (old + delta) & mask, mask, limit, mult, shift, base - 1)

        # Eliminate false rejections when the unshifted product exceeds 64
        # bits. Pin the largest legal output and first overflowing output.
        d = (1 << 63) - 1
        assert probe(0, d, MAX64, d, 4, 1, 0) == (0, MAX64 - 1, 0)
        assert probe(0, d, MAX64, d, 4, 1, 1) == (0, MAX64 - 1, 1)
        assert probe(0, d, MAX64, d, 2, 0, 0) == (0, MAX64 - 1, 0)
        assert probe(0, MAX64 // 3, MAX64, d, 3, 0, 0) == (0, MAX64, 0)
        assert probe(0, MAX64 // 3 + 1, MAX64, d, 3, 0, 0) == (5, 0, 0)

        raw = struct.pack("<7Q", 255, 1, 255, 127, 3, 2, 1)
        for n in list(range(56)) + [57, 63, 64, 128]:
            check((raw + b"\x42" * 128)[:n])
        for n in list(range(24)) + [24, 25, 31, 48]:
            check(raw, n)
            check(b"", n)
        for vals in [(0, 0, 0, 1, 1, 0, 0), (0, 0, 1, 1, 1, 0, 0),
                     (0, 0, 0b10111, 7, 1, 0, 0), (16, 0, 15, 7, 1, 0, 0),
                     (0, 16, 15, 7, 1, 0, 0), (0, 0, 15, 8, 1, 0, 0),
                     (0, 0, 15, 0, 1, 0, 0), (0, 0, 15, 7, 0, 0, 0),
                     (0, 0, 15, 7, MAX32 + 1, 0, 0), (0, 0, 15, 7, 1, 33, 0),
                     (0, 0, 15, 7, 1, MAX64, 0), (0, 0, 15, 7, 1, 0, 1),
                     (0, 0, 15, 7, 1, 32, 1 << 32)]:
            assert probe(*vals) == (3, 0, 0)

        rng = random.Random(0xC10C5002)
        for _ in range(6000):
            width = rng.randrange(2, 65)
            mask = (1 << width) - 1
            limit = rng.randrange(1, mask // 2 + 1)
            old, new = rng.getrandbits(width), rng.getrandbits(width)
            shift = rng.randrange(33)
            probe(old, new, mask, limit, rng.randrange(1, MAX32 + 1), shift,
                  rng.getrandbits(shift))
        # Many real calls chained using the exact returned fraction. Verify
        # total against a one-shot bigint calculation across several wraps.
        for width, shift, mult in ((8, 6, 19), (16, 32, MAX32), (32, 0, 25), (64, 31, 314159265)):
            mask = (1 << width) - 1
            old = mask - 3
            ns = fraction = total = 0
            for _ in range(250):
                delta = rng.randrange(1, (mask // 2) + 1)
                if width == 64:
                    delta %= 1 << 36
                new = (old + delta) & mask
                status, step_ns, fraction = probe(old, new, mask, mask // 2, mult, shift, fraction)
                assert status == 0
                old = new
                total += delta
                ns += step_ns
                assert (ns, fraction) == divmod(total * mult, 1 << shift)
        assert all(counts)
        print(json.dumps({"status": "PASS", "native_calls": sum(counts),
            "status_counts": counts, "source_sha256": sha(source), "compiler_sha256": COMPILER,
            "object_sha256": sha(machine), "text_sha256": sha((tmp / "obj.text").read_bytes())},
            sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler", type=Path, required=True)
    main(p.parse_args().compiler.resolve(strict=True))
