# HIA native single-owner 4KiB PTE revocation

`src/x86_pt_revoke.hepta` is genuine HIA Core v8 `selfhost_elf` source, emitted as x86-64 native machine code with no embedded host assembler or Linux syscall. Its ABI is `fn x86_pt_revoke(readbuf, mutbuf, mutbuf)`: an exactly 32-byte little-endian request with four u64 words `slot, expected_old, new_value, caps`; reply at least 16 bytes; and a caller-owned 4096-byte mutable page-table buffer.

The operation requires `new_value==0`, `expected_old.Present==1`, an in-bounds leaf slot and a valid capability profile (32–52 physical bits), then re-reads and matches the *entire old entry*. Under exclusive-owner quiescence it clears the selected eight bytes. Success returns status 0 and new value 0. Refusals leave the entire table unchanged. Status conventions mirror `src/x86_pt_commit.hepta`: 1 short reply, 2 malformed request, 4 wrong page size, 6 invalid proposed revocation or index, 8 invalid caps, 9 stale expected old.

The independent `tests/test_x86_pt_revoke.py` oracle exercises deterministic random state, page-boundary slots, malformed sizes/caps and a 320-case revoke-then-stale-replay campaign. The negative control is *also* compiled from genuine HIA source and intentionally returns success without clearing the entry.

This is **only a quiescent single-owner table operation**. Writes are bytewise, not an atomic 64-bit compare-exchange; neither page-table provenance/ownership nor TLB invalidation, remote shootdown, hardware page-fault behavior, physical frame reclamation or Linux unmap syscalls are established. No complete Linux acceptance gate is closed.
