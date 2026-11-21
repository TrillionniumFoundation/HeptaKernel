# HIA native offline two-leaf shadow page construction

`src/x86_pt_pair_shadow.hepta` is genuine Core v8 HIA source compiled by
the pinned `selfhost_elf` backend. It constructs a **separate, unpublished**
4 KiB leaf table instead of sequentially modifying two leaves of the current
hardware-visible table.

The 4160-byte read-only payload contains the same 64-byte request layout as
`x86_pt_pair_commit.hepta`, followed by an exact 4096-byte source page.
The output is a **distinct** 4096-byte mutable shadow page and the receipt
is exactly 16 bytes. The source and output buffers must not overlap; this
is a caller ownership precondition and is **not** authenticated by the current
HIA native ABI. The request holds slots A/B, expected old A/B, candidate
new A/B, CPU capabilities and zero reserved word. Slots must be distinct
and under 512. Replacement leaves must be present, have distinct nonzero
physical frames, meet the declared width, have no reserved bits, obey
W^X and require NXE/PGE as appropriate.

Before writing any output byte, native HIA checks the complete shape,
capabilities and both expected-old PTEs **inside the immutable input
snapshot**. On rejection (statuses 1–7 matching the paired live writer),
the shadow and receipt stay unchanged. Once admitted, the HIA machine
code copies all 4096 source bytes to the unpublished shadow, replaces two
entries, and records both new entries in the receipt.

The independent byte oracle checks 1700+ deterministic valid/invalid cases,
two stale-old variants, reversed slots, reserved bits, W^X, frame alias,
input immutability, every unchanged PTE, canaries, and a separately
HIA-compiled malicious always-success no-op. Both empty-PATH rebuilds
must match the original native object and the shared-library .text.

This provides a **candidate for single-entry parent-pointer publication**
with no two-leaf modification of an active table. It is not itself a
trusted page-table publish transaction: no live CR3/PDE/PTE update,
hardware TLB invalidation, ownership authority, DMA/SMP exclusion,
alias-proof source capability, cache coherence, or failure-safe parent
replacement is implemented here. The old snapshot could be stale or
mutated during copying, and no source-page pinning/recovery protocol is
provided. QEMU hardware publication and fault controls are still pending.
The fixed Linux 7.3.4 scope, all 17 acceptance gates and 422 x86-64
syscall rows remain HOLD.

## Isolated QEMU single-parent publication experiment

`make test-pt-shadow-hw` links the unchanged pinned HIA Core v8 native
`x86_pt_pair_shadow.hepta` machine code into two isolated QEMU configurations
(PC 32 MiB and Q35 64 MiB). After HIA E820 and reservation admission,
the explicitly non-HIA observer takes an all-zero 4 KiB source-table snapshot
and constructs a disjoint, page-aligned shadow in guest RAM. The observer
checks all 512 output words and the 16-byte receipt before a **single**
parent PDE store and CR3 reload. Real CPU reads must observe the opposite
physical data frames on both 4 KiB virtual pages.

Stale second-old, malicious HIA-compiled success/no-op, and post-build
shadow-byte corruption have separate exact readbacks and must refuse without
publishing a parent pointer. Every hardware run records the original HIA
source/object hashes, linked text identity, complete guest output, image
SHA-256 and exit status. The unchanged source snapshot, inactive original
table and physical frame contents are checked before publication.

This removes the specific hazard of sequentially modifying two *active*
PTEs in this single-CPU test. It does not make publication atomic with
respect to SMP or asynchronous faults, nor authenticate table-page
ownership, source-page stability under DMA, TLB shootdown, HIA CR3
instructions, or a Linux address-space lifecycle. No other acceptance
gate or x86-64 syscall row is closed.
