# ACPI 3.x E820 nonvolatile-memory admission policy

The HIA E820 region gate (`src/e820_region.hepta`) is a *temporary,
fail-closed* admission check for physical memory supplied by the current
Multiboot loader. It does **not** discover physical RAM or qualify a Linux
persistent-memory driver.

Each canonical 24-byte record contains `base:u64`, `length:u64`,
`type:u32` and `extended_attributes:u32`. ACPI E820 extended attribute
bit 0 marks a record enabled; bit 1 marks the range nonvolatile.

The requested region is admitted only if the union of **enabled,
type-1, volatile** ranges covers all requested bytes and no enabled
non-type-1 or nonvolatile range overlaps it. An enabled type-1 record with
the nonvolatile bit set is treated as an exclusion, **even if another
volatile type-1 record overlaps it**. Disabled records do not supply
coverage or exclusions. Nonzero lengths, non-overflowing extents and the
bounded 52-bit requested physical address window are still mandatory.

This conservative policy deliberately avoids repurposing persistent data
as volatile kernel storage before persistent-memory initialization,
ownership and flush semantics are implemented. It is not a claim that
every Linux E820 or DAX/pmem policy has been implemented.

The native independent sorted-interval oracle in
`tests/test_e820_region.py` separately enforces this rule. Cases cover
persistent-only ranges, overlapping conflicting RAM descriptions,
one-byte conflicts, disabled records, unknown attribute bits, fragmented
volatile coverage and fixed-seed random cases. The boot bridge still
requires separate work for firmware authenticity, loader reservations,
multiple zones, and architecture-native HIA privilege support.
