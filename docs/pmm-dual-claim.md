# One-call native HIA two-zone PMM claim (bounded single-owner experiment)

The source `src/pmm_dual_claim.hepta` is a genuine `selfhost_elf`
HIA Core v8 program compiled by the pinned upstream native HIA compiler.
It is neither an assembly/foreign-code bridge nor a language interpreter.

## Exact wire and state contract

`f0` receives three normal borrowed-byte buffers: **empty request for claim or an exactly 8-byte LE64 physical address for release**, an
output of at least 16 bytes, and a **130-byte mutable state** consisting of
exactly two consecutive **65-byte** PMM-compatible records. Each record is
a 64-byte header followed by one bitmap octet for exactly eight pages.
At offsets 0,8,16,24,32 each record holds LE64
`magic=3552580688320940353`, `pages=8`, `physical_base`,
`reserved_prefix_pages`, and `free_page_count`. Header bytes
40..63 are zero; bit 1 means occupied. All reserved-prefix bits must be
occupied and every free-page count must equal the bitmap's unoccupied
bits. Physical bases must be 4 KiB aligned, lie below 2^52, and leave
room for the complete 32 KiB zone. The two zones must not overlap.
This is a deliberately fixed-width test fixture, **not** a general E820
zone format, buddy allocator or ownership credential.

After checking **both** records and disjointness before any state write,
an empty-request claim chooses the first free page in zone order, sets exactly
its occupancy bit, reduces exactly that zone's free counter by one, and
writes `(status=0, physical_address)` as two LE64 words. An exactly eight-byte
LE64 release request instead locates the owning zone, verifies page alignment,
requires its occupancy bit set and that the page is **not** part of the reserved
prefix, clears that bit, increments only that zone's free count, and returns
`(status=0, released_address)`. An unaligned, out-of-zone, reserved, or
already-free address returns **status 6** without changing either zone.
The release operation is subject to the same caller-guaranteed exclusive
ownership, not a proof of Linux frame ownership or DMA quiescence.
Invalid state produces status 4, no free page status 5, request length other than 0 or 8 status 2, and short reply status 1. Failure paths do not change
either state record. For a reply buffer of length >=16, status and
value=0 are written on errors; additional reply bytes stay unchanged.
The short-reply path touches neither reply nor state.

The contract provides **single-invocation, sequential first-free selection,
claim, and verified occupied-page release** under externally guaranteed exclusive ownership of the complete
130-byte buffer. It narrows the previous *separate* query/claim time window
for this bounded fixture, but does not provide a hardware atomic test-and-set,
cross-CPU linearizability, freshness of firmware memory ownership, a trusted
inter-zone coordinator, crash transactionality or Linux allocation semantics.
HIA byte stores still occur sequentially; unexpected runtime traps are not
rollback transactions.

## Independent native checks

`make test-pmm-dual-claim` recompiles the exact HIA source twice under
empty PATH, compares the native object bytes, links an ordinary host test
library, requires identical `.text`, then invokes
`tests/test_pmm_dual_claim.py` with a separately implemented Python
byte/bitmap oracle. The oracle verifies statuses, exact state transitions,
every unchanged byte and redzones, malformed headers, reserved bits,
free-count mismatch, overlapping regions, exhausted zones, boundary
physical addresses, repeated claims, successful releases, reserved-page
refusals, unaligned/out-of-zone address refusals and double-free detection. A deliberately dishonest HIA
native library (`build/pmm-dual-claim-liar.so`, compiled from `tests/negative/pmm_dual_claim_allow_all.hepta`) must disagree with the oracle
on a corrupted header. The native test report binds source/object/library
SHA-256 and states explicitly that QEMU/Linux behavior is not tested by
this component.

This test is wired into `make test`, but its green result does not change
`compatibility/coverage.json` or `make full-acceptance`: 17 full Linux
gates remain HOLD and all 422 syscall obligations stay open.

Next critical dependencies are actual HIA privilege/effect instructions,
atomic memory order, authenticated firmware provenance, and QEMU/SMP
ownership tests before evolving this into a true kernel allocator.

## Native release verification scope

