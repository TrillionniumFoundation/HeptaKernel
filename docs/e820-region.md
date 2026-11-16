# HIA E820 memory-region admission component

The complete Linux target still requires firmware discovery, rich memory-map
handling, reservations, multi-arena management, virtual memory and SMP.
`src/e820_region.hepta` implements **one separately testable native HIA
precondition**, not those missing systems. It is compiled by the pinned
upstream HIA self-hosting compiler into a freestanding ELF64 x86-64 object,
without C, Rust, libc, imported symbols or a host Linux syscall.

## Foreign ABI and contract

The entry `f0(request, request_bytes, reply, reply_bytes, state, state_bytes)`
uses the same three-buffer SysV caller convention as the allocator. The
request region is read-only; the reply must hold at least 16 bytes. The
unused `state` buffer is never read or written. The foreign caller **must**
provide valid, disjoint memory regions; no bare pointer provenance or guest
physical authenticity is established by the HIA program.

The request starts with three little-endian 64-bit words: `physical_base`,
`page_count`, `entry_count`, followed by exactly `entry_count` records each of
24 bytes: little-endian `e820_base:u64`, `e820_length:u64`, `type:u32`,
`extended_attributes:u32`. The entry count is at most 128. The caller must
supply a **canonicalized E820-style table**, including a valid attributes
word even if original firmware provided only the legacy 20-byte form. The
low bit of extended attributes marks whether the entry is enabled; a disabled
entry is ignored for coverage and exclusion. The caller is responsible for
obtaining the real firmware map, preserving its provenance and translating
its actual transport format correctly. A fabricated map does not prove RAM.

A candidate has 1..65,536 pages, a 4096-byte-aligned physical base, and an
exclusive end at most `2^52`. Every provided record must have nonzero length
and a representable exclusive end (`base + length` must not overflow u64).
**The whole table is validated**, including records that do not intersect the
candidate. A candidate is admitted only when the union of *enabled type-1*
records covers the **entire proposed arena**, without gaps, and no *enabled
non-type-1* record intersects any byte of it. Checks are independent of record
order. Native HIA uses bounded repeated scans instead of sorting. Each useful
pass strictly extends the covered prefix; at most 128 such passes can occur.
The map is not a fully normalized, ownership-tracked OS memory map and there
is no general OS-level reservation policy. In particular, kernel image, stack, firmware
handoff data and page-table regions can exist *inside* a type-1 RAM region:
the caller must separately reserve them before the allocator may use that
arena. The HIA check cannot establish that they are protected.

The return `u32` equals the first little-endian `u64` status in the reply;
the second word is `page_count` only on success and zero on other results.
Status 0 is admissible; 1 is short reply (no writes); 2 is malformed request
extent/count; 5 is no provably wholly usable arena; 6 is invalid geometry or
malformed entry. All returns leave the read buffer and state unchanged and
write no reply byte after the first 16. A status-0 result **is not a physical
memory allocation** and is not valid authorization to touch RAM absent
firmware provenance and all additional reservations.

## Verification and current gap

`make test-memory-map` compiles the HIA source, checks for undefined symbols,
links that exact object into a host test library, compares the loaded `.text`
section against the object's `.text` bytes, and runs an independently coded
Python oracle. Fixed cases include complete coverage, enabled reserved-region
overlap, disabled attributes, unsorted overlapping records, wraparound,
empty/short/malformed buffers, maximum entry count and physical bounds.
3,000 deterministic randomized cases and 640 shuffled fragmented/overlap/
gap/reservation cases exercise the same actual machine code.
An independently compiled HIA always-allow negative control returns false
success on a reserved overlap; the oracle rejects that result explicitly.
Failures are reported rather than being silently skipped. CI runs a separate
upstream HIA Core syntax/semantic verifier before compilation.

## Native HIA check of the actual QEMU loader handoff

`arch/x86_64/boot.S` now requires the real Multiboot v1 mmap flag and
reads every variable-length entry provided by the loader. The temporary
assembly bridge rejects zero/overlong/incomplete maps, more than 128 entries,
unknown row widths (only the standard 20-byte and extended 24-byte body
are accepted), wraparound, a map buffer overlapping the 4–8 MiB probe arena,
and a loader module list with nonzero module count. Legacy 20-byte rows have
no extended attributes: the bridge explicitly marks them enabled before
creating the 24-byte native HIA request. Extended rows keep their original
attribute bits. No records may be silently dropped.

The actual native HIA E820 object is linked alongside the native HIA allocator
with a **symbol-only** `f0` → `e820_f0` rename. Both ELF boot containers
are checked for byte-exact preservation of the HIA E820 `.text`. Before
the allocator accesses a page, the native HIA admission checker must
approve all 1,024 pages of the fixed 4–8 MiB arena. The QEMU test requires an
explicit `HEPTAKERNEL HIA E820 VERIFIED` marker on both positive boots
and deliberately broken kernel runs, proving those negative controls were
not rejected at an unrelated early-boot check.

**Still missing:** independent firmware authenticity beyond the loader,
UEFI and architecture-specific memory handoffs, arbitrary E820 extension
sizes, general memory discovery, full firmware/module/MMIO reservations,
ownership and multi-arena allocation, SMP locking, virtual memory and Linux
userspace compatibility. `boot.S` remains GNU assembly and the chosen arena
remains a test fixture; this is not a production memory safety guarantee.
The full Linux acceptance ledger remains HOLD.

## End-to-end reserved-page rejection negative controls

The QEMU suite builds a separate test-only boot object with
`HEPTAKERNEL_TEST_INJECT_RESERVED`. After copying all loader memory-map
records, it appends an enabled type-2 reserved row for the first physical
page at 4 MiB. No genuine entries are dropped. The normal boot object does
not have the test define. The genuine HIA E820 object must reject this map
on both PC and Q35 **before** printing its admission marker or probing any
physical page. A separately compiled, deliberately dishonest HIA E820 object
is also linked to the same injected boot observer. Its *false acceptance*
must be observed to show that this negative control discriminates a
functioning E820 gate from an always-allow implementation.

These are synthetic test inputs, not evidence of authenticated real firmware,
general reserved-memory ownership, or any production Linux subsystem.
