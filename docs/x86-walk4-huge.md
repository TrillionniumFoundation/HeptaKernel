# Native HIA supplied-entry x86-64 2 MiB and 1 GiB leaf policy

`src/x86_walk4_huge.hepta` is **HIA Core v8 `selfhost_elf` source**,
compiled by the repository's locked self-hosting native compiler. It exports
`walk4_huge(va, pml4e, pdpte, pde, phys_bits, page_shift) -> u64`
with six SysV `u64` arguments. Only page_shift 21 (PDE large leaf) and 30
(PDPTE large leaf) are admitted. The 1 GiB profile never reads PDE.

On success, the returned 64-bit word has bit 63 set, bits 62/61/60 encode
effective write/user/execute permissions, and bits 0–51 are physical address
plus the virtual-address page offset. Zero means refusal. A zero physical
leaf base is legal. The HIA source, not an injected code blob, computes
these fields.

Checks include canonical 48-bit VA, MAXPHYADDR within 32–52, Present bits,
PML4E and nonleaf PDPTE page-size/global bits, nonzero in-range parent table
addresses, the correct large-leaf PS bit, high reserved bits 52–62, and
leaf-reserved bits 13 through (page_shift - 1). Bit 12 is large-page PAT,
and bit 8 in a **leaf** can be global. Effective permissions inherit
RW/U/S/NX from the traversed levels only. The caller must separately
qualify EFER.NXE=1, CPUID support for 1 GiB leaves, legal CR3 state,
MTRRs/PAT, and physical ownership.

This is supplied-entry translation policy rather than hardware table
walking: the caller chooses all entries and must prove that they were
read from appropriately owned, linked, quiescent physical pages. The
1 GiB PDE argument is deliberately ignored, because hardware does not
consult it. No hardware CR3 read/write, INVLPG, address-space switch,
SMP synchronization, TLB lifetime, user ABI or Linux syscall is claimed.

`make test-x86-walk4-huge` builds genuine HIA ELF objects using the pinned
compiler, checks `.text` identity after host ELF linking, compares
randomized and targeted native calls against an independent Python oracle,
and verifies that a deliberately dishonest HIA implementation is rejected.
The whole `make test` and GitHub Foundation CI include that target, and
retain the raw report and objects. Full 17-gate Linux acceptance remains
HOLD; all 422 syscall obligations remain unchanged.
