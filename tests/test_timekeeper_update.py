#!/usr/bin/env python3
"""Execute composed native HIA and compare every byte with a bigint model."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PIN = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
MAX = (1 << 64) - 1
MAX32 = (1 << 32) - 1


def sha(data):
    return hashlib.sha256(data).hexdigest()


def oracle(req, state, rep_len):
    if rep_len < 24:
        return 1, None, state

    def reject(code):
        return code, struct.pack("<3Q", code, 0, 0), state

    if len(req) != 16:
        return reject(2)
    if len(state) != 64:
        return reject(6)
    expect, now = struct.unpack("<2Q", req)
    previous, fraction, total, generation, mask, limit, mult, shift = struct.unpack("<8Q", state)
    if expect != generation:
        return reject(7)
    if generation == MAX:
        return reject(8)
    modulus = mask + 1
    if (modulus.bit_count() != 1 or not (0 < limit <= mask // 2)
        or max(previous, now) >= modulus or not (0 < mult <= MAX32)
        or shift > 32 or fraction >= (1 << shift)):
        return reject(3)
    delta = (now - previous) % modulus
    if delta > limit:
        return reject(4)
    step, remainder = divmod(delta * mult + fraction, 1 << shift)
    if step > MAX:
        return reject(5)
    if total + step > MAX:
        return reject(9)
    committed = struct.pack("<8Q", now, remainder, total + step, generation + 1, mask, limit, mult, shift)
    return 0, struct.pack("<3Q", 0, total + step, generation + 1), committed


def main(compiler):
    assert sha(compiler.read_bytes()) == PIN, "compiler hash mismatch"
    source = subprocess.check_output([sys.executable, "-I", "-B", ROOT / "tools/compose_timekeeper_update.py"])
    machine = subprocess.check_output([compiler], input=source, env={"PATH": ""})
    assert machine == subprocess.check_output([compiler], input=source, env={"PATH": ""})
    with tempfile.TemporaryDirectory(prefix="timekeeper-update-") as tmpname:
        tmp = Path(tmpname)
        obj, so = tmp / "time.o", tmp / "time.so"
        obj.write_bytes(machine)
        assert not subprocess.check_output(["nm", "-u", obj])
        subprocess.run(["ld", "-shared", "-z", "noexecstack", "-o", so, obj], check=True)
        for binary, output in [(obj, tmp / "obj.text"), (so, tmp / "so.text")]:
            subprocess.run(["objcopy", "--dump-section", f".text={output}", binary], check=True)
        code = (tmp / "obj.text").read_bytes()
        assert code == (tmp / "so.text").read_bytes()
        f = C.CDLL(str(so)).f0
        f.argtypes = [C.c_void_p, C.c_uint64] * 3
        f.restype = C.c_uint32
        counts = [0] * 10

        def check(req, state, n=24):
            q = C.create_string_buffer(b"\x45" * 16 + req + b"\x45" * 16)
            r = C.create_string_buffer(b"\x56" * (n + 32))
            s = C.create_string_buffer(b"\x67" * 16 + state + b"\x67" * 16)
            before_q, before_r, before_s = bytes(q), bytes(r), bytes(s)
            status, reply, expected_state = oracle(req, state, n)
            got = f(C.addressof(q) + 16, len(req), C.addressof(r) + 16, n,
                    C.addressof(s) + 16, len(state))
            expected_reply = before_r if reply is None else before_r[:16] + reply + before_r[40:]
            assert got == status, (got, status, req.hex(), state.hex())
            assert bytes(q) == before_q
            assert bytes(r) == expected_reply, (got, bytes(r).hex(), expected_reply.hex())
            assert bytes(s) == before_s[:16] + expected_state + before_s[16 + len(state):]
            counts[status] += 1
            return status, expected_state

        def pack(*words):
            return struct.pack("<" + "Q" * len(words), *words)

        profile = (255, 127, 17, 6)
        state = pack(254, 7, 123, 91, *profile)
        req = pack(91, 1)
        assert check(req, state)[0] == 0
        for n in range(24):
            assert check(req, state, n)[0] == 1
        for n in list(range(16)) + [17, 23, 64]:
            assert check((req + bytes(64))[:n], state)[0] == 2
        for n in list(range(64)) + [65, 72, 96]:
            assert check(req, (state + bytes(96))[:n])[0] == 6
        assert check(req, pack(254, 64, 123, 91, *profile))[0] == 3
        assert check(pack(91, 200), state)[0] == 4
        assert check(pack(91, MAX // 3 + 1), pack(0, 0, 0, 91, MAX, MAX // 2, 3, 0))[0] == 5
        assert check(pack(90, 1), state)[0] == 7
        assert check(pack(MAX, 1), pack(254, 7, 123, MAX, *profile))[0] == 8
        assert check(pack(91, 254), pack(250, 0, MAX, 91, 255, 127, 1, 0))[0] == 9
        assert check(pack(91, 254), pack(250, 0, MAX - 4, 91, 255, 127, 1, 0))[0] == 0

        rng = random.Random(0xC10C5003)
        for width in range(2, 65):
            mask = (1 << width) - 1
            for shift in range(33):
                limit = mask // 2
                generation = rng.randrange(MAX)
                for d in (0, 1, limit, limit + 1, mask):
                    base = rng.choice((0, 1, limit, mask - 1, mask))
                    total = rng.choice((0, 1234, MAX - 1, MAX))
                    fraction = rng.randrange(1 << shift)
                    mult = rng.choice((1, 17, MAX32))
                    result, _ = check(pack(generation, (base + d) & mask),
                                      pack(base, fraction, total, generation, mask, limit, mult, shift),
                                      rng.choice((24, 25, 48)))
                    assert result in (0, 4, 5, 9)

        # Stateful traces over wrap. Replaying each accepted expected
        # generation must leave the whole new state unchanged.
        for mask, mult, shift in ((255, 17, 6), (65535, MAX32, 32), (MAX, 3, 0)):
            total_base, fraction_base, prior, generation = 5, 0, mask - 3, 40
            state = pack(prior, fraction_base, total_base, generation, mask, mask // 2, mult, shift)
            summed_cycles = 0
            for _ in range(512):
                d = rng.randrange(min(mask // 2, 1000) + 1)
                now = (prior + d) & mask
                req = pack(generation, now)
                status, state = check(req, state)
                assert status == 0
                assert check(req, state) == (7, state)
                summed_cycles += d
                generation += 1
                prior = now
                accum, frac = divmod(summed_cycles * mult + fraction_base, 1 << shift)
                assert struct.unpack("<4Q", state[:32]) == (now, frac, total_base + accum, generation)
        assert all(counts)
        print(json.dumps({"status": "PASS", "native_calls": sum(counts), "status_counts": counts,
            "source_sha256": sha(source), "compiler_sha256": PIN, "object_sha256": sha(machine),
            "text_sha256": sha(code)}, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler", type=Path, required=True)
    main(p.parse_args().compiler.resolve(strict=True))
