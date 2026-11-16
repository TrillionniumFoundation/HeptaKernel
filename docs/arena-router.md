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
| 2 FIRST_FIT_GEOMETRY | Physical alignment as a nonzero power of two in **pages**, nonzero contiguous page count | First geometrically valid, physically aligned address in descriptor order; **does not inspect occupied frames** |

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

Operation 2 accepts any representable nonzero **u64 power-of-two**
page alignment (from 1 through `2^63`), matching the HIA page allocator's
alignment argument. It does not impose the 65,536-page *arena size* limit
on the alignment. A region beginning at physical address zero may satisfy
even very large alignment requests. Otherwise a large alignment with no
candidate below the physical limit returns NO_MEMORY, rather than wrapping
around or accepting an out-of-range address. The requested run remains
limited to 65,536 pages and cannot straddle zones. The first-fit result is
read-only and has no live-bitmap or ownership reservation semantics.

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

The genuine native HIA router is now additionally linked under a distinct
`arena_f0` symbol into the QEMU Multiboot image. After real loader E820
admission, the explicitly non-HIA observer checks six immutable 80-byte router
requests against independently fixed return/status/value values in PC and Q35:
two-zone validation, correct first/second routing, protected reserved prefix,
run crossing a zone boundary, and an overlapping descriptor map. Only after
these checks may the existing single-arena PMM tests continue. The faulty
native-HIA replacement of `arena_f0` must fail the boot observer, with an
explicit failure exit. The exact HIA machine-code section is bound to each
64-bit and 32-bit boot-image container, including the dishonest mutant.

This QEMU milestone verifies the **read-only router** running in ring 0; it
still does not implement dynamic multi-arena allocation and readback. The
existing physical allocation fixture is one fixed 4–8 MiB arena, and the
non-HIA `boot.S` transport and E820 gate remain. The next integration must
bind each arena to its exact E820 evidence, initialize separate allocator
states, route allocation requests to a legitimate zone, and test actual
physical pages and error paths under QEMU. Full Linux compatibility remains
`HOLD`.

## Two-region physical ownership integration (test fixture)

The QEMU Multiboot observer now replays **two independent calls** to the
real native HIA E820 checker using the retained loader-provided firmware
map: 17 pages at physical `0x400000` and 17 pages at `0x600000`.
Both must independently return the exact admitted length. Then the real
native HIA router selects zone 1 and zone 2 for two-page runs beginning
at `0x402000` and `0x601000`. A fixed immutable zone-ID-to-state table
selects two disjoint, guarded 8192-byte private HIA allocator states.

The observer invokes the unchanged actual native HIA PMM entry `f0` for
both states. It independently checks initialization free counts (15/16),
the exact physical addresses of two allocated runs, four distinct word
sentinels written and read back **while all pages are simultaneously
allocated**, cross-zone `CLAIM_RUN` rejection, occupied-run query results,
two successful frees, duplicate-free rejection, and final free counts.
No Linux runtime or host system call performs these allocations. A
dedicated negative boot image intentionally aliases the second ownership
state onto the first and must fail before any new physical-page access.

This is still an **isolated two-zone test-only orchestration in GNU assembly**,
not a native-HIA dynamic zone manager, a trusted real-firmware memory
provenance proof, a Linux NUMA/buddy subsystem, or SMP-safe allocation.
Allocation metadata remains private, single-threaded and not protected
against firmware compromise. The 17 Linux-wide acceptance gates remain HOLD.

The E820 negative-control HIA object was intentionally strengthened to echo
its requested page count while still **ignoring every firmware reservation**.
This avoids a hard-coded 1024-page reply accidentally rejecting the independent
17-page E820 probes; the unsafe image must still reach the physical readback,
so the independent false-acceptance control remains observable. All original
negative tests remain mandatory.
