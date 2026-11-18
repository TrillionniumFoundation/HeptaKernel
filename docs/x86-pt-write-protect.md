# Native HIA quiescent PTE write-protection downgrade

This implementation is genuine `hia-asm.v1 hepta.hia.program.v8 selfhost_elf`
compiled by the pinned HIA Core v8 bootstrap. `src/x86_pt_write_protect.hepta`
takes the same (request:32B, reply:>=16B, table:4096B) buffer ABI as the
existing native page-table commit/revoke primitives. It does not embed machine
code, host assembler, or a Linux system call.

The request is four little-endian u64 values: leaf slot (0..511), exact
expected old PTE, proposed new PTE, and capability profile (physical width,
NXE, PGE). The transition is restricted to **present, writable, NX** 4KiB
pages. The proposed new entry must equal exactly `expected_old - 2`:
the leaf RW bit is cleared, and *every other bit* (frame address, user,
cache, Accessed/Dirty, PAT, global, software flags, NX) is preserved.
High reserved bits, out-of-profile physical addresses, user/global conflict
and unsupported NXE/PGE are refused. The existing live old entry must
match all 64 expected bits before the eight-byte modification.

Statuses: 1 short reply, 2 wrong request length, 4 invalid table length,
6 invalid transition/index/PTE, 8 invalid CPU capability profile, 9 stale
old value. Refusals cannot modify the table. A fully independent byte-array
oracle checks boundary slots, A/D retention, valid downgrades, invalid
upgrades, malformed caps, exact-old stale replay and buffer guards. A second
genuine-HIA implementation that dishonestly returns 0 without writing
must be rejected by the same oracle.

**Scope:** only single-owner, quiescent mapping downgrade; writes are
bytewise and not atomic 64-bit CAS. This does not invalidate TLB entries,
guarantee remote CPU visibility, enforce authority for page ownership,
implement `mprotect`, or solve arbitrary Linux memory-management behavior.
The existing non-HIA `INVLPG` and exception bridge remains explicitly
outside HIA closure. All 17 gates and 422 syscall obligations stay open.
