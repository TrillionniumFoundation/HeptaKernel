# ELF64 PT_LOAD segment-layout admission in genuine native HIA (partial)

`src/elf64_load_segments.hepta` is compiled by the pinned upstream HIA Core v8
`selfhost_elf` native x86-64 backend. It does not embed foreign code, call libc,
use Linux syscalls, or implement an interpreter. Its public ABI is
`(readbuf image, mutbuf unused, mutbuf unused) -> u32`; inputs are bounded
caller-supplied *complete* ELF image bytes. The function never writes.

The first 1–7 return statuses follow the existing `elf64_exec_admit` header
gate, except this bounded scanning profile rejects `e_phnum > 128` as 5.
For every program header the new HIA code reads the actual bytes, handles
PT_LOAD, refuses PT_INTERP, and returns:

| Code | Narrow conclusion |
| --- | --- |
| 0 | All scanned PT_LOAD records meet policy and entry is in a file-backed executable load |
| 8 | No PT_LOAD |
| 9 | A PT_LOAD has unknown flag bits or writable+executable flags |
| 10 | PT_LOAD geometry invalid: empty memory span, file > memory, file out of range, non-user-range mapping, bad page congruence or p_align |
| 11 | Entry outside all file-backed executable PT_LOAD segments |
| 12 | PT_INTERP present; interpreter handling not implemented |

For individual PT_LOAD entries it checks `p_filesz <= p_memsz`, nonzero
`p_memsz`, bounded file ranges without addition overflow, page-offset
congruence, a power-of-two/0/1 `p_align` and `p_vaddr % p_align ==
p_offset % p_align` when nontrivial. Low-half 48-bit user VAs must stay
in `[0x1000, 2^47)` including `p_memsz`. An executable entry must be in
file-backed bytes rather than only a zero-filled tail. The distinct entry
does not imply permission to execute or trust the bytes.

Independent Python oracle and adversarial byte mutation campaign use the
actual selfhost native object and a separate dishonest HIA constant-success
object. The gate binds original .text to linked library .text, tests canary
integrity, and compares two empty-PATH rebuilds with the production object.
`make test-elf64-load-segments` is required by `make test` and Foundation CI.
Every report is attached to the exact candidate.

This is **not safe ELF loading or generic ELF conformance**. The admitted
PT_LOAD records have not been proven mutually non-overlapping, nor does
the gate check PT_GNU_STACK, PT_GNU_RELRO, PT_DYNAMIC, PT_TLS, section state,
load bias, relocation, mmaps, mapping ownership, W^X enforcement by a CPU,
file authenticity, atomicity or coherent memory read. ET_DYN is parsed
without an ASLR/load-bias policy. Non-LOAD types except PT_INTERP are
not yet interpreted. No user task, syscall, startup stack, page allocator
integration or QEMU user process is introduced in this change. Any
claim that status 0 is enough to execute an arbitrary binary is invalid.

Linux 7.3.4 baseline, locked HIA compiler, all 17 full-acceptance gates
and 422 x86-64 syscall rows remain unchanged and HOLD.
