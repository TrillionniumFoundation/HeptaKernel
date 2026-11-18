# Native HIA 4KiB user-to-supervisor PTE downgrade

`src/x86_pt_user_revoke.hepta` is genuine `hia-asm.v1 hepta.hia.program.v8 selfhost_elf` source, compiled with the locked HIA Core v8 native self-hosting compiler. It is a restricted exclusive-owner page-table leaf operation, not a Linux syscall or a host-side machine-code stub.

## ABI and contract

The function accepts exactly 32 request bytes (`<4Q` little-endian: slot, expected_old, new, capabilities), at least 16 reply bytes, and exactly 4096 mutable bytes containing 512 PTEs. Capabilities use bits 0–7 for physical-address width (32..52), bit 8 for EFER.NXE, and bit 9 for CR4.PGE. All higher capability bits are rejected.

An accepted request has slot 0..511, Present=1, U/S=1, a physically in-range 4KiB leaf, no forbidden high reserved bits, no simultaneous user/global bit combination, and a new entry *exactly* equal to expected_old with U/S cleared. NX requires NXE, and Global requires PGE. A complete 64-bit expected-old comparison is performed before the single-owner bytewise store. All other bits are preserved, including RW, NX, A/D, cache attributes, PAT and physical frame. The 16-byte reply stores zero-extended status and updated PTE on success.

Status: 1 short reply, 2 malformed request, 4 wrong table size, 6 invalid transition/slot, 8 invalid capabilities, 9 stale old value, and 0 success. All non-success paths leave the page unchanged. The independent Python oracle checks sentinel guards and all 4096 bytes after the call, and a second malicious HIA implementation always returning success must be rejected.

## Limits

This is **not** a linearizable PTE CAS: it updates 8 bytes sequentially under the exclusive-owner/quiescence assumption. It has no native HIA CR3, INVLPG, shootdown, authority proof or independent CPL3/QEMU user-access fault validation. It does not implement Linux `mprotect`, user-memory isolation, page freeing or memory ownership. These remain open in the 17-gate acceptance ledger.

The Foundation pipeline checks Core syntax/effects, full native differential behavior, malicious control, empty-PATH recompilation, and object/shared-image `.text` identity. The pinned Linux and HIA revisions, all 422 syscall obligations and HOLD acceptance outcome remain unchanged.
