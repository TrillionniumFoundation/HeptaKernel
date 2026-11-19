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
