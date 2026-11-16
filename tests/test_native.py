#!/usr/bin/env python3
"""Independent finite tests of the actual HIA object through its public ABI.

The reference model uses sets of physical addresses, not the implementation's
bitmap. This is a component test, not Linux syscall or hardware qualification.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import random
import struct
from pathlib import Path

PAGE = 4096
LIMIT = 1 << 52
MASK = (1 << 64) - 1
MAGIC = 0x314D4D504B484941
OK, SHORT_REPLY, BAD_REQUEST, BAD_OP, BAD_STATE = range(5)
NO_MEMORY, INVALID, DOUBLE_FREE, RESERVED = range(5, 9)


class Native:
    def __init__(self, library: Path, capacity: int = 8256):
        self.library = ctypes.CDLL(str(library.resolve()))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint32
        self.capacity = capacity
        # Independent guard regions surround all three external capabilities.
        self.state_storage = (ctypes.c_ubyte * (capacity + 64))()
        ctypes.memset(ctypes.addressof(self.state_storage), 0xA5, capacity + 64)
        self.state_ptr = ctypes.addressof(self.state_storage) + 32
        ctypes.memset(self.state_ptr, 0, capacity)

    def snapshot(self):
        return ctypes.string_at(self.state_ptr, self.capacity)

    def guards(self):
        s = bytes(self.state_storage)
        assert s[:32] == b"\xa5" * 32 and s[-32:] == b"\xa5" * 32

    def call(self, command, *, raw=None, reply_len=16):
        request = struct.pack("<4Q", *command) if raw is None else raw
        request_guarded = ctypes.create_string_buffer(b"\xb6" * 32 + request + b"\xb6" * 32)
        reply_guarded = ctypes.create_string_buffer(b"\xc7" * (reply_len + 64))
        before_request = bytes(request_guarded)
        returned = self.entry(ctypes.addressof(request_guarded) + 32, len(request),
                              ctypes.addressof(reply_guarded) + 32, reply_len,
                              self.state_ptr, self.capacity)
        assert bytes(request_guarded) == before_request, "request capability was modified"
        reply = bytes(reply_guarded)
        assert reply[:32] == b"\xc7" * 32 and reply[32 + reply_len:32 + reply_len + 32] == b"\xc7" * 32
        self.guards()
        if reply_len < 16:
            assert returned == SHORT_REPLY and reply == b"\xc7" * (reply_len + 64) + b"\0"
            return returned, 0
        status, value = struct.unpack("<2Q", reply[32:48])
        assert returned == status, ("return/status disagreement", returned, status)
        assert reply[48:32 + reply_len] == b"\xc7" * (reply_len - 16)
        return status, value


class Model:
    def __init__(self, capacity=8256):
        self.capacity = capacity
        self.initialized = False
        self.free = set()

    def call(self, c):
        op, a, b, d = c
        if op not in range(9):
            return BAD_OP, 0
        if op == 0:
            if not 1 <= a <= 65536 or b % PAGE or b >= LIMIT or a > (LIMIT - b) // PAGE or d > a:
                return INVALID, 0
            if self.capacity < 64 + (a + 7) // 8:
                return BAD_STATE, 0
            self.n, self.base, self.reserved = a, b, d
            self.free = {b + i * PAGE for i in range(d, a)}
            self.initialized = True
            return OK, len(self.free)
        # Parameter-only failures precede inspection of mutable allocator state.
        if ((op == 1 and (a == 0 or a & (a - 1) or b or d))
                or (op == 2 and (a % PAGE or b or d))
                or (op == 3 and (a or b or d))
                or (op in (4, 8) and (a == 0 or b == 0 or (b & (b - 1)) or d))
                or (op == 5 and (a % PAGE or b == 0 or d))
                or (op == 6 and (a % PAGE or b == 0 or d))
                or (op == 7 and (a % PAGE or b == 0 or d))):
            return INVALID, 0
        if not self.initialized:
            return BAD_STATE, 0
        if op == 1:
            if a == 0 or a & (a - 1) or b or d:
                return INVALID, 0
            aligned = [p for p in self.free if (p // PAGE) % a == 0]
            if not aligned:
                return NO_MEMORY, 0
            p = min(aligned)
            self.free.remove(p)
            return OK, p
        if op == 2:
            if b or d or a % PAGE or not self.base <= a < self.base + self.n * PAGE:
                return INVALID, 0
            if a < self.base + self.reserved * PAGE:
                return RESERVED, 0
            if a in self.free:
                return DOUBLE_FREE, 0
            self.free.add(a)
            return OK, 0
        if op in (4, 8):
            if a > len(self.free):
                return NO_MEMORY, 0
            for index in range(self.reserved, self.n - a + 1):
                physical = self.base + index * PAGE
                run = {physical + offset * PAGE for offset in range(a)}
                if (physical // PAGE) % b == 0 and run.issubset(self.free):
                    if op == 4:
                        self.free.difference_update(run)
                    return OK, physical
            return NO_MEMORY, 0
        if op == 5:
            if not self.base <= a < self.base + self.n * PAGE:
                return INVALID, 0
            index = (a - self.base) // PAGE
            if b > self.n - index:
                return INVALID, 0
            if index < self.reserved:
                return RESERVED, 0
            run = {a + offset * PAGE for offset in range(b)}
            if run & self.free:
                return DOUBLE_FREE, 0
            self.free.update(run)
            return OK, 0
        if op == 6:
            if not self.base <= a < self.base + self.n * PAGE:
                return INVALID, 0
            index = (a - self.base) // PAGE
            if b > self.n - index:
                return INVALID, 0
            if index < self.reserved:
                return RESERVED, 0
            run = {a + offset * PAGE for offset in range(b)}
            if not run.issubset(self.free):
                return NO_MEMORY, 0
            self.free.difference_update(run)
            return OK, 0
        if op == 7:
            if not self.base <= a < self.base + self.n * PAGE:
                return INVALID, 0
            index = (a - self.base) // PAGE
            if b > self.n - index:
                return INVALID, 0
            if index < self.reserved:
                return RESERVED, 0
            requested = {a + offset * PAGE for offset in range(b)}
            return (OK, b) if requested.issubset(self.free) else (NO_MEMORY, 0)
        if a or b or d:
            return INVALID, 0
        return OK, len(self.free)


class Campaign:
    def __init__(self, library):
        self.library, self.commands, self.cases = library, 0, []

    def pair(self, capacity=8256):
        return Native(self.library, capacity), Model(capacity)

    def check_state(self, native, model):
        if not model.initialized:
            return
        raw = native.snapshot()
        assert struct.unpack_from("<5Q", raw) == (MAGIC, model.n, model.base, model.reserved, len(model.free))
        assert raw[40:64] == bytes(24), "spare header bytes changed"
        for i in range(model.n):
            actual_used = bool(raw[64 + i // 8] & (1 << (i % 8)))
            expected_used = i < model.reserved or model.base + i * PAGE not in model.free
            assert actual_used == expected_used, ("bitmap disagrees with set oracle", i)
        if model.n % 8:
            assert raw[64 + model.n // 8] >> (model.n % 8) == 0, "tail bits changed"

    def call(self, pair, command):
        native, model = pair
        before = native.snapshot()
        expected = model.call(command)
        actual = native.call(command)
        self.commands += 1
        assert actual == expected, {"command": command, "actual": actual, "expected": expected}
        if actual[0] != OK:
            assert native.snapshot() == before, ("failure mutated allocator state", command)
        elif command[0] in (3, 7, 8):
            assert native.snapshot() == before, "read-only query mutated state"
        if model.initialized:
            end = 64 + (model.n + 7) // 8
            assert native.snapshot()[end:] == before[end:], "unrelated state capacity modified"
        self.check_state(native, model)
        return actual

    def boundaries(self):
        for n in (1, 2, 7, 8, 9, 15, 17, 63, 64, 65, 129):
            for reserved in sorted({0, n // 3, n}):
                pair = self.pair(64 + (n + 7) // 8)
                self.call(pair, (0, n, 0x503000, reserved))
                allocated = []
                for _ in range(n - reserved):
                    allocated.append(self.call(pair, (1, 1, 0, 0))[1])
                self.call(pair, (1, 1, 0, 0))
                self.call(pair, (3, 0, 0, 0))
                for p in allocated[::2]:
                    self.call(pair, (2, p, 0, 0))
                    self.call(pair, (2, p, 0, 0))
                for _ in allocated[::2]:
                    self.call(pair, (1, 1, 0, 0))
                if reserved:
                    self.call(pair, (2, 0x503000, 0, 0))
        self.cases.append("exact-capacity, non-byte-aligned tails, reserved prefixes, exhaustion, reuse, double-free")

    def alignment(self):
        for alignment in (1, 1 << 63):
            zero_pair = self.pair()
            self.call(zero_pair, (0, 1, 0, 0))
            assert self.call(zero_pair, (1, alignment, 0, 0)) == (OK, 0)
            assert self.call(zero_pair, (1, 1, 0, 0)) == (NO_MEMORY, 0)
            self.call(zero_pair, (2, 0, 0, 0))
            self.call(zero_pair, (3, 0, 0, 0))
        for base in (0, 0x1000, 0x503000, LIMIT - 129 * PAGE):
            pair = self.pair()
            self.call(pair, (0, 129, base, 3))
            for alignment in (1, 2, 4, 8, 16, 32, 64, 128, 256, 65536, 1 << 63):
                self.call(pair, (1, alignment, 0, 0))
            for p in (base, base + 128 * PAGE, base + 129 * PAGE, MASK, base + 1):
                self.call(pair, (2, p, 0, 0))
        self.cases.append("physical alignment, zero base, 52-bit upper boundary, unsigned 64-bit arguments")

    def invalid(self):
        pair = self.pair()
        self.call(pair, (1, 1, 0, 0))
        self.call(pair, (3, 0, 0, 0))
        self.call(pair, (99, 0, 0, 0))
        for malformed in ((1, 0, 0, 0), (1, 3, 0, 0), (2, 1, 0, 0), (3, 1, 0, 0)):
            self.call(pair, malformed)
        self.call(pair, (0, 17, 0x400000, 2))
        bad = [(0, 0, 0, 0), (0, 65537, 0, 0), (0, 17, 3, 0), (0, 17, LIMIT, 0),
               (0, 2, LIMIT - PAGE, 0), (0, 17, 0, 18), (0, MASK, 0, 0),
               (1, 0, 0, 0), (1, 3, 0, 0), (1, 1, 1, 0), (1, 1, 0, 1),
               (2, 0x402001, 0, 0), (2, 0x402000, 1, 0), (2, 0x402000, 0, 1),
               (3, 1, 0, 0), (3, 0, 1, 0), (3, 0, 0, 1), (MASK, 0, 0, 0)]
        for c in bad:
            self.call(pair, c)
        for cap in (0, 1, 8, 32, 63, 64, 65):
            small = self.pair(cap)
            self.call(small, (0, 17, 0x400000, 0))
            self.call(small, (3, 0, 0, 0))
        native = pair[0]
        for size in (0, 1, 7, 15, 31, 33, 64):
            before = native.snapshot()
            assert native.call((0, 0, 0, 0), raw=b"\x00" * size) == (BAD_REQUEST, 0)
            assert native.snapshot() == before
            self.commands += 1
        for size in (0, 1, 8, 15):
            before = native.snapshot()
            assert native.call((0, 17, 0x400000, 0), reply_len=size) == (SHORT_REPLY, 0)
            assert native.snapshot() == before
            self.commands += 1
        assert native.call((3, 0, 0, 0), reply_len=64)[0] == OK
        self.commands += 1
        self.cases.append("malformed requests, short capabilities, unused arguments, guard bytes, mutation-free errors")

    def header_corruption(self):
        for offset, value in ((0, 0), (8, 0), (8, 65537), (16, 3), (16, LIMIT),
                              (24, 18), (32, 16), (32, MASK)):
            native, model = self.pair()
            assert native.call((0, 17, 0x400000, 2)) == (OK, 15)
            ctypes.memmove(native.state_ptr + offset, struct.pack("<Q", value), 8)
            before = native.snapshot()
            assert native.call((3, 0, 0, 0)) == (BAD_STATE, 0), (offset, value)
            assert native.snapshot() == before
            self.commands += 2
        # The bytes 40..63 are ABI-reserved. Merely checking canonical
        # initialization is insufficient: forged nonzero bytes must reject
        # *all* live paths before any state changes. Mutate each byte and
        # include a high-bit value to catch signedness and short scans.
        for offset in range(40, 64):
            for octet in (1, 0x80, 0xFF):
                native, _ = self.pair()
                assert native.call((0, 17, 0x400000, 2)) == (OK, 15)
                ctypes.memmove(native.state_ptr + offset, bytes([octet]), 1)
                before = native.snapshot()
                for command in ((3, 0, 0, 0), (8, 1, 1, 0),
                                (6, 0x402000, 1, 0), (1, 1, 0, 0)):
                    assert native.call(command) == (BAD_STATE, 0), (offset, octet, command)
                    assert native.snapshot() == before, ("noncanonical header mutated", offset, command)
                    self.commands += 1
        self.cases.append("header invariants: all 24 reserved bytes reject corruption across query and mutation paths; failures preserve bytes")

    def bitmap_corruption(self):
        # Check the HIA validation path itself, not the Python set model:
        # a forged free-count, released reserved bit or nonzero tail padding
        # must be rejected before any allocator operation changes state.
        for flips in ((0,), (1,), (2,), (3,), (0, 3)):
            native, _ = self.pair()
            assert native.call((0, 17, 0x400000, 2)) == (OK, 15)
            assert native.call((1, 1, 0, 0)) == (OK, 0x402000)
            for index in flips:
                address = native.state_ptr + 64 + index // 8
                old = ctypes.string_at(address, 1)[0]
                ctypes.memmove(address, bytes((old ^ (1 << (index % 8)),)), 1)
            corrupted = native.snapshot()
            for command in ((3, 0, 0, 0), (1, 1, 0, 0),
                            (2, 0x402000, 0, 0)):
                assert native.call(command) == (BAD_STATE, 0), (flips, command)
                assert native.snapshot() == corrupted, (flips, "mutation on invalid bitmap")
                self.commands += 1
        for index in (17, 18, 23):
            native, _ = self.pair()
            assert native.call((0, 17, 0x400000, 2)) == (OK, 15)
            address = native.state_ptr + 64 + index // 8
            old = ctypes.string_at(address, 1)[0]
            ctypes.memmove(address, bytes((old | (1 << (index % 8)),)), 1)
            before = native.snapshot()
            assert native.call((3, 0, 0, 0)) == (BAD_STATE, 0), index
            assert native.snapshot() == before
            self.commands += 1
        for count in (0, 14):
            native, _ = self.pair()
            assert native.call((0, 17, 0x400000, 2)) == (OK, 15)
            ctypes.memmove(native.state_ptr + 32, struct.pack("<Q", count), 8)
            before = native.snapshot()
            assert native.call((3, 0, 0, 0)) == (BAD_STATE, 0), count
            assert native.snapshot() == before
            self.commands += 1
        self.cases.append("HIA bitmap integrity: reserved bits, exact free counter, unused tail bits; errors preserve bytes")

    def contiguous_runs(self):
        # A separate set oracle establishes first-fit, physical alignment,
        # all-or-nothing failure and coexistence with single-page FREE/ALLOC.
        pair = self.pair(67)
        self.call(pair, (4, 1, 1, 0))  # valid arguments but uninitialized
        self.call(pair, (4, 0, 1, 0))  # invalid before state inspection
        self.call(pair, (0, 17, 0x503000, 3))
        for request in ((4, 0, 1, 0), (4, 1, 0, 0),
                        (4, 1, 3, 0), (4, 1, 1, 1)):
            self.call(pair, request)
        assert self.call(pair, (4, 4, 8, 0)) == (OK, 0x508000)
        assert self.call(pair, (4, 6, 1, 0)) == (OK, 0x50C000)
        assert self.call(pair, (4, 4, 1, 0)) == (NO_MEMORY, 0)
        assert self.call(pair, (4, 65536, 1, 0)) == (NO_MEMORY, 0)
        self.call(pair, (2, 0x508000, 0, 0))
        assert self.call(pair, (4, 2, 1, 0)) == (OK, 0x506000)
        self.call(pair, (2, 0x509000, 0, 0))
        self.call(pair, (2, 0x50A000, 0, 0))
        assert self.call(pair, (4, 3, 2, 0)) == (OK, 0x508000)
        assert self.call(pair, (4, 4, 1, 0)) == (NO_MEMORY, 0)
        self.call(pair, (3, 0, 0, 0))
        for base, alignment in ((0, 1), (0x1000, 1 << 63),
                                (LIMIT - 7 * PAGE, 2)):
            p = self.pair(65)
            self.call(p, (0, 7, base, 0))
            self.call(p, (4, 1, alignment, 0))
            self.call(p, (4, 7, 1, 0))
            self.call(p, (3, 0, 0, 0))
        p = self.pair(8256)
        self.call(p, (0, 65536, 0x400000, 65535))
        assert self.call(p, (4, 1, 1, 0)) == (OK, 0x400000 + 65535 * PAGE)
        assert self.call(p, (4, 2, 1, 0)) == (NO_MEMORY, 0)
        self.cases.append("contiguous run allocation: independently modelled first-fit, alignment, fragmentation, no partial claim, zero physical address and maximal state")

    def free_runs(self):
        pair = self.pair(67)
        self.call(pair, (5, 0, 1, 0))  # valid syntax but state not initialized
        self.call(pair, (5, 0, 0, 0))  # invalid count takes precedence
        self.call(pair, (0, 17, 0x503000, 2))
        assert self.call(pair, (4, 4, 8, 0)) == (OK, 0x508000)
        self.call(pair, (5, 0x508000, 5, 0))  # last page free: no partial release
        assert self.call(pair, (5, 0x508000, 4, 0)) == (OK, 0)
        self.call(pair, (5, 0x508000, 4, 0))  # whole run already released
        assert self.call(pair, (4, 4, 8, 0)) == (OK, 0x508000)
        self.call(pair, (2, 0x509000, 0, 0))
        self.call(pair, (5, 0x508000, 4, 0))  # partial double free: atomic reject
        self.call(pair, (5, 0x508000, 1, 0))
        self.call(pair, (5, 0x50A000, 2, 0))
        for cmd in ((5, 0x503000, 1, 0), (5, 0x502000, 1, 0),
                    (5, 0x514000, 1, 0), (5, 0x513000, 2, 0),
                    (5, 0x508001, 1, 0), (5, 0x508000, 0, 0),
                    (5, 0x508000, 1, 1), (5, 0x508000, MASK, 0)):
            self.call(pair, cmd)
        zero = self.pair(65)
        self.call(zero, (0, 1, 0, 0))
        self.call(zero, (4, 1, 1, 0))
        self.call(zero, (5, 0, 1, 0))
        self.call(zero, (5, 0, 1, 0))
        self.cases.append("atomic contiguous release: independent set oracle, partial-double-free rollback, reserved/overflow, exact metadata and physical zero")

    def exact_claim_runs(self):
        # Independent address-set oracle, including exact-placement failures.
        pair = self.pair(67)
        assert self.call(pair, (6, 0x505000, 3, 0)) == (BAD_STATE, 0)
        assert self.call(pair, (6, 0x505000, 0, 0)) == (INVALID, 0)
        self.call(pair, (0, 17, 0x503000, 2))
        assert self.call(pair, (6, 0x505000, 3, 0)) == (OK, 0)
        assert self.call(pair, (6, 0x505000, 3, 0)) == (NO_MEMORY, 0)
        assert self.call(pair, (6, 0x504000, 3, 0)) == (RESERVED, 0)
        assert self.call(pair, (6, 0x507000, 2, 0)) == (NO_MEMORY, 0)
        assert self.call(pair, (2, 0x506000, 0, 0)) == (OK, 0)
        assert self.call(pair, (6, 0x505000, 3, 0)) == (NO_MEMORY, 0)
        self.call(pair, (2, 0x505000, 0, 0))
        self.call(pair, (2, 0x507000, 0, 0))
        assert self.call(pair, (6, 0x505000, 3, 0)) == (OK, 0)
        for cmd in ((6, 0x505001, 1, 0), (6, 0x505000, 0, 0),
                    (6, 0x505000, 1, 1), (6, 0x514000, 1, 0),
                    (6, 0x513000, 2, 0), (6, MASK, 2, 0)):
            self.call(pair, cmd)
        zero = self.pair(65)
        self.call(zero, (0, 1, 0, 0))
        assert self.call(zero, (6, 0, 1, 0)) == (OK, 0)
        assert self.call(zero, (6, 0, 1, 0)) == (NO_MEMORY, 0)
        self.call(zero, (5, 0, 1, 0))
        assert self.call(zero, (6, 0, 1, 0)) == (OK, 0)
        ceiling = self.pair(65)
        self.call(ceiling, (0, 1, LIMIT - PAGE, 0))
        assert self.call(ceiling, (6, LIMIT - PAGE, 1, 0)) == (OK, 0)
        assert self.call(ceiling, (6, LIMIT - PAGE, 2, 0)) == (INVALID, 0)
        self.cases.append("exact address claim: zero physical address, reserved, conflict immutability, boundary and reacquisition")

    def query_free_runs(self):
        pair = self.pair(67)
        assert self.call(pair, (7, 0x505000, 3, 0)) == (BAD_STATE, 0)
        assert self.call(pair, (7, 0x505000, 0, 0)) == (INVALID, 0)
        self.call(pair, (0, 17, 0x503000, 2))
        assert self.call(pair, (7, 0x505000, 3, 0)) == (OK, 3)
        assert self.call(pair, (7, 0x504000, 1, 0)) == (RESERVED, 0)
        assert self.call(pair, (6, 0x507000, 2, 0)) == (OK, 0)
        assert self.call(pair, (7, 0x505000, 5, 0)) == (NO_MEMORY, 0)
        assert self.call(pair, (7, 0x505000, 2, 0)) == (OK, 2)
        assert self.call(pair, (7, 0x507000, 2, 0)) == (NO_MEMORY, 0)
        self.call(pair, (5, 0x507000, 2, 0))
        assert self.call(pair, (7, 0x505000, 5, 0)) == (OK, 5)
        for cmd in ((7, 0x505001, 1, 0), (7, 0x505000, 0, 0),
                    (7, 0x505000, 1, 1), (7, 0x513000, 2, 0),
                    (7, MASK, 1, 0)):
            self.call(pair, cmd)
        zero = self.pair(65)
        self.call(zero, (0, 1, 0, 0))
        assert self.call(zero, (7, 0, 1, 0)) == (OK, 1)
        self.call(zero, (6, 0, 1, 0))
        assert self.call(zero, (7, 0, 1, 0)) == (NO_MEMORY, 0)
        ceiling = self.pair(65)
        self.call(ceiling, (0, 1, LIMIT - PAGE, 0))
        assert self.call(ceiling, (7, LIMIT - PAGE, 1, 0)) == (OK, 1)
        assert self.call(ceiling, (7, LIMIT - PAGE, 2, 0)) == (INVALID, 0)
        self.cases.append("read-only exact run query: independent set model, fragmentation, zero address, reserved, boundaries and immutability")

    def query_first_runs(self):
        # Query the real allocation bitmap without claiming the run. This is
        # the precursor to a single-owner multi-arena query-then-claim protocol.
        pair = self.pair(67)
        assert self.call(pair, (8, 4, 8, 0)) == (BAD_STATE, 0)
        for command in ((8, 0, 1, 0), (8, 1, 0, 0),
                        (8, 1, 3, 0), (8, 1, 1, 1)):
            assert self.call(pair, command) == (INVALID, 0)
        self.call(pair, (0, 17, 0x503000, 2))
        assert self.call(pair, (8, 4, 8, 0)) == (OK, 0x508000)
        assert self.call(pair, (8, 4, 8, 0)) == (OK, 0x508000)
        assert self.call(pair, (6, 0x508000, 4, 0)) == (OK, 0)
        assert self.call(pair, (8, 4, 8, 0)) == (OK, 0x510000)
        assert self.call(pair, (6, 0x510000, 4, 0)) == (OK, 0)
        assert self.call(pair, (8, 4, 8, 0)) == (NO_MEMORY, 0)
        assert self.call(pair, (5, 0x508000, 4, 0)) == (OK, 0)
        assert self.call(pair, (8, 4, 8, 0)) == (OK, 0x508000)
        zero = self.pair(65)
        self.call(zero, (0, 1, 0, 0))
        assert self.call(zero, (8, 1, 1, 0)) == (OK, 0)
        assert self.call(zero, (8, 1, 1, 0)) == (OK, 0)
        assert self.call(zero, (6, 0, 1, 0)) == (OK, 0)
        assert self.call(zero, (8, 1, 1, 0)) == (NO_MEMORY, 0)
        ceiling = self.pair(65)
        self.call(ceiling, (0, 1, LIMIT - PAGE, 0))
        assert self.call(ceiling, (8, 1, 1, 0)) == (OK, LIMIT - PAGE)
        assert self.call(ceiling, (8, 2, 1, 0)) == (NO_MEMORY, 0)
        self.cases.append("read-only live-bitmap aligned first-fit: fragmentation, occupied candidates, independence, physical zero, limit and immutable state")

    def randomized(self):
        for seed in range(32):
            rng = random.Random(0x48494100 + seed)
            pair = self.pair()
            n, reserved = rng.randint(7, 129), rng.randrange(7)
            base = rng.randrange(0, 1024) * PAGE
            self.call(pair, (0, n, base, reserved))
            for _ in range(250):
                choice = rng.randrange(19)
                if choice < 5:
                    c = (1, 1 << rng.randrange(9), 0, 0)
                elif choice < 8:
                    c = (2, base + rng.randrange(n + 2) * PAGE, 0, 0)
                elif choice < 10:
                    c = (4, rng.randint(1, 5), 1 << rng.randrange(6), 0)
                elif choice == 10:
                    c = (5, base + rng.randrange(n + 2) * PAGE, rng.randint(1, 5), 0)
                elif choice in (11, 12, 13):
                    c = (6, base + rng.randrange(n + 2) * PAGE, rng.randint(1, 5), 0)
                elif choice in (14, 15):
                    c = (7, base + rng.randrange(n + 2) * PAGE, rng.randint(1, 5), 0)
                elif choice in (16, 17):
                    c = (8, rng.randint(1, 5), 1 << rng.randrange(6), 0)
                else:
                    c = (3, 0, 0, 0)
                self.call(pair, c)
        self.cases.append("32 fixed reproducible random traces, 250 operations per trace, set-oracle comparison after every operation")

    def maximum(self):
        pair = self.pair(8256)
        self.call(pair, (0, 65536, 0x400000, 65535))
        self.call(pair, (1, 1, 0, 0))
        self.call(pair, (1, 1, 0, 0))
        self.call(pair, (2, 0x400000 + 65535 * PAGE, 0, 0))
        self.cases.append("maximum 65536-page arena with exact 8256-byte metadata capacity")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--report", type=Path, default=Path("build/native-report.json"))
    args = parser.parse_args()
    campaign = Campaign(args.library)
    report = {"schema": "heptakernel.native-tests.v1", "scope": "HIA single-arena allocator with atomic contiguous allocation, release, exact claim and two read-only live-bitmap query modes",
              "linux_compatibility_tested": False, "formal_proof": False,
              "tested_library": str(args.library.resolve()),
              "tested_library_sha256": hashlib.sha256(args.library.read_bytes()).hexdigest(),
              "object_sha256": hashlib.sha256(Path("build/kernel.o").read_bytes()).hexdigest(),
              "source_sha256": hashlib.sha256(Path("src/kernel.hepta").read_bytes()).hexdigest()}
    try:
        # HIA's object has no relocations. Verify the linked library actually
        # contains those exact instruction bytes before attaching its evidence.
        def text_section(path):
            raw = Path(path).read_bytes()
            assert raw[:6] == b"\x7fELF\x02\x01", "ELF64 little-endian required"
            offset = struct.unpack_from("<Q", raw, 40)[0]
            entry_size, count, strings = struct.unpack_from("<3H", raw, 58)
            headers = [struct.unpack_from("<IIQQQQIIQQ", raw, offset + i * entry_size) for i in range(count)]
            table = headers[strings]
            names = raw[table[4]:table[4] + table[5]]
            for h in headers:
                name = names[h[0]:].split(b"\0", 1)[0]
                if name == b".text":
                    return raw[h[4]:h[4] + h[5]]
            raise AssertionError("missing .text section")
        assert text_section(args.library) == text_section("build/kernel.o"), "loaded library does not match HIA object"
        report["library_text_matches_object"] = True
        campaign.boundaries()
        campaign.alignment()
        campaign.invalid()
        campaign.header_corruption()
        campaign.bitmap_corruption()
        campaign.contiguous_runs()
        campaign.free_runs()
        campaign.exact_claim_runs()
        campaign.query_free_runs()
        campaign.query_first_runs()
        campaign.randomized()
        campaign.maximum()
        report.update(status="PASS", calls=campaign.commands, cases=campaign.cases)
    except Exception as exc:
        report.update(status="FAIL", calls=campaign.commands, cases=campaign.cases, error=repr(exc))
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
