# HIA native single-owner 4KiB PTE revocation

`src/x86_pt_revoke.hepta` is genuine HIA Core v8 `selfhost_elf` source, emitted as x86-64 native machine code with no embedded host assembler or Linux syscall. Its ABI is `fn x86_pt_revoke(readbuf, mutbuf, mutbuf)`: an exactly 32-byte little-endian request with four u64 words `slot, expected_old, new_value, caps`; reply at least 16 bytes; and a caller-owned 4096-byte mutable page-table buffer.

The operation requires `new_value==0`, `expected_old.Present==1`, an in-bounds leaf slot and a valid capability profile (32–52 physical bits), then re-reads and matches the *entire old entry*. Under exclusive-owner quiescence it clears the selected eight bytes. Success returns status 0 and new value 0. Refusals leave the entire table unchanged. Status conventions mirror `src/x86_pt_commit.hepta`: 1 short reply, 2 malformed request, 4 wrong page size, 6 invalid proposed revocation or index, 8 invalid caps, 9 stale expected old.

The independent `tests/test_x86_pt_revoke.py` oracle exercises deterministic random state, page-boundary slots, malformed sizes/caps and a 320-case revoke-then-stale-replay campaign. The negative control is *also* compiled from genuine HIA source and intentionally returns success without clearing the entry.

This is **only a quiescent single-owner table operation**. Writes are bytewise, not an atomic 64-bit compare-exchange; neither page-table provenance/ownership nor TLB invalidation, remote shootdown, hardware page-fault behavior, physical frame reclamation or Linux unmap syscalls are established. No complete Linux acceptance gate is closed.

## Isolated PC/Q35 live hardware revocation

The native HIA `x86_pt_revoke` runs on the actual 4 MiB leaf page table in
an isolated Multiboot/QEMU observer. A supervisor read warms the mapping;
native HIA checks the exact old 64-bit PTE and clears it; the explicitly
non-HIA bridge executes `invlpg` and attempts another read. The CPU must
deliver a not-present supervisor read #PF with error code zero, CR2=0x400000
and the exact instruction RIP on the HIA-installed IST1 gate. An independent
stale-old control must refuse without changing the entry. A second adversarial
test bridge restores the old PTE, invalidates its translation, and must read
the original value instead of falsely reporting a fault. Both pc/32MiB and
q35/64MiB run all three variants and retain SHA-256 inputs and QEMU outputs.

This is a narrow single-CPU hardware observation. Privileged INVLPG, CR2
reading and exception entry remain non-HIA, and this does **not** prove
concurrent atomic updates, ownership, SMP shootdown, Linux munmap semantics
or safe physical-frame reuse.
