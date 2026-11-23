# Restricted native HIA x86 TLB shootdown acknowledgement snapshot

This candidate adds a **real Core v8 HIA source program** built with the unchanged
pinned selfhost_elf compiler. It verifies a bounded, caller-supplied per-CPU
acknowledgement ledger. Its only function has read and trap effects; **it does
not send IPIs, execute INVLPG, read CR3, issue memory barriers, authenticate
CPU state, perform an atomic operation, or authorize frame reclamation**.

The immutable little-endian request is exactly 48 + 32*N bytes, with six
u64 header words (expected CR3 physical root, canonical 4KiB virtual page,
nonzero invalidation epoch, online CPU mask, target CPU mask, N=1..64).
Each 32-byte row contains (CPU index 0..63, acknowledged epoch, claimed
CR3 root, claimed completion flags). Completion flags must be exactly 3,
meaning the **untrusted producer claims** both an invalidation and post-flush
ordering step. Rows must cover the target mask exactly once; targets must be
a nonempty subset of online CPUs. Root must be 4KiB aligned, nonzero, below
2^52; the page must be canonical in 48-bit mode and page aligned. The gate
does not assume 57-bit paging. A missing CPU (including bit 63), duplicated
CPU, stale epoch, different root or malformed flags fails closed.

Return values are 0=accepted snapshot, 1=invalid size/row count,
2=invalid header/profile, 3=duplicate/non-target/out-of-range row,
4=stale or incomplete claimed CPU acknowledgement, 5=missing target row.
All inputs remain immutable; the function has no mutable output.

The independent host byte-array oracle exercises sparse and dense masks,
bit 63, malformed lengths, duplicates, missing rows, stale epochs, CR3
mismatches and flag tampering. A compiled HIA always-accept substitution
must be detected. Two empty-PATH compiler replays must produce byte-identical
objects to the normal build. This is a **necessary data-preflight building
block only**. In particular, ledger data has no signed or hardware provenance,
epochs can race with late CPU or page-table mutations, and the code proves
neither actual remote TLB invalidation nor DMA/IOMMU coherence. Full 17-gate
Linux acceptance remains HOLD, 422 syscall rows remain unchanged.
