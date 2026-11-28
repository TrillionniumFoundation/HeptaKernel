# SPDX-License-Identifier: GPL-2.0-only
"""Run the real native HIA dirent64 leaf vs pinned Linux ABI and live host records."""
import argparse
import collections
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"
REF = "7595a62d45ee1a2297eafa5f2ef5d0a45142d84d"
PINS = {
    "fs/readdir.c": "f2288841337ad10eea121f64db86109aff1ca104",
    "include/linux/dirent.h": "99002220cd452646b924f76f3c37909d804a67d4",
    "include/linux/fs_dirent.h": "92f75c5bac19022d2e28335d7722955764895ff3",
    "include/uapi/linux/limits.h": "6bcbe306876196e53064dcd2f4099696208a1a48",
}
ORACLE = r"""
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#define ALIGN(value, alignment) (((value) + ((alignment) - 1)) & ~((alignment) - 1))
#include "linux/dirent.h"
#include "linux/fs_dirent.h"
#include "uapi/linux/limits.h"

_Static_assert(offsetof(struct linux_dirent64, d_name) == 19, "x86-64 layout");
REPLACEMENTS
int oracle(u64 ino, s64 off, u64 flags, const char *name, int namlen,
           unsigned char *out, size_t capacity) {
    struct linux_dirent64 *dirent = (struct linux_dirent64 *)out;
    if (namlen <= 0 || namlen >= PATH_MAX)
        return -EIO;
    if (flags > UINT32_MAX)
        return -EINVAL;
    int status = verify_dirent_name(name, namlen);
    if (status)
        return status;
    DECLARATION
    if (capacity < (size_t)reclen)
        return -EINVAL;
    dirent->d_ino = ino;
    dirent->d_off = off;
    dirent->d_reclen = reclen;
    dirent->d_type = flags & S_DT_MASK;
    memcpy(dirent->d_name, name, namlen);
    dirent->d_name[namlen] = '\0';
    return reclen;
}
"""


def run(args, *, data=None, env=None):
    return subprocess.run(args, input=data, env=env, capture_output=True, check=True, timeout=30).stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build_native(compiler, source, work):
    obj, so = work / "native.o", work / "native.so"
    data = run([compiler], data=source, env={"PATH": ""})
    assert data and data == run([compiler], data=source, env={"PATH": ""})
    obj.write_bytes(data)
    assert run(["nm", "-u", obj]) == b""
    run(["ld", "-shared", "-z", "noexecstack", "-o", so, obj])
    texts = []
    for n, p in enumerate((obj, so)):
        t = work / f"text{n}"
        run(["objcopy", "--dump-section", f".text={t}", p, work / f"copy{n}"])
        texts.append(t.read_bytes())
    assert texts[0] and texts[0] == texts[1]
    native = ctypes.CDLL(str(so))
    native.f0.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    native.f0.restype = ctypes.c_int32
    return native.f0, sha(data), sha(texts[0])


def build_oracle(linux, work):
    for path, digest in PINS.items():
        raw = (linux / path).read_bytes()
        assert hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == digest, path
    code = (linux / "fs/readdir.c").read_text()
    verify = re.search(r"static int verify_dirent_name\(.*?\n\}", code, re.S).group(0)
    size = re.search(r"#define dirent_size[^\n]+", code).group(0)
    declaration = re.search(r"\bint reclen = ALIGN\(dirent_size\(dirent, namlen \+ 1\), sizeof\(u64\)\);",
                            code).group(0)
    shim = work / "shim/linux"
    shim.mkdir(parents=True)
    (shim / "types.h").write_text("#include <stdint.h>\ntypedef uint64_t u64;\ntypedef int64_t s64;\n"
                                  "typedef unsigned short umode_t;\n")
    (shim / "stat.h").write_text("#include <sys/stat.h>\n")
    out = work / "oracle.so"
    source = ORACLE.replace("REPLACEMENTS", size + "\n" + verify).replace("DECLARATION", declaration)
    run(["cc", "-x", "c", "-std=gnu11", "-include", shim / "types.h", "-shared", "-fPIC",
         "-I", shim.parent, "-I", linux / "include", "-o", out, "-"], data=source.encode())
    ref = ctypes.CDLL(str(out)).oracle
    ref.argtypes = [ctypes.c_uint64, ctypes.c_int64, ctypes.c_uint64, ctypes.c_void_p,
                    ctypes.c_int32, ctypes.c_void_p, ctypes.c_size_t]
    ref.restype = ctypes.c_int32
    return ref