The eight-byte release path is checked by the locked native HIA compiler,
an independent host differential byte oracle, and a separate genuine-QEMU
physical-memory experiment. In the release mode, all fourteen allocated
physical pages are first read back, then HIA releases 0x501000 in zone zero.
The non-HIA observer checks the exact 130-byte state and confirms existing
physical contents are **not** erased, rejects a second release with status 6
and no state mutation, and verifies that the next HIA first-free claim
returns precisely 0x501000. A subsequent real physical write/readback checks
the reused guest frame. Full Linux lifecycle, concurrent release, DMA
exclusion, page-table revocation, reference counts and reuse sanitization
remain HOLD.

## Isolated QEMU physical-memory execution

`make test-pmm-dual-qemu` additionally links the **same original native HIA
object** into an x86-64 guest as `dual_claim_f0` (symbol rename only).
A dedicated, plainly non-HIA `boot.S` fixture uses the actual Multiboot
firmware map and genuine HIA E820 admission twice, for distinct 32 KiB
zones at physical 0x500000 and 0x700000. It feeds a 130-byte PMM-compatible
state, initially with one reserved page per zone, to the real HIA entry.

For each of fourteen successful first-free claims, the independent observer
checks the returned address and the entire 130-byte state against its own
simple bitmask/free-count evolution, then fills the **actual claimed 4 KiB
guest-RAM page** with a frame-specific 64-bit pattern. Two further HIA calls
must report exhaustion without modifying the state. Finally the observer
checks all 14 physical pages word by word (7,168 64-bit reads). The
observer, not HIA, provides the initial state and page patterns.

Two machine configurations are used (PC 32 MiB and Q35 64 MiB), with
five modes each: positive, release/double-free/reclaim, stale free-count
refusal with full-state immutability, the separately compiled dishonest HIA
returning false success for that stale state, and physical-memory tampering
*after* successful HIA claims. Full borrowed-state and reply redzones must stay
unchanged. Independent serial markers and ISA debug-exit codes distinguish
all ten runs. Timeout, failed, and not-run cases are preserved in
`build/pmm-dual-physical-qemu-report.json` with exact native source,
object, test and boot image hashes.

This adds a real-guest-physical-memory observation of sequential HIA
two-zone allocation, release and first-free reuse. It **does not** establish that the 130-byte state is
authenticated firmware ownership, that claims are atomic or crash-safe,
that the 14 pages belong to a Linux lifecycle, or that HIA implements
privileged instructions, SMP synchronization or a complete Linux PMM.
The complete 17-gate Linux acceptance remains HOLD.


## Native page-zero scrub **before** PMM release in QEMU

The `dual-scrub` test now composes two existing, unchanged Core v8
native HIA objects: `pmm_dual_claim.hepta` for claim/release and
`page_zero.hepta` for scrubbing the entire 4 KiB guest physical page.
The test-only, non-HIA observer first confirms that `0x501000` is
**still allocated** and contains the original full-page pattern.
An additional native HIA first-free claim must return exhaustion (status 5)
without mutating either of the 65-byte state records. The original HIA
`page_zero_f0` runs *while the PMM occupancy bit remains set*; the observer
then checks its receipt and guard words and independently reads all 512
64-bit words from physical RAM. A second HIA exhaustion check proves the
frame has **not been published to the free list by scrubbing**.

Two adversarial QEMU images separately simulate a dishonest success response
without scrubbing and a post-HIA physical memory mutation. On either failure,
the observer verifies the full 130-byte state remains allocated and calls
the native HIA first-free allocator, which must still refuse exhaustion,
**before** reporting the expected failure. A successful full scan is the
only path permitted to invoke HIA release; afterward the independent oracle
checks the changed occupancy/free count, rejects a double release and
requires first-free reclaim of exactly `0x501000`. The observer rechecks
all 4 KiB after reclaim, before writing a new-owner pattern. PC/32 MiB
and Q35/64 MiB keep all sixteen positive and fault-injected QEMU cases.
The separate `dual-release` mode continues to test intentional release
without scrubbing; it is not a safe cross-owner recycle protocol.

This removes the specific **free-before-scrub ordering** from the isolated
single-owner clean-reuse path. It is not a general Linux page lifecycle:
the caller controls physical ownership, interrupt exclusion and the copied
130-byte state. Live PTE/DMAR revocation, CPU TLB/IOMMU shootdown,
proof of DMA and other owners' quiescence, crash recovery, native atomic
operations and SMP linearizability remain unimplemented. A hostile writer
between the final scrub scan and release is not prevented by this test.
All 17 Linux acceptance gates remain HOLD and all 422 source syscall
obligations remain open.
