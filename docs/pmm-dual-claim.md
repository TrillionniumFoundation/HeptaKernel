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

The original PC/Q35 hardware observer below continues to exercise **claims
only**. The added eight-byte release path is tested by the pinned native
compiler's x86-64 object and independent host differential byte oracle,
including redzones and denial-path immutability; its separate physical-memory
release/reuse lifecycle has **not** yet been exercised in the guest. A valid
claim is not a general DMA/SMAP/IOMMU or multiprocess owner capability.
Releasing a page in the allocator state does not zero its old bytes or revoke
a page-table mapping. Full Linux memory lifecycle, concurrent release,
reference counts and reuse sanitation remain HOLD.

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
four modes each: positive, stale free-count refusal with full-state
immutability, the separately compiled dishonest HIA returning false
success for that stale state, and physical-memory tampering *after*
successful HIA claims. Full borrowed-state and reply redzones must stay
unchanged. Independent serial markers and ISA debug-exit codes distinguish
all eight runs. Timeout, failed, and not-run cases are preserved in
`build/pmm-dual-physical-qemu-report.json` with exact native source,
object, test and boot image hashes.

This adds a real-guest-physical-memory observation of sequential HIA
two-zone allocation. It **does not** establish that the 130-byte state is
authenticated firmware ownership, that claims are atomic or crash-safe,
that the 14 pages belong to a Linux lifecycle, or that HIA implements
privileged instructions, SMP synchronization or a complete Linux PMM.
The complete 17-gate Linux acceptance remains HOLD.
