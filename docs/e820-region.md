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
candidate. A candidate is admitted only when at least one *enabled type-1*
record contains the **entire proposed arena** and no *enabled non-type-1*
record intersects any byte of it. Checks are independent of record order.

This conservative rule deliberately rejects some legitimate RAM unions that
are covered only by adjacent type-1 entries; it has no false-positive grant
from joining fragments, and does not yet provide a fully normalized map or
an OS-level reservation policy. In particular, kernel image, stack, firmware
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
3,000 deterministic randomized cases exercise the same actual machine code.
An independently compiled HIA always-allow negative control returns false
success on a reserved overlap; the oracle rejects that result explicitly.
Failures are reported rather than being silently skipped. CI runs a separate
upstream HIA Core syntax/semantic verifier before compilation.

**Not yet demonstrated:** obtaining E820 from a real QEMU Multiboot firmware
handoff, mapping canonicalization, 24-byte attribute provenance, a multi-arena
physical allocator, page-table/device reservations, QEMU execution of this
component, SMP concurrency and Linux userspace ABI. The existing `boot.S`
fixture still passes a hardcoded arena directly to the allocator. No
full-target ledger gate is closed by this isolated capability.
