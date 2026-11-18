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

## Isolated live MMU write-protection experiment

The three additional QEMU boot images call the **same exact genuine HIA**
RW->RO writer on the live 4 MiB page's 4 KiB PTE, *after* a successful
supervisor write and read. The CPU can set Accessed and Dirty bits during the
warm store; the request therefore captures the **actual** old PTE only after
that access. The HIA transition clears RW and preserves every other PTE bit.
The observer checks the returned HIA status and PTE readback, then invalidates
the local TLB using expressly **non-HIA** `INVLPG` and checks that reads
remain permitted.

The positive image requires a hardware CPL0 write #PF with error code 3
(P=1, W=1, U=0), exact CR2 and faulting RIP, and a frame on the separate
TSS IST1 stack. This fault path is terminal; it cannot return to the write.
The first negative control supplies a stale expected old PTE and requires
code 9 with no PTE mutation. The second first makes the *real HIA* downgrade,
then maliciously restores RW in the non-HIA observer and must successfully
write and read back a distinct value. Outcomes have disjoint debug-exit codes
and serial markers on PC/32 MiB and Q35/64 MiB.

The build audit compares native `.text` from the original HIA object,
symbol-renamed boot object and 64-bit/32-bit ELF images for all three tests.
The experiments do not make CR2, `INVLPG`, exception entry or GDT/IDT
privilege operations HIA-native; they do not implement concurrency,
remote TLB shootdown, safe physical frame reclamation, or Linux `mprotect`.
All 17 complete-kernel gates remain HOLD.
