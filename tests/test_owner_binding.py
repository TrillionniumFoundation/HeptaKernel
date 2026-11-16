#!/usr/bin/env python3
"""Independent ABI tests for genuine HIA arena/PMM header binding.

The existing native HIA PMM performs INIT. A separately compiled HIA
binding checker must accept that exact descriptor and reject mismatched,
noncanonical or truncated headers, without mutating the PMM state.
This tests header binding only, NOT entire PMM bitmap or SMP ownership.
"""
from __future__ import annotations

import argparse
import ctypes
import struct
from pathlib import Path

LIMIT = 1 << 52
PAGE = 4096
MAGIC = 0x314D4D504B484941
OK, SHORT_REPLY, BAD_REQUEST, BAD_OP, BAD_STATE = range(5)
INVALID = 6


def entry(path: Path):
    fn = ctypes.CDLL(str(path.resolve())).f0
    fn.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    fn.restype = ctypes.c_uint32
    return fn


def call(fn, request: bytes, state, *, reply_len: int = 16, state_immutable: bool = True):
    reply = (ctypes.c_ubyte * (reply_len + 64))()
    ctypes.memset(ctypes.addressof(reply), 0xC7, len(reply))
    snapshot = bytes(state)
    request_storage = (ctypes.c_ubyte * (len(request) + 64))()
    ctypes.memset(ctypes.addressof(request_storage), 0xB6, len(request_storage))
    if request:
        ctypes.memmove(ctypes.addressof(request_storage) + 32, request, len(request))
    request_before = bytes(request_storage)
    result = fn(ctypes.addressof(request_storage) + 32, len(request),
                ctypes.addressof(reply) + 32, reply_len,
                ctypes.addressof(state), len(state))
    assert bytes(request_storage) == request_before, "request modified"
    if state_immutable:
        assert bytes(state) == snapshot, "owner binding mutated PMM state"
    raw = bytes(reply)
    assert raw[:32] == bytes([0xC7]) * 32
    assert raw[32 + reply_len:] == bytes([0xC7]) * 32
    if reply_len < 16:
        assert raw == bytes([0xC7]) * len(reply)
        return result, None
    status, value = struct.unpack_from("<QQ", raw, 32)
    assert status == result, "return code differs from reply status"
    assert raw[48:32 + reply_len] == bytes([0xC7]) * (reply_len - 16)
    return status, value


def build_state(pmm_fn, pages: int, base: int, reserved: int):
    capacity = 64 + (pages + 7) // 8
    state = (ctypes.c_ubyte * capacity)()
    request = struct.pack("<QQQQ", 0, pages, base, reserved)
    result = call(pmm_fn, request, state, state_immutable=False)
    assert result == (OK, pages - reserved), ("HIA INIT failed", result)
    return state


def overwrite(state, offset, data):
    assert offset + len(data) <= len(state)
    ctypes.memmove(ctypes.addressof(state) + offset, data, len(data))


def tests(binding_fn, pmm_fn):
    cases = 0
    for pages, base, reserved in (
        (1, 0, 0), (1, PAGE, 1), (7, 0x400000, 3),
        (8, 0x600000, 2), (9, 0x800000, 0),
        (65536, LIMIT - 65536 * PAGE, 1),
    ):
        state = build_state(pmm_fn, pages, base, reserved)
        request = struct.pack("<QQQ", base, pages, reserved)
        actual = call(binding_fn, request, state)
        assert actual == (OK, pages - reserved), (pages, actual)
        cases += 1
        # Every identity field is indispensable. The second zone may not
        # silently reuse the first zone's PMM state pointer.
        for other in (
            (base + PAGE, pages, reserved),
            (base, pages + 1, reserved),
            (base, pages, reserved + 1),
        ):
            if other == (base, pages, reserved):
                continue
            reply = call(binding_fn, struct.pack("<QQQ", *other), state)
            assert reply[0] in (BAD_STATE, INVALID), (other, reply)
            cases += 1
        assert call(binding_fn, request, state, reply_len=0) == (SHORT_REPLY, None)
        assert call(binding_fn, request, state, reply_len=15) == (SHORT_REPLY, None)
        cases += 2
        for bad in (b"", request + b"\0", request[:-1]):
            assert call(binding_fn, bad, state)[0] == BAD_REQUEST
            cases += 1
        for offset in (0, 8, 16, 24, 32):
            before = bytes(state)
            overwrite(state, offset, b"\xff" * 8)
            assert call(binding_fn, request, state)[0] == BAD_STATE, offset
            overwrite(state, 0, before)
            cases += 1
        for offset in range(40, 64):
            for byte in (1, 0x80, 0xFF):
                before = bytes(state)
                overwrite(state, offset, bytes([byte]))
                assert call(binding_fn, request, state)[0] == BAD_STATE, offset
                overwrite(state, 0, before)
                cases += 1
        for cut in (0, 7, 39, 63, capacity - 1):
            short_state = (ctypes.c_ubyte * cut).from_buffer_copy(bytes(state)[:cut])
            assert call(binding_fn, request, short_state)[0] == BAD_STATE
            cases += 1
    # A matching header can still have a corrupted allocation bitmap.
    # This limited guard is not the PMM's state_valid() and MUST NOT be
    # used as an independent authorization to allocate or free pages.
    state = build_state(pmm_fn, 9, 0x400000, 1)
    request = struct.pack("<QQQ", 0x400000, 9, 1)
    for invalid in (
        (0x400000, 0, 0), (0x400000, 65537, 0),
        (0x400001, 9, 1), (0x400000, 9, 10),
        (LIMIT - PAGE, 2, 0),
    ):
        assert call(binding_fn, struct.pack("<QQQ", *invalid), state)[0] == INVALID
        cases += 1
    assert call(binding_fn, request, state) == (OK, 8)
    cases += 1
    print(f"native HIA owner/header binding: {cases} independent cases PASS")
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("owner_library", type=Path)
    parser.add_argument("pmm_library", type=Path)
    parser.add_argument("--expect-unsafe", action="store_true")
    args = parser.parse_args()
    binding_fn, pmm_fn = entry(args.owner_library), entry(args.pmm_library)
    if args.expect_unsafe:
        try:
            tests(binding_fn, pmm_fn)
        except AssertionError as exc:
            print(f"dishonest HIA owner binding REJECTED: {exc}")
            return
        raise SystemExit("unsafe binding escaped the independent oracle")
    tests(binding_fn, pmm_fn)


if __name__ == "__main__":
    main()
