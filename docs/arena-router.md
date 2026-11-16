# Native HIA multi-arena ownership router (bounded component)

The authoritative source is `src/arena_router.hepta`. It is written in
`hia-asm.v1 hepta.hia.program.v8 selfhost_elf` and compiled directly by the
pinned upstream HIA native compiler. It is a pure, read-only selection and
descriptor-validation component, not a memory allocator, E820 discovery tool,
Linux zone implementation, or concurrent ownership authority.

## Wire interface

The legacy HIA `f0` SysV interface is used with three independent buffers:
`(request:readbuf, reply:mutbuf, unused:mutbuf) -> u32`. The third buffer is
never read or written. The caller must provide disjoint valid capabilities.

The request is little-endian: `(operation, physical_address, run_pages,
arena_count)` as four u64 words, followed by exactly `arena_count` 24-byte
descriptors `(physical_base, arena_pages, reserved_prefix_pages)`. The length
must equal `32 + 24 * arena_count`. The router accepts at most 32 arenas.
The response is two u64 words `(status, value)`, and the returned u32 equals
`status`. On a sufficiently large response, failures set `value=0`; if
the reply is shorter than 16 bytes, the caller observes only status 1 and
no reply writes. Request and state buffers remain unchanged.

| Operation | Inputs | Successful value |
| --- | --- | --- |
| 0 VALIDATE | `physical_address=0, run_pages=0` | Count of validated descriptors |
| 1 ROUTE_EXACT | Page-aligned physical address, nonzero contiguous page count | **1-based** arena index in the *original caller-supplied descriptor order* |

A valid descriptor has 1..65,536 pages, a 4096-byte-aligned base below
`2^52`, an exclusive end no higher than `2^52`, and
`reserved_prefix_pages <= arena_pages`. **Every descriptor is validated
before any routing result is returned**, even when an earlier arena happens
to contain the requested interval. Pairwise full physical ranges are checked
for overlap independent of descriptor ordering; adjacent regions are legal,
gaps are legal, and two overlapping regions are invalid even if their
reserved prefixes differ. For routing, the full requested run must lie in a
single arena's non-reserved suffix. The router never silently combines a run
across adjacent arenas. It rejects a request crossing an arena boundary.

Status values are 0 OK, 1 REPLY_TOO_SMALL, 2 BAD_REQUEST (truncated or
overlong request, or >32 descriptors), 3 UNKNOWN_OP, 5 NO_MEMORY
(valid descriptors but no single matching non-reserved arena), and 6
INVALID_ARGUMENT (invalid geometry, overlaps, malformed validation request).
All other kernel allocator status codes are deliberately unused.

Every accepted arena must **already have passed** the independent E820 region
admission check with a trusted firmware/loader memory-map snapshot, and must
not overlap kernel image, page tables, stack, firmware, ACPI, MMIO or loader
allocations. This router does not prove any of those prerequisites. It also
does not maintain allocations, handle hotplug, prevent physical aliases across
concurrent CPUs, or coordinate reinitialization. The descriptor array is
caller-owned and mutable; independent identity/lifetime protection is an
unmet Linux kernel obligation.

## Independent evidence and remaining integration

`make test-arenas HEPTA_COMPILER=...` builds the actual HIA object, checks
for undefined symbols, links it to a native test library, verifies that its
`.text` matches the HIA object, and compares its behavior with a separately
written Python oracle. The oracle tests boundary geometry, duplicate and
overlapping descriptors, unsorted maps, disjoint fragmented arenas, completely
reserved arenas, exact-range success and failure, malformed lengths, reply
lengths, absence of writes and deterministic randomized cases. A separate,
deliberately dishonest **native HIA** object that returns success for a
reserved request is required to disagree with the oracle.

This is a host-side native component proof. A QEMU multi-arena allocation and
readback path is not yet integrated: the existing boot path still uses one fixed
4–8 MiB arena, the non-HIA `boot.S` transport and its own E820 gate. The
next integration must bind each arena to its exact E820 evidence, initialize
separate allocator states, route allocation requests to a legitimate zone,
and test real physical pages and error paths under QEMU. Full Linux
compatibility remains `HOLD`.
