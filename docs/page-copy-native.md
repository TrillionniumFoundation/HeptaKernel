# Native HIA 4KiB page copy (COW prerequisite)

`src/page_copy.hepta` uses the locked HIA Core v8 `buffer.copy_range`
opcode. The fixed `selfhost_elf` emits a freestanding native x86-64 ELF
object, with no host syscalls, embedded machine bytes, C or assembly
implementation. This is an actual data-movement primitive, not a translation
of Linux `copy_page`/COW fault handling yet.

The three-argument public ABI is
`f0(source:readbuf, receipt:mutbuf, destination:mutbuf) -> u32`.
The source and destination must each be exactly 4096 bytes and the receipt
exactly 16 bytes. Status 1 rejects the source, 2 the receipt and 3 the
destination; all rejected shapes must leave all buffers unchanged.
Status 0 copies the entire source into destination, leaving source unchanged,
and publishes the two little-endian words `(0, 4096)` in the receipt.

The test independently compares whole source, output, receipt and canaries
for varied pages, malformed capability lengths and a no-copy dishonest HIA
control. A separate OS `mprotect` experiment makes the source page
read-only and both neighboring pages of source and destination inaccessible.
The native object must copy the entire page correctly without writing to the
source, crossing an inaccessible neighbor, or accepting an overlong source.

**Security and Linux scope:** This requires disjoint source/destination
capabilities and authenticated PMM ownership *from its caller*; raw C ABI
pointers are not themselves physical capabilities. It does not implement
page-fault handling, copy-on-write policy, virtual memory aliases, TLB
shootdown, race freedom, dirty-bit protocol, DMA/IOMMU protection or a
general-purpose Linux page copier. The 17 complete acceptance gates and
422 syscall obligations remain HOLD. QEMU physical-source readback is a
separate future test, not implied by the host-native oracle.

## Isolated QEMU actual physical page copy

`make test-page-copy-hw` now builds the exact pinned `page_copy.hepta`
selfhost ELF object and renames only its exported symbol for boot linking.
An independent `.text` byte comparison binds original and linked objects.

The clearly **non-HIA** QEMU observer uses the real Multiboot E820
handoff, reservation admission, native HIA two-zone PMM allocator and
owner-state binding. It prepares two disjoint cross-zone pairs:
`0x402000 -> 0x601000`, `0x403000 -> 0x602000`.
For each pair the observer populates the entire source with a distinct
incrementing eight-byte sequence and destination with unrelated nonzero
bytes. The genuine HIA `buffer.copy_range` native object copies 4096
physical bytes. An independent readback rederives the full 4096-byte
expected sequence for **both source and destination**, instead of accepting
only a status or preseeded success receipt. PC (32 MiB) and Q35 (64 MiB)
run under QEMU TCG.

Three malicious controls per machine must each fail with exit 35:
an independently compiled HIA routine returning success without copying;
post-copy modification of destination physical RAM; and post-copy
modification of source physical RAM. Every failure must suppress the
positive marker; the test records binary SHA-256, command, full serial
output, return code and timeout distinction in
`build/page-copy-hardware-report.json`. Both positive tests must exit 33.

**Boundary:** The physical page addresses, PMM coordination, source
seeding and oracle readback are handled by the non-HIA test bridge.
The HIA primitive does not prove the ABI pointers are authenticated PMM
capabilities, that physical mapping remains stable across concurrency or
DMA, or that it implements COW faults, page-table commit, cache/TLB
shootdown or Linux copy_page semantics. All 17 full-target gates and 422
syscall rows remain unchanged and HOLD.
