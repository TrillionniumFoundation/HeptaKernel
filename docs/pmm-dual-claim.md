# One-call native HIA two-zone PMM claim (bounded single-owner experiment)

The source `src/pmm_dual_claim.hepta` is a genuine `selfhost_elf`
HIA Core v8 program compiled by the pinned upstream native HIA compiler.
It is neither an assembly/foreign-code bridge nor a language interpreter.

## Exact wire and state contract

`f0` receives three normal borrowed-byte buffers: **empty request**, an
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
the HIA routine chooses the first free page in zone order, sets exactly
its occupancy bit, reduces exactly that zone's free counter by one,
and writes `(status=0, physical_address)` as two LE64 words.
Invalid state produces status 4, no free page status 5, nonempty
request status 2, and short reply status 1. Failure paths do not change
either state record. For a reply buffer of length >=16, status and
value=0 are written on errors; additional reply bytes stay unchanged.
The short-reply path touches neither reply nor state.

The contract provides **single-invocation, sequential first-free selection
and claim** under externally guaranteed exclusive ownership of the complete
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
physical addresses, and repeated claims. A deliberately dishonest HIA
native library (`build/e820-allow-all.so`) must disagree with the oracle
on a corrupted header. The native test report binds source/object/library
SHA-256 and states explicitly that QEMU/Linux behavior is not tested by
this component.

This test is wired into `make test`, but its green result does not change
`compatibility/coverage.json` or `make full-acceptance`: 17 full Linux
gates remain HOLD and all 422 syscall obligations stay open.

Next critical dependencies are actual HIA privilege/effect instructions,
atomic memory order, authenticated firmware provenance, and QEMU/SMP
ownership tests before evolving this into a true kernel allocator.
