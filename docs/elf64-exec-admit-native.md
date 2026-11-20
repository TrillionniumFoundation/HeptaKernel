# Native HIA ELF64 executable-header admission (partial loader prerequisite)

This component adds a **genuine HIA Core v8 `selfhost_elf` native
x86-64 function**, `src/elf64_exec_admit.hepta`, and an independently
authored Python byte-level oracle. It does not execute host syscalls or
embed externally assembled machine code in the HIA source.

The public ABI is `(readbuf image, mutbuf unused, mutbuf unused) -> u32`.
The input is a bounded **caller-provided full image byte slice**.
The function performs no writes. Return values:

| Status | Meaning |
| --- | --- |
| 0 | Narrow header and program-header *span* admitted |
| 1 | Image shorter than 64-byte ELF64 header |
| 2 | Invalid ELF magic |
| 3 | Non-ELF64/LSB/version-one, unsupported OSABI, or dirty EI_PAD |
| 4 | Not ET_EXEC/ET_DYN x86-64 with e_version = 1 |
| 5 | Invalid e_ehsize, e_phentsize, e_phnum (PN_XNUM refused) |
| 7 | Entry not in [0x1000, 2^47) user canonical low half |
| 6 | Program header table offset not aligned/in bounds, or full table absent |

The code checks `e_phoff <= image_len` before subtracting, and computes
`e_phnum * 56` only after the number is bounded to 1..65534, preventing
64-bit overflow. This narrowly rejects nonstandard but potentially valid
ELF images (for example extended program-header count or zero-entry
shared objects) rather than claiming all Linux ELF compatibility.

## Evidence and regression contract

`make test-elf64-exec-admit` independently verifies malformed and
positive headers, random byte mutations, truncated images, raw buffer
and canary integrity, original native `.text` against linked `.so`,
a **compiled dishonest HIA constant-success program** with the same
ABI, and two `env -i PATH=''` compiler runs whose objects must be
byte-identical to the original. `make test` and Foundation CI include
this gate, retaining a report bound to the exact CI commit.

This is **not an ELF loader**, even when tests pass. No PT_LOAD segment
walk, file-backed page mapping, W^X enforcement, relocations, auxv,
interpreter, TLS, process state, user stack, signal state, syscall
dispatch, ASLR, credentials, or independently booted executable is
implemented. Input authenticity, concurrent mutation and CPU profile
are not established. In particular, status 0 does not mean the entry
lies in an executable PT_LOAD segment: that is a future *mandatory*
precondition before executing such an image.

The user-defined full Linux target is unchanged: all 17 gates remain
HOLD, all 422 x86-64 syscall obligations remain open, and
`make full-acceptance` must still return 2. The pinned Linux source
and HIA compiler locks have not moved.
