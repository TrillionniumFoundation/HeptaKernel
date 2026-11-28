# Scoped HIA Linux device number conversion

This freestanding, pure-integer x86-64 SysV leaf is intended for eventual
filesystem and Linux stat device-field integration. It does not assign devices,
perform I/O, implement stat or mknod, or close a Linux acceptance obligation.

`linux_devnum(u64 op, u64 value) -> u64` has four operations:

| op | accepted input | result |
| --- | --- | --- |
| 0 | unsigned 32-bit internal dev_t, major:minor = 12:20 | modern encoded u32 |
| 1 | unsigned 32-bit modern encoded word | internal dev_t |
| 2 | unsigned 32-bit internal dev_t with both fields below 256 | legacy encoded u16 |
| 3 | unsigned 16-bit legacy encoded word | internal dev_t |

The modern word places the low minor byte at bits 7:0, the complete major
at bits 19:8, and the upper minor at bits 31:20. Wider values, unknown
operations, and unrepresentable legacy encodings return UINT64_MAX, which
cannot collide with any valid result (including 0xffffffff).
The u64 calling convention and explicit refusal are this leaf's contract;
they do not change kernel C conversion semantics within the valid domain.
SysV and the user-space glibc wide dev_t representation are out of scope.

The local check compiles the original GPL Linux header from immutable baseline
`7595a62d45ee1a2297eafa5f2ef5d0a45142d84d` into a separate host-only C
oracle. It verifies both Linux header Git blob identities and the repository's
pinned HIA compiler digest, recompiles the same HIA ELF object twice, verifies
absence of undefined symbols, and checks that the host wrapper preserves the
complete emitted machine text before invoking it. No C is linked into the HIA
object. All 65,536 legacy words and 20,104 modern inputs in both round-trip
directions are tested, including basis bits and field boundaries. A separately
compiled HIA control that drops the first high minor bit must disagree with
the oracle. The local machine-readable result is in
[`validation/linux-devnum-native.json`](../validation/linux-devnum-native.json).

From the repository root, on Linux x86-64 with GNU binutils, a C compiler
driver and Python 3:

```sh
python3 -I -B tests/test_linux_devnum.py \
  --compiler .toolchain/compiler/native-compiler \
  --linux-root /path/to/locked/linux \
  --report linux-devnum-native.json
```

For source bootstrap of the pinned compiler, see [build.md](build.md). Full
Linux acceptance stays HOLD; boot-path and filesystem integration are separate.
