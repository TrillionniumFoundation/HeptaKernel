# Native HIA protected-interval exclusion precondition

`src/reservation_gate.hepta` is a true HIA Core v8 selfhost_elf program
compiled directly to x86-64. It checks that a caller-declared physical
allocation suffix is disjoint from **every** supplied protected byte interval.
This narrows an important gap between E820 type-1 RAM admission and
actual allocator ownership: kernel image, page tables, loader payloads and
other objects can occupy otherwise usable E820 type-1 RAM. Those ranges
must not be released into PMM free pages.

The ABI is the ordinary `f0(readbuf,mutbuf,mutbuf)` pointer/length triple.
The request is exactly four little-endian u64 header words
`(base, pages, reserved_prefix_pages, interval_count)`, followed by
`interval_count` little-endian `(physical_start, byte_length)` u64 pairs.
There are at most 128 intervals. Base must be page-aligned, pages in
1..65,536 and fit below 2^52, prefix cannot exceed pages. Every span
must be nonempty and must have a non-overflowing exclusive end. Unsorted
and overlapping spans are valid; zero-length and overflowing spans are
**invalid even if disjoint from the arena**.

The gate rejects any span intersecting
`[base + 4096*reserved_prefix_pages, base + 4096*pages)`. The reserved
prefix itself is excluded from allocation and may intersect spans. The
response is two u64 words: (0, pages-prefix) on acceptance; (5, 0) for
a protected collision; (6, 0) for invalid geometry/intervals;
(2, 0) for wrong framing/count. Reply shorter than 16 bytes returns
status 1 with no writes. The request/unused capabilities are immutable;
the gate **does not allocate**, mutate any PMM bitmap or prove provenance.
The foreign caller must provide valid disjoint buffers.

`make test-reservations` runs independent Python integer-interval oracle
comparisons against the **actual native HIA machine code**, including
deterministic generated rows, malformed and overlapping reservations,
all-prefix and near-limit arenas, short replies, untouched guard bytes,
and an independently compiled deliberately dishonest HIA allow-all
negative control. `make record-build` also recompiles source with an
empty PATH and binds its exact ELF .text to the loaded test library.

**HOLD:** This checker receives caller-provided exclusions; it does not
discover or authenticate the live firmware/Multiboot/UEFI reservation
set. It is not integrated into the QEMU boot allocation path, whose
transport still uses GNU assembly. No runtime owner registry, page
tables, SMP lock, atomics, DMA protections or general Linux VM is implied.
Full Linux rewrite gates and syscall inventory are unchanged.
