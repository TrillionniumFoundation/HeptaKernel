#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Run the actual HIA and pinned Linux helper with independent ABI observers."""
import argparse
import ctypes as c
import hashlib
import itertools
import json
from pathlib import Path
import platform
import random
import struct
import subprocess
import tempfile

COMPILER_SHA = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
LINUX_SHA = "3b0f4859b379dce907d3836354bbc1d1fd8af98b84189630125126021f343f23"
MAX = (1 << 63) - 1
INF = (1 << 64) - 1
LEGACY = (1 << 31) - 1
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/vfs_write_limits.hepta"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs).stdout


def linux_oracle(source_path, work, cc):
    raw = source_path.read_bytes()
    if sha(raw) != LINUX_SHA:
        raise ValueError("fs/read_write.c does not match the locked Linux bytes")
    src = raw.decode()
    start = src.index("int generic_write_check_limits(")
    stop = src.index("\nEXPORT_SYMBOL_GPL(generic_write_check_limits);", start)
    code = """#include <stdint.h>
typedef int64_t loff_t;
struct super_block { loff_t s_maxbytes; };
struct inode { struct super_block *i_sb; };
struct address_space { struct inode *host; };
struct file { struct address_space *f_mapping; unsigned int f_flags; };
#define MAX_NON_LFS ((1UL<<31)-1)
#define O_LARGEFILE (1 << 15)
#define RLIMIT_FSIZE 1
#define RLIM_INFINITY (~0UL)
#define SIGXFSZ 25
#define EFBIG 27
#define min(x,y) ((x) < (y) ? (x) : (y))
#define unlikely(x) (x)
#define current ((void *)0)
static unsigned long supplied_limit;
static unsigned long rlimit(int which) { return which == RLIMIT_FSIZE ? supplied_limit : 0; }
static uint64_t last_signal;
static void send_sig(int sig, void *task, int priv) {
    (void)task;
    last_signal = priv ? UINT64_MAX : (uint64_t)sig;
}
_Static_assert(sizeof(unsigned long) == 8, "native x86-64 limit ABI");
""" + src[start:stop] + """
int observe(int64_t pos, uint64_t limit, int64_t maxbytes, unsigned int large,
            int64_t *count, uint64_t *signal)
{
    struct super_block sb = {maxbytes};
    struct inode inode = {&sb};
    struct address_space mapping = {&inode};
    struct file file = {&mapping, large ? O_LARGEFILE : 0};
    supplied_limit = limit;
    last_signal = 0;
    int status = generic_write_check_limits(&file, pos, count);
    *signal = last_signal;
    return status;
}
"""
    path = work / "linux_oracle.c"
    path.write_text(code)
    binary = work / "linux_oracle.so"
    run([cc, "-O2", "-fPIC", "-shared", "-std=gnu11", str(path), "-o", str(binary)])
    lib = c.CDLL(str(binary))
    func = lib.observe
    func.argtypes = [c.c_int64, c.c_uint64, c.c_int64, c.c_uint,
                    c.POINTER(c.c_int64), c.POINTER(c.c_uint64)]
    func.restype = c.c_int

    def observe(case):
        pos, requested, limit, maxbytes, large = case
        count, signal = c.c_int64(requested), c.c_uint64(0)
        result = func(pos, limit, maxbytes, large, c.byref(count), c.byref(signal))
        if result not in (0, -27) or signal.value not in (0, 25):
            raise AssertionError((result, signal.value))
        return -result, count.value, int(signal.value == 25)

    return observe


