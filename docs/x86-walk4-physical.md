# Native HIA CR3-rooted physical-window walker

`src/x86_walk4_physical.hepta` is a real Core v8 `selfhost_elf` program
compiled by the unchanged pinned native HIA compiler. Its entry is
`f0(request:readbuf, reply:mutbuf, pages:mutbuf)`, with a three-slice
native HIA buffer ABI. No source is rewritten as GNU assembly and no
opaque instruction bytes are linked into the target.

The request is exactly four little-endian `u64` words
`{virtual_address, physical_address_bits, cr3_snapshot, physical_window_base}`.
The `pages` slice is exactly 16,384 bytes representing four contiguous
4 KiB **caller-supplied copied physical pages** beginning at
`physical_window_base`. The CR3 root and all successor L4/L3/L2
physical addresses are followed *by their actual entry address* into
the window. There are no separately trusted L3, L2 or L1 addresses,
no fixed table level-to-buffer-order convention, and no dereference
outside the validated window. Page table pages can occur in any order.

The 16-byte reply is `{status:u64, encoded_translation:u64}`;
the function return value is the 32-bit status. Status codes are
0 (admitted), 1 (reply too short; untouched), 2 (wrong request size),
3 (wrong page window size), 4 (bad physical geometry or CR3 metadata),
5 (a traversed physical page pointer falls outside this window),
and 6 (non-present/invalid/nonconforming entry or translation).
On refusal the translation is zero. The upper bits of an admitted
translation encode the effective W/U/X permission flags and a success
bit using the existing HIA page-policy helpers, not a raw physical
address alone. The first encountered 1 GiB or 2 MiB PS leaf
terminates the walk without reading irrelevant lower levels.

The metadata admits 32–52 physical address bits and 48-bit canonical
virtual addresses, and allows CR3.PWT/PCD but rejects PCID/unsupported
CR3 fields. Page-table address validity and present/PS/reserved bits
are checked before any child lookup. The fixed 16 KiB window must fit
inside the declared physical width. The HIA intrinsic bounds rules
enforce that no table bytes are accessed beyond the admitted slice.

`make test-x86-walk4-physical` invokes a separate Python oracle which
reads physical pages through its own offset calculations. It permutes
physical page order, injects malformed parents and addresses, mutates
entries, checks read-only inputs and guard sentinels, compares ELF object
and shared `.text` bytes, and rejects a separately compiled dishonest
native HIA always-admit implementation. The exact-candidate result and
failures are part of Foundation CI.

**Scope limit:** the physical window is provided by a caller and is
not independently authenticated against RAM, the CPU's actual CR3, a
stable physical memory map or a page ownership structure. There is
no privilege instruction, MMIO, page-fault handler, TLB shootdown,
SMP synchronization or IOMMU behavior in this component. The
non-HIA `boot.S` bridge remains and all 17 Linux acceptance gates
and 422 x86_64 syscall rows stay open. `make full-acceptance` must
still return HOLD (exit code 2).
