# SPDX-License-Identifier: GPL-2.0-only
"""Compose real HIA E820 discovery, E820 admission, and PMM in a host fixture."""
import ctypes
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

# -I does not add the script directory. Only add this checkout's test directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_native import Native as Allocator

ROOT = Path(__file__).resolve().parents[1]
PAGE, LIMIT = 4096, 1 << 52
SOURCES = ("e820_find_arena", "e820_region", "kernel")
COMPILER_PIN = "87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54"


def sha(b):
    return hashlib.sha256(b).hexdigest()


def build(compiler, out):
    receipt, paths = {}, {}
    for name in SOURCES:
        source = (ROOT / f"src/{name}.hepta").read_bytes()
        cmd = [str(compiler)]
        obj = subprocess.check_output(cmd, input=source, env={"PATH": ""}, timeout=30)
        if not obj or subprocess.check_output(cmd, input=source, env={"PATH": ""}, timeout=30) != obj:
            raise ValueError(f"{name}: nonrepeatable object")
        object_path, lib = out / f"{name}.o", out / f"{name}.so"
        object_path.write_bytes(obj)
        if subprocess.check_output(["nm", "-u", object_path], timeout=10):
            raise ValueError(f"{name}: unexpected external symbols")
        subprocess.run(["ld", "-shared", "-z", "noexecstack", "-o", lib, object_path],
                       check=True, timeout=10)
        texts = []
        for i, elf in enumerate((object_path, lib)):
            text = out / f"{name}-{i}.text"
            # Name a separate output ELF so objcopy never rewrites the input.
            subprocess.run(["objcopy", "--dump-section", f".text={text}", elf,
                            out / f"{name}-{i}.copy"], check=True, timeout=10)
            texts.append(text.read_bytes())
        if not texts[0] or texts[0] != texts[1]:
            raise ValueError(f"{name}: linked text differs from native object")
        paths[name] = lib
        receipt[name] = {"source_sha256": sha(source), "object_sha256": sha(obj),
                         "linked_text_sha256": sha(texts[0])}
    return receipt, paths


def gate(path):
    native = ctypes.CDLL(str(path))
    f = native.f0
    f.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
    f.restype = ctypes.c_uint32

    def call(data):
        prefix, suffix = b"G" * 16, b"T" * 16
        raw = ctypes.create_string_buffer(prefix + data + suffix)
        reply = ctypes.create_string_buffer(prefix + bytes(16) + suffix)
        state = ctypes.create_string_buffer(b"M" * 32)
        before_raw, before_state = bytes(raw), bytes(state)
        rc = f(ctypes.addressof(raw) + 16, len(data), ctypes.addressof(reply) + 16, 16,
               state, 32)
        observed = bytes(reply)
        assert bytes(raw) == before_raw and bytes(state) == before_state
        assert observed[:16] == prefix and observed[32:] == suffix + b"\0"
        pair = struct.unpack_from("<QQ", observed, 16)
        assert rc == pair[0]
        return pair

    return call


def exercises(paths):
    discovery, admit = (gate(paths[name]) for name in SOURCES[:2])
    lo = 0x400000
    ram = (lo, 32 * PAGE, 1, 1)
    fixtures = [
        ("plain", lo, lo + 32 * PAGE, 8, 4, [ram], (0, lo)),
        ("blocked_first_byte", lo, lo + 32 * PAGE, 6, 8,
         [ram, (lo + 1, 1, 2, 1)], (0, lo + 8 * PAGE)),
        ("ram_union", lo, lo + 32 * PAGE, 7, 4,
         [(lo + 17, 7 * PAGE - 17, 1, 1), (lo, 17, 1, 1)], (0, lo)),
        ("disabled_ignored", lo, lo + 32 * PAGE, 5, 4,
         [ram, (lo, 32 * PAGE, 2, 0)], (0, lo)),
        ("persistent_overlap", lo, lo + 32 * PAGE, 3, 2,
         [ram, (lo, PAGE + 1, 1, 3)], (0, lo + 2 * PAGE)),
        ("physical_limit", LIMIT - 4 * PAGE, LIMIT, 4, 4,
         [(LIMIT - 4 * PAGE, 4 * PAGE, 1, 1)], (0, LIMIT - 4 * PAGE)),
        ("blocked_everywhere", lo, lo + 32 * PAGE, 2, 4,
         [ram, (lo, 32 * PAGE, 2, 1)], (5, 0)),
        ("gap_at_join", lo, lo + 2 * PAGE, 2, 1,
         [(lo, PAGE, 1, 1), (lo + PAGE + 1, PAGE, 1, 1)], (5, 0)),
        ("invalid_row", lo, lo + 32 * PAGE, 2, 4, [ram, (0, 0, 2, 0)], (6, 0)),
    ]
    outcomes = []
    for name, begin, end, pages, align, rows, expected in fixtures:
        for reverse in (False, True):
            rows_wire = b"".join(struct.pack("<QQII", *row)
                                 for row in (rows[::-1] if reverse else rows))
            pmm = Allocator(paths["kernel"])
            before = pmm.snapshot()
            result = discovery(struct.pack("<5Q", begin, end, pages, align * PAGE, len(rows))
                               + rows_wire)
            assert result == expected, (name, result, expected)
            case = {"case": name, "reverse_rows": reverse, "discovery": result,
                    "pmm_invocations": 0}
            if result[0]:
                assert pmm.snapshot() == before
                outcomes.append(case)
                continue
            base = result[1]
            assert admit(struct.pack("<3Q", base, pages, len(rows)) + rows_wire) == (0, pages)
            # The entire offered arena is initially free. Query, reserve, verify
            # exhaustion, release, and exercise the new full-state bitmap audit.
            commands = [((0, pages, base, 0), (0, pages)),
                        ((8, pages, align, 0), (0, base)),
                        ((4, pages, align, 0), (0, base)),
                        ((3, 0, 0, 0), (0, 0)),
                        ((1, 1, 0, 0), (5, 0)),
                        ((5, base, pages, 0), (0, 0)),
                        ((3, 0, 0, 0), (0, pages)),
                        ((8, pages, align, 0), (0, base))]
            for cmd, reply in commands:
                assert pmm.call(cmd) == reply, (name, cmd)
            case["pmm_invocations"] = len(commands)
            outcomes.append(case)
    return outcomes


def main():
    if not __debug__:
        raise SystemExit("run with assertions enabled")
    if len(sys.argv) != 2:
        raise SystemExit("usage: test_native_memory_chain.py /path/to/pinned-native-compiler")
    compiler = Path(sys.argv[1]).resolve(strict=True)
    digest = sha(compiler.read_bytes())
    pin = json.loads((ROOT / "compatibility/hia-toolchain-lock.json").read_text())
    # Assert the exact lock schema and pinned bytes before executing the compiler.
    if (pin.get("schema") != "heptakernel.hia-toolchain-lock.v1"
            or digest != COMPILER_PIN or pin.get("compiler_sha256") != COMPILER_PIN):
        raise SystemExit("compiler differs from the locked executable")
    with tempfile.TemporaryDirectory() as tmp:
        blobs, paths = build(compiler, Path(tmp))
        cases = exercises(paths)
    print(json.dumps({"status": "PASS", "scope": "host-composed-native-HIA",
                      "full_linux_acceptance": "HOLD", "compiler_sha256": digest,
                      "targets": blobs, "cases": cases,
                      "pmm_invocations": sum(c["pmm_invocations"] for c in cases)},
                     sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