def hia(comp, work):
    source = SOURCE.read_bytes()
    if sha(comp.read_bytes()) != COMPILER_SHA:
        raise ValueError("compiler does not match the HeptaKernel lock")
    compile_args = dict(input=source, stdout=subprocess.PIPE, env={"PATH": ""})
    a, b = (run([str(comp)], **compile_args) for _ in range(2))
    assert a == b and a.startswith(b"\x7fELF\x02\x01")
    obj, lib = work / "vfs-write-limits.o", work / "vfs-write-limits.so"
    obj.write_bytes(a)
    assert run(["nm", "-u", str(obj)], stdout=subprocess.PIPE) == b""
    run(["ld", "-shared", "-z", "noexecstack", "-o", str(lib), str(obj)])
    for binary in (obj, lib):
        run(["objcopy", "--dump-section", f".text={binary}.text", str(binary)])
    assert Path(f"{obj}.text").read_bytes() == Path(f"{lib}.text").read_bytes()
    loaded = c.CDLL(str(lib))
    entry = loaded.f0
    entry.argtypes = [c.c_void_p, c.c_uint64] * 3
    entry.restype = c.c_uint32

    def observe(request, capacity=24):
        guard = b"\xA5" * 32
        req = c.create_string_buffer(guard + request + guard)
        rep = c.create_string_buffer(guard + b"\xC7" * capacity + guard)
        scratch = c.create_string_buffer(guard * 3)
        ptr = lambda buf: c.addressof(buf) + 32
        status = entry(ptr(req), len(request), ptr(rep), capacity, ptr(scratch), 32)
        assert req.raw == guard + request + guard + b"\x00"
        assert scratch.raw == guard * 3 + b"\x00"
        assert rep.raw[:32] == guard and rep.raw[32 + capacity:] == guard + b"\x00"
        if capacity < 24:
            assert status == 1 and rep.raw[32:32 + capacity] == b"\xC7" * capacity
            return None
        assert rep.raw[56:32 + capacity] == b"\xC7" * (capacity - 24)
        words = struct.unpack_from("<3Q", rep.raw, 32)
        assert words[0] == status
        return words

    return observe, {"source_sha256": sha(source), "object_sha256": sha(a),
                     "compiler_sha256": COMPILER_SHA, "linux_source_sha256": LINUX_SHA}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler", type=Path, required=True)
    p.add_argument("--linux-source", type=Path, required=True)
    p.add_argument("--cc", default="cc")
    args = p.parse_args()
    if platform.machine() != "x86_64":
        p.error("x86_64 host required")
    with tempfile.TemporaryDirectory(prefix="hepta-write-limits-") as d:
        work = Path(d)
        source_result = linux_oracle(args.linux_source, work, args.cc)
        native, report = hia(args.compiler.resolve(), work)
        fixed = (0, 1, 2, LEGACY - 1, LEGACY, LEGACY + 1, MAX - 1, MAX)
        directed = itertools.product(fixed, fixed, (*fixed, INF), fixed, (0, 1))
        counts, categories = {}, set()

        def test(case, *, capacity=24):
            expected = source_result(case)
            actual = native(struct.pack("<5Q", *case), capacity)
            assert actual == expected, (case, actual, expected)
            categories.add((actual[0], actual[1] < case[1], actual[2]))
            counts["linux_oracle"] = counts.get("linux_oracle", 0) + 1

        for case in directed:
            test(case)
        rand = random.Random(73_04)
        for _ in range(4000):
            pos, count = rand.randrange(MAX + 1), rand.randrange(MAX + 1)
            neighbors = (0, max(0, pos - 1), pos, min(MAX, pos + 1), MAX)
            test((pos, count, rand.choice((*neighbors, INF)),
                  rand.choice(neighbors), rand.randrange(2)), capacity=40)
        assert {(0, False, 0), (0, True, 0), (27, False, 1),
                (27, False, 0), (27, True, 0)} <= categories
        pack = lambda *v: struct.pack("<5Q", *v)
        wire = pack(0, 1, INF, MAX, 1)
        malformed = [wire[:i] for i in range(40)] + [wire + b"X"]
        malformed += [pack(MAX + 1, 0, INF, MAX, 1), pack(0, MAX + 1, INF, MAX, 1),
                      pack(0, 0, MAX + 1, MAX, 1), pack(0, 0, INF, INF, 1),
                      pack(0, 0, INF, MAX, 2)]
        for row in malformed:
            assert native(row) == (2, 0, 0)
        for n in range(24):
            assert native(wire, n) is None
        counts.update(malformed_requests=len(malformed), short_replies=24)
        print(json.dumps(dict(report, **counts, status="PASS", full_linux_acceptance="HOLD"), sort_keys=True))


if __name__ == "__main__":
    main()