def native_call(f, ino, offset, flags, name, capacity):
    packet = struct.pack("<QqQ", ino, offset, flags) + name
    marker = b"X" * 16
    raw = ctypes.create_string_buffer(marker + packet + marker)
    out = ctypes.create_string_buffer(marker + b"\xA5" * capacity + marker)
    unused = ctypes.create_string_buffer(b"Z" * 32)
    rc = f(ctypes.addressof(raw) + 16, len(packet), ctypes.addressof(out) + 16, capacity,
           unused, 32)
    assert bytes(raw) == marker + packet + marker + b"\0"
    assert bytes(unused) == b"Z" * 32 + b"\0"
    reply = bytes(out)
    assert reply[:16] == marker and reply[-17:] == marker + b"\0"
    return rc, reply[16:-17]


def live(f, directory):
    for name in ("plain", "unicode-ß", "x" * 255):
        (directory / name).write_bytes(b"")
    (directory / "child").mkdir()
    (directory / "relative-link").symlink_to("plain")
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.syscall.restype = ctypes.c_long
        out = ctypes.create_string_buffer(b"\xA5" * 8192)
        size = libc.syscall(ctypes.c_long(217), ctypes.c_int(fd), out, ctypes.c_uint(8192))
        assert 0 < size < 8192, ctypes.get_errno()
    finally:
        os.close(fd)
    blob = bytes(out)[:size]
    seen = set()
    pos = 0
    while pos < len(blob):
        ino, off, reclen, kind = struct.unpack_from("<QqHB", blob, pos)
        assert 24 <= reclen <= len(blob) - pos and reclen % 8 == 0
        name = blob[pos + 19:pos + reclen].split(b"\0", 1)[0]
        actual, emitted = native_call(f, ino, off, kind, name, reclen)
        assert actual == reclen and emitted == blob[pos:pos + reclen], name
        seen.add(name)
        pos += reclen
    assert seen == {b".", b"..", b"plain", b"child", b"relative-link",
                    "unicode-ß".encode(), b"x" * 255}
    return len(seen)


def main():
    app = argparse.ArgumentParser()
    app.add_argument("--compiler", required=True, type=Path)
    app.add_argument("--linux", required=True, type=Path)
    app.add_argument("--report", required=True, type=Path)
    args = app.parse_args()
    if not __debug__ or platform.machine() != "x86_64" or platform.system() != "Linux":
        app.error("requires assertions and x86-64 Linux")
    compiler, linux = args.compiler.resolve(), args.linux.resolve()
    assert sha(compiler.read_bytes()) == COMPILER, "wrong native compiler"
    source = (ROOT / "src/linux_dirent64.hepta").read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        f, object_sha, text_sha = build_native(compiler, source, work)
        oracle = build_oracle(linux, work)
        counts = collections.Counter()

        def check(ino, off, flags, name, cap):
            guard = b"Q" * 16
            out = ctypes.create_string_buffer(guard + b"\xA5" * cap + guard)
            rc = oracle(ino, off, flags, ctypes.create_string_buffer(name), len(name),
                        ctypes.addressof(out) + 16, cap)
            reference = bytes(out)
            assert reference[:16] == guard and reference[-17:] == guard + b"\0"
            ret, actual = native_call(f, ino, off, flags, name, cap)
            assert (ret, actual) == (rc, reference[16:-17]), (ret, rc, len(name), cap)
            counts["success" if rc > 0 else str(rc)] += 1

        for length in range(1, 4096):
            n = (20 + length + 7) & ~7
            for cap in (n - 1, n, n + 7):
                check(2**64 - length, length - 2048, 0x80000000 | length, b"x" * length, cap)
        for name in (b"", b"x" * 4096, b"/", b"a/b", b"a\0/b", b"a\0b", b"\xff"):
            for capacity in (0, 24, 4200):
                check(0, -(2**63), 0xFFFFFFFF, name, capacity)
        for flags in (2**32, 2**64 - 1):
            check(1, 2**63 - 1, flags, b"a", 24)
        rng = random.Random(20261128)
        for _ in range(512):
            name = rng.randbytes(rng.randint(1, 257))
            check(rng.getrandbits(64), rng.randrange(-(2**63), 2**63),
                  rng.getrandbits(32), name, rng.randrange(320))
        actual = work / "actual"
        actual.mkdir()
        host_count = live(f, actual)
    report = {"status": "PASS", "scope": "single native directory record, not a syscall",
              "full_linux_acceptance": "HOLD", "compiler_sha256": COMPILER,
              "linux_commit": REF, "linux_git_blobs": PINS, "source_sha256": sha(source),
              "object_sha256": object_sha, "text_sha256": text_sha,
              "pinned_oracle_calls": sum(counts.values()), "outcomes": dict(counts),
              "actual_host_kernel_records": host_count}
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
