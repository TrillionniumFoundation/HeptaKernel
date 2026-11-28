# Native E820 candidate discovery

The read-only HIA primitive in `src/e820_find_arena.hepta` returns the
lowest aligned contiguous candidate from a **supplied snapshot**. Unlike
`e820_region`, which checks a caller's already selected address, this
primitive discovers an address inside an explicit search window.

## Native ABI

The pinned native compiler emits an x86-64 SysV `f0` entry. It takes a
request buffer, a reply buffer, and an unused buffer, each a pointer
followed by a byte length. As with the existing kernel ABI, the caller
must provide valid, non-overlapping buffers and keep the request stable.
The implementation never mutates the request or touches the unused buffer.

The request is little-endian. Five consecutive u64 fields precede the
records: inclusive window start, exclusive window end, number of 4096-byte
pages, alignment in bytes, and record count. Window endpoints are page
aligned, with a nonzero start and end no greater than 2^52. The requested
page count is 1–65,536; alignment is a power of two in [4096, 2^52].
The request must contain exactly 0–128 records of 24 bytes each:
`u64 base, u64 length, u32 E820 type, u32 extended attributes`. Every
record, even a disabled one, must have nonzero length and a nonwrapping
exclusive end. The caller may represent reservations as extra enabled
type-2 records.

A reply buffer shorter than 16 bytes produces return code 1 and no
write. Otherwise the first two u64 reply fields are status and selected
base; the function returns the same status as u32. Status 0 means a
candidate was found, 5 means the valid snapshot had no fit, and 6
means malformed request. Unsuccessful replies contain base zero. Bytes
after the first 16 are untouched.

## Search and invariants

An address is eligible if at least one enabled, volatile type-1
record covers it and no enabled record of any conflicting type or
with the nonvolatile attribute covers it. Adjacent eligible fragments
form one interval; an excluded byte breaks contiguity. Unknown attribute
bits are ignored, matching `e820_region`.

After validating every record, the implementation starts at the window's
lower bound. At each step it scans the rows and finds the smallest
enabled start/end boundary strictly greater than the cursor, clipped to
the window end. Eligibility is constant on the resulting half-open
segment. It retains the start of consecutive eligible segments and
tries the aligned start of that run after each extension. Because the
cursor moves upward, the first fit is the lowest possible address.
A segment advances to a distinct record endpoint or the end of the
window, so there are at most 257 segment scans, independent of address
distance. The 52-bit window and power-of-two alignment bounds also keep
round-up and extent addition below u64 capacity.

## Verification and limits

```sh
python3 -B tests/test_e820_find_arena.py /path/to/pinned-native-compiler
```

The test checks the compiler pin, two byte-identical empty-PATH native
builds, and no unresolved object symbols. It links the genuine object
without an implementation fallback and calls its native ABI against a
separate interval-merge and aligned-enumeration oracle. The fixed cases
cover fragmented RAM, overlaps, one-byte reservations, invalid framing,
the 52-bit ceiling, the 128-record capacity and a machine-sized empty
gap. Seeded maps are checked in both record orders, including bounds and
buffer canaries.

This does not authenticate a firmware map, discover reservations on the
host, claim any page, initialize a PMM, or change the boot path. The
caller must still verify provenance and reserve or claim the returned
range before use. No Linux acceptance gate or syscall is credited.
