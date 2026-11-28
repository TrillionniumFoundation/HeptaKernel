# HIA frame allocator

The authoritative implementation is `src/kernel.hepta`, using the real upstream
`hia-asm.v1 hepta.hia.program.v8 selfhost_elf` profile. It contains 17 functions,
typed control flow, checked borrowed byte access, and no owned allocation or
external function call. The native compiler emits an ELF64 object with the
legacy exported symbol `f0`. Its `.text` is unchanged when linked into either
the native test library or the QEMU guest.

## Caller contract

The x86-64 SysV entry is equivalent to:

```c
uint32_t f0(const void *request, uint64_t request_bytes,
            void *reply, uint64_t reply_bytes,
            void *state, uint64_t state_bytes);
```

This notation describes the foreign ABI; it is not the implementation language.
The caller must provide valid, pairwise disjoint regions of the stated extent.
The raw ABI does not validate pointer provenance or overlapping physical memory.
HIA's internal capability checks cannot establish those facts about a foreign
caller. The boot observer and native tests own and separate all three regions.

The state region is trusted, private, single-owner kernel memory. Calls must be
serialized. On each non-init operation the HIA state validator reads each
active storage byte once, checks the reserved prefix and unused tail with
separate masks, then counts zero bits within the valid mask using portable
integer operations. It reconciles the exact free-frame counter and requires
zero in every reserved header byte at offsets 40–63. This contributes
O(ceil(pages/8)) byte iterations to each operation; it detects
inconsistent bookkeeping but does not authenticate caller-owned memory or
detect a coherent malicious rewrite of an entire private state. A future Linux
allocator requires protected metadata, concurrency and scalable structures. This component has no interrupt/SMP synchronization and performs no
implicit allocation, system call, global access or runtime initialization.

## Request and response

Requests contain exactly four little-endian u64 words (32 bytes). Replies use
their first two little-endian u64 words (16 bytes): `(status, value)`. The u32
function return must equal the reply status. Every failure with a sufficiently
large reply sets `value` to zero. Successful physical address zero is valid;
the status word distinguishes it from a failure.

| Opcode | Arguments `(a,b,c)` | Success value |
| --- | --- | --- |
| 0 INIT | page count, physical base, reserved prefix pages | Free frames |
| 1 ALLOC | power-of-two alignment in pages, 0, 0 | Lowest free aligned physical address |
| 2 FREE | allocated physical address, 0, 0 | 0 |
| 3 FREE_COUNT | 0, 0, 0 | Free frames |
| 4 ALLOC_RUN | contiguous page count, power-of-two alignment in pages, 0 | Lowest physically aligned first frame of a contiguous run |
| 5 FREE_RUN | starting physical address, contiguous page count, 0 | 0 (atomic release) |
| 6 CLAIM_RUN | exact physical start address, contiguous page count, 0 | 0 (atomic claim) |
| 7 QUERY_FREE_RUN | exact physical start address, contiguous page count, 0 | Requested count if every frame is free (read-only) |
| 8 QUERY_FIRST_FREE_RUN | contiguous page count, power-of-two alignment in pages, 0 | Lowest physically aligned, currently free contiguous-run start (read-only) |

Each page is 4096 bytes. The arena has 1 through 65,536 pages, a 4096-aligned
base, and an exclusive upper bound at most `2^52`. The permanently reserved
prefix can range from zero through the entire arena. The caller is responsible
for proving that the chosen physical range is usable RAM and does not overlap
kernel, firmware or device storage. INIT reinitializes bookkeeping; the caller
must not use it while previously allocated frames remain live.

Alignment is applied to the physical page number, including the base. For
example, base `0x503000` and an 8-page alignment yields `0x508000`, not an
address merely aligned relative to the arena. Any representable nonzero
power-of-two page alignment is accepted; absence of a matching frame returns
NO_MEMORY. Arithmetic validation precedes mutation. Search is first-fit and
linear in the page count; no Linux buddy-allocation behavior is claimed.

ALLOC_RUN walks the existing bitmap exactly once after validating the state,
finds a contiguous run of the requested nonzero number of pages, and commits
all its bits and free-count change only after the entire run has been found.
The first physical page of the run must satisfy the power-of-two page
alignment. An insufficient total count or fragmented capacity returns
NO_MEMORY with no state mutation. FREE_RUN validates the complete requested run, including aligned start,
nonzero length, in-arena exclusive end, reserved prefix and every existing
allocation bit, before clearing any bits. Any already-free member returns
DOUBLE_FREE without partial release; malformed range returns INVALID_ARGUMENT
and a protected prefix returns RESERVED. A successful release increases the
free count by the full run length. FREE remains available for individual
pages. CLAIM_RUN performs exact-address placement (without searching another
candidate). It validates geometry, reserved prefix, and the complete requested
bitmap run before modifying any state. An occupied member returns NO_MEMORY,
without partial claim. Successful CLAIM_RUN returns value zero, even for
physical address zero; status distinguishes success. This primitive does not
discover usable firmware RAM or protect arbitrary device ranges.

