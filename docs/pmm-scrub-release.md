# Native HIA single-call scrub-before-release (two eight-page zones)

The program in `src/pmm_scrub_release.hepta` is an actual HIA Core v8
`selfhost_elf` source. It is compiled directly by the locked, self-hosted
native compiler; no inline bytes, foreign kernel implementation, or
interpreter participates in the target operation.

## Exact three-buffer contract

`f0(request:readbuf, state:mutbuf, page:mutbuf) -> u32` receives:

* exactly eight request bytes: little-endian target physical address;
* exactly 130 mutable bytes: two consecutive, 65-byte PMM states, with
  two 8-frame zones and the same layout as `pmm_dual_claim.hepta`;
* exactly 4096 mutable bytes: the **caller-provided memory for the
  requested, already-owned frame**.

It checks both PMM states (including reserved prefixes, bitmap-free-count
consistency, alignment, physical width, zeroed metadata padding and
nonoverlap) before any writes. It then verifies the address belongs to
exactly one zone, has page alignment, is currently occupied, and is not
within its reserved prefix.

On success it zeroes **all 4096 bytes first**, then clears exactly one PMM
occupancy bit and increments the corresponding free count. These operations
take place in one native HIA invocation, so unlike the previous
`page_zero` followed by `pmm_dual_claim` protocol there is no
*between-calls* opportunity to publish the page before scrub under the
single-owner precondition. Status 0 means the routine returned from both
writes. It does not return a separate address or reply buffer.

Failures do not write the page or the state:
status 1 for malformed request length, 2 for malformed state length,
3 for malformed page length, 4 for invalid PMM state/disjointness,
and 6 for an ineligible (misaligned, out-of-zone, reserved or already
free) requested page. Error precedence is lengths then state then address.

## Critical trust boundary

The HIA routine receives a *physical address as data*, plus an
independent mutable `page` capability; **it cannot authenticate that
the pointer designates the requested physical frame**. The caller must
prove the mapping binding, exclusive ownership, and CPU/TLB/IOMMU/DMA
quiescence before invocation. The two mutable capabilities must not
alias. There is no hardware-atomic publication, SMP synchronization,
crash rollback, CPU memory fence, IOMMU operation or DMA revocation.
A trap during the page stores can leave a partially scrubbed but still
occupied frame; a trap during the later metadata stores may leave a
partially updated PMM state. This is not a general allocator, page
recycle service, or complete Linux memory lifecycle.

The existing PC and Q35 `dual-scrub` hardware tests use a **different
two-invocation** protocol; those tests cannot be counted as hardware
validation of this newly added native single-call function.

## Independent validation

`make test-pmm-scrub-release` builds the actual self-hosted compiler's
x86-64 ELF object twice under `env -i PATH=`, compares the exact
bytes, requires identical `.text` in the host shared-library link, and
runs `tests/test_pmm_scrub_release.py`. This test uses the existing
independently implemented Python PMM byte/bitmap oracle plus an
independent page-zero oracle. The suite varies occupied/reserved bits,
region order/overlap, physical boundaries, malformed lengths and
metadata, and exact full-page contents; redzones around the borrowed
buffers must remain intact. A separately compiled dishonest native HIA
routine that claims success without scrubbing or changing the PMM
must disagree with the independent oracle on at least 100 cases.
The report binds source/object/library hashes to these test results.

The fixed Linux 7.3.4 and Hepta compiler commits remain unchanged.
All 17 full-Linux gates and all 422 x86-64 syscall source obligations
remain open. The main missing dependencies are HIA privilege and
atomic/fence semantics, verified physical-frame pointer binding, true
mapping revocation, CPU/DMA quiescence, SMP ownership and full
multi-platform system integration.
