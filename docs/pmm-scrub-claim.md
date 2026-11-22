# Native HIA one-call zero-before-claim for two PMM zones

`src/pmm_scrub_claim.hepta` is actual HIA Core v8 `selfhost_elf` source, lowered
by the pinned standalone native x86-64 compiler. It complements
`pmm_scrub_release.hepta`: the old routine clears the page before *freeing*
it; this routine clears the page before *marking it allocated*.

## Calling contract

`f0(request:readbuf, state:mutbuf, page:mutbuf) -> u32` takes exactly
eight request bytes (LE64 requested physical address), exactly 130 mutable
state bytes (two nonoverlapping 65-byte, eight-frame PMM zones), and exactly
4096 mutable page bytes. The caller must already hold the specified page
capacity, disallow aliasing among the inputs, and guarantee no concurrent
access by CPUs or DMA.

The native routine validates both zones' magic, frame count, reserved
prefix, free/bitmap agreement, aligned 52-bit-bounded physical bases,
all zeroed state padding, and disjoint 8-page ranges; it then checks that
the requested page is aligned, belongs to a zone, is not reserved, and
is *currently free*.

On success, one HIA call zeroes all 4096 bytes **before** setting the
corresponding occupancy bit and decrementing that zone's free counter.
It returns status 0. Status 1 means wrong request length, 2 wrong state
length, 3 wrong page length, 4 invalid state or overlapping zones,
and 6 unavailable/invalid page address. No refusal mutates any input.

Validation consists of an independently authored byte/bitmap Python oracle
and a separately compiled dishonest HIA constant-success control. On the
exact locally tested candidate: 1,070 native differential cases matched,
1,070 dishonest-control mismatches were detected, original native object and
host shared-library `.text` matched, and two empty-PATH compilations yielded
identical objects. The CI checks the same source and controls independently;
reports and object bytes are retained with the exact candidate.

Use `make test-pmm-scrub-claim`; it is also a prerequisite of `make test`.

## Non-claims and open blockers

The physical-address request is **only data**. The HIA code does not prove
that its independent page capability points to the requested physical frame.
It does not verify E820 ownership, inter-call coherence, mutable capability
nonaliasing, CR3/TLB/IOMMU state, interrupts, or DMA quiescence. Traps during
the scrub or the subsequent metadata update can leave partial state. The
precondition is a single, quiescent owner; there is **no hardware-atomic
publication, SMP linearizability, TLB shootdown or Linux page allocator**.
The initial HIA component was qualified with host-native differential tests;
a later, isolated physical QEMU integration is detailed below. This does not
close the missing privileged HIA backend. Linux's pinned baseline and all 17 closure gates
remain HOLD; the original 422 syscall obligations are unchanged.

The HIA language/verifier/native backend still lacks verified CRx/MSR,
IRETQ/exception entry, privileged I/O, atomics and memory-ordering effects.
The non-HIA `boot.S` bridge is not replaced, and no upstream Hepta main or
compiler lock was changed.

## Physical QEMU execution (single-owner experimental contract)

The `dual-native-claim` and `dual-native-claim-noop` guest images link
exactly the HIA object compiled by the native host oracle, with only the ELF
symbol `f0` renamed. The non-HIA fixture first obtains two E820-admitted
8-frame zones, performs 14 genuine HIA allocations and observes all 14
physical 4KiB patterns. It then calls the existing HIA release ABI for
`0x501000` to produce an actual free-but-nonzero physical frame. Only after
checking the 130-byte metadata and all 512 old words does it call the new
HIA scrub-claim function on the real guest RAM address. An independent
observer verifies the exact occupied bitmap/free count and all 4096 zeroed
bytes. The previously free page is now unavailable to the original HIA
first-free allocator. A repeated scrub-claim on the occupied page must
return 6, preserve the entire metadata and preserve an intentionally
introduced page sentinel.

A separate image links the compiled dishonest HIA no-op returning success.
It must be rejected because the HIA state and old physical RAM do not
change. Both images are run under PC/32MiB and Q35/64MiB, with exact
image/source/object hashes and separate positive/negative exit rules.
This extends the independent hardware test matrix from 20 to 24 cases.
The bridge, E820 transport, requested-address-to-page-pointer association
and ownership quiescence remain **non-HIA test assumptions**, not kernel
or HIA-backend closure. No credit is given toward the 17 full acceptance
gates or 422 syscall obligations.