QUERY_FREE_RUN is an exact-range read-only availability query using the same
argument, geometry, reserved-prefix and complete-bitmap checks as CLAIM_RUN.
It returns NO_MEMORY when any requested frame is in use and never modifies
the allocator state. It is not an atomic claim, and callers must use CLAIM_RUN
to reserve pages; probing is safe only under the stated single-owner contract.

QUERY_FIRST_FREE_RUN uses the same bounded state-integrity validation,
live bitmap first-fit scan, physical alignment and reserved-prefix rules as
ALLOC_RUN, but publishes the address without writing the bitmap or free count.
It can support speculative cross-zone selection under single-owner
serialization; a caller must still use CLAIM_RUN to reserve that address and
handle a changed occupancy result. This is not an atomic multi-zone allocation
or SMP-safe read-modify-write transaction.

No run-ownership tracking, zones, SMP locking or buddy merging is yet
implemented. The caller must prevent stale aliases and coordinate ownership.

| Status | Name | Meaning |
| ---: | --- | --- |
| 0 | OK | Operation completed |
| 1 | REPLY_TOO_SMALL | Reply has fewer than 16 bytes; no reply write |
| 2 | BAD_REQUEST | Request size is not exactly 32 bytes |
| 3 | UNKNOWN_OP | Opcode is not implemented in this component protocol |
| 4 | BAD_STATE | Missing/invalid state, invalid header or insufficient metadata capacity |
| 5 | NO_MEMORY | No free frame meets the requested alignment |
| 6 | INVALID_ARGUMENT | Invalid geometry, unused argument, alignment or free address |
| 7 | DOUBLE_FREE | The addressed dynamic frame is already free |
| 8 | RESERVED | The addressed frame belongs to the permanent prefix |

Validation order is reply length, request length, opcode, parameter-only
constraints, then state and state-dependent constraints. Thus an invalid ALLOC
alignment returns INVALID_ARGUMENT even on an uninitialized state. FREE checks
range, reserved status, allocation state, and the free-count invariant in that
order after validating its arguments and header. All returned failures leave
the state bytes unchanged; successful FREE_COUNT is also read-only.

## State representation and invariants

| Offset | Representation |
| ---: | --- |
| 0 | Magic `0x314d4d504b484941` |
| 8 | Page count |
| 16 | Physical base |
| 24 | Permanently reserved prefix length |
| 32 | Current free-frame count |
| 40–63 | Zero, reserved |
| 64 onward | `ceil(page_count/8)` bitmap bytes, least-significant bit first |

A set bit denotes a reserved or allocated page. Reserved prefix bits are set
during initialization and cannot be cleared by FREE. Tail bits beyond the
arena remain zero and are never candidates. Bytes after the required metadata
extent remain unchanged. INIT clears only the required extent and publishes
the magic after all geometry/capacity checks and initialization writes.

For a valid state, `free_count = pages - reserved - allocated_dynamic_pages`.
ALLOC sets exactly one eligible bit and decrements the count; FREE clears one
dynamic allocated bit and increments it. Parameter and header checks bound
all bitmap accesses. State validation checks ranges and capacity, rejects nonzero reserved header
bytes before touching mutable allocation metadata, then rescans the active
bitmap on every non-init call (one iteration per storage byte). The state is not an authenticated
storage format and arbitrary memory corruption is not guaranteed to be detected.

## Verification

`tests/test_native.py` uses an independently written set of physical addresses
as the oracle. It compares every operation and state transition, exercises
failed-operation immutability, preserved bytes, exact capacities, partial bitmap
bytes, reserved prefixes, physical alignment, zero-address success and maximum
geometry. The actual loaded library is hashed and its `.text` compared with
the HIA object before attaching the test evidence. The bitmap audit alone is
also checked against an exhaustive set oracle for all 256 stored octets, all
lengths from one to eight pages, every legal reserved prefix, and every
in-range claimed free count. Each query must preserve the entire state.

`tests/test_guard_pages.py` places capabilities against inaccessible pages and
makes the request page read-only. This checks real process memory protection,
including zero-length capabilities. It remains a host-side component test.

The boot observer independently compares each request's return and both reply
words to fixed expected data. For every successful allocation it validates the
physical bounds and writes/reads distinct patterns at the first and last word
of the actual frame. Exceptions and corrupt results exit through a separate
failure path. An always-success HIA stub and an out-of-bounds HIA program must
both fail explicitly; timeouts and triple faults do not count as correct
diagnostics. The observer itself is GNU assembly and remains outside HIA.
