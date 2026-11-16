# HIA E820 candidate region admission

The real HIA Core v8 native source is `src/e820_region.hepta`, compiled by the pinned
selfhost_elf toolchain to x86-64 ELF64, exposing `f0`. This component only
**tests a caller-supplied memory-map snapshot**; it does not acquire firmware
records, authenticate their provenance, or reserve the kernel image and page
tables. The boot bridge does not call it yet.

## Wire and result

The request contains little-endian 64-bit `candidate_base`, `candidate_pages`,
`entry_count`, then exactly that many 24-byte map records. Each record is
`base:u64, length:u64, type:u32, ext_attrs:u32`. The reply contains two
little-endian 64-bit words `(status,value)`; the native return is the status.
Status 0 means the **entire** candidate is admitted and value is its page count;
5 means not demonstrated safe (no complete coverage, hole, disabled interval or
enabled exclusion); 6 means malformed geometry, zero/overflow record; 2 means
invalid exact request size or entry count; 1 means reply shorter than 16 bytes.
The state buffer is ignored and must remain unchanged.

Candidate bases are 4-KiB aligned, page counts are 1–65,536 and the end is at
most 2^52. Entry count is 0–128; the implementation checks all entry ranges
for overflow before accepting anything. Entry extended-attribute bit 0 must
be set for an entry to be active. Active `type == 1` RAM entries may cover
the candidate through a union of adjacent/overlapping ranges **regardless of
input order**. Any active non-RAM entry that overlaps the candidate rejects
admission, even if RAM coverage is otherwise complete. Disabled records do
not grant RAM coverage or exclude it. These rules are deliberately conservative
for ambiguous overlapping firmware maps.

The HIA implementation first scans all entries and checks exclusion, malformed
ranges, and any single full-covering entry. If a single entry does not cover the
candidate, it grows a cursor by repeatedly scanning unsorted usable entries
whose starts are at or before the cursor. Each successful round strictly
increases the cursor; at most 128 progress rounds are possible. The worst-case
time is O(entry_count^2) with entry_count <= 128 and bounded input. This
algorithm does not sort or allocate memory; independent Python tests instead
sort and coalesce usable intervals before comparison.

## Evidence and limits

`make test-memory-map` compares the actual native HIA object against the
independent oracle, checks reply bounds and read-only request/state behavior,
and rejects a deliberately unsafe HIA allow-all negative control. The HIA
object's `.text` must match the loaded host test library's text.

The map must already have correct provenance and attribute semantics. In
particular, Multiboot, legacy E820 and UEFI descriptors are **not all the same
wire format**: the caller must explicitly convert them and preserve every
usable and reserved region without silently dropping entries. The 128-row
limit is a fail-closed capacity limit, not a guarantee firmware maps fit.
This component is not a physical-memory allocator or a complete safety proof.
The persistent Linux acceptance status remains HOLD.
