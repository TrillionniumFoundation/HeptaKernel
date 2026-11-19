# Native HIA full-page zeroing

`src/page_zero.hepta` is a genuine HIA Core v8 `selfhost_elf` function that
writes zero to every byte of exactly one 4096-byte mutable page capability.
It does not call libc, issue Linux host syscalls or embed opaque machine bytes.

The public ABI is `f0(request:readbuf, reply:mutbuf, page:mutbuf) -> u32`.
The request must have length zero; the reply must have exactly 16 bytes; the
page capability must have exactly 4096 bytes. All shape failures leave both
mutable capabilities untouched: status 1 (request), 2 (reply), or 3 (page).
Success returns 0, zeros exactly the page and publishes `(0,4096)` as two
little-endian u64 reply words.

Independent Python byte-oracle tests compare the entire page, reply and
surrounding sentinels on 82 deterministic calls. OS guard pages enclose the
actual HIA native fill; an oversized length pointing into a PROT_NONE neighbor
must reject without touching either buffer. A separately compiled dishonest
HIA program that always returns success but leaves secrets present is
required to fail the same oracle. Empty-PATH compilation must reproduce
the complete native object byte-for-byte.

**Scope:** This is a real native data-mutation primitive, *not* authenticated
physical-page ownership. The HIA capability is supplied by its caller; it
cannot establish that the bytes are mapped to an allocated PMM frame, cannot
prove quiescent exclusivity, lacks cross-CPU synchronization and has no
privileged CRx/MMIO/TLB backend. Integrate with a verified PMM claim,
identity-bound mapping, appropriate memory ordering, and QEMU physical
readback before claiming secure frame recycling or user data isolation.
The original 17 full-Linux gates and 422 syscall obligations remain HOLD.

## Isolated QEMU physical-frame test

`make test-page-zero-hw` links the exact `src/page_zero.hepta` object
with a renamed symbol into a Multiboot image; the object and linked object
must have identical `.text` bytes. The NON-HIA boot observer requires the
real Multiboot memory map and protected-range gate to admit two disjoint
17-page arenas. The actual HIA router, HIA allocator and HIA state-owner
checker provision two 2-page allocations at physical addresses 0x402000
and 0x601000. Those four physical frames are filled with nonzero bytes
in the observer, passed as 4096-byte mutable capabilities into the genuine
HIA function, and independently checked byte by byte for zero in QEMU PC
32 MiB and Q35 64 MiB.

Two negative images use exactly the same observation path. One substitutes
an independently compiled dishonest HIA routine that returns success without
writing memory; the reply is preseeded with plausible values so only actual
physical RAM readback can detect the bypass. The other runs genuine HIA and
then corrupts byte 2048 in real RAM via an expressly NON-HIA malicious bridge;
full-byte readback must reject the decoy. Each negative image must finish
with failure exit 35, without a positive page-zero marker. Original host
byte-oracle and guard-page tests remain independently required.

This is an **isolated quiescent single-owner hardware test**, not a proof that
`page_zero` itself authenticates physical-frame ownership, preserves other
zones under concurrent updates, performs page retirement, implements IOMMU
or DMA safety, or works without the existing non-HIA QEMU bootstrap.


## E820/PMM release–reallocate–scrub lifecycle (isolated QEMU)

The same PC/32MiB and Q35/64MiB physical test now calls the genuine HIA
PMM to free both allocated two-frame runs, checks the *new* native HIA
ownership states via the independent HIA owner-binding entry, then
reallocates both runs. The HIA first-fit results must be the exact original
four physical addresses, and each state must again have its expected
free-page count. The non-HIA observer dirties all 16,384 physical bytes
*after* reallocation; the unchanged native HIA `page_zero` object must
clear every byte. An independent physical RAM readback, not the reply
status alone, determines success. Both runs are released again before
the original double-free refusal and final-count tests.

A dedicated `recycle-bypass` image performs the genuine HIA PMM
release/reallocation operations but suppresses only the second HIA
zero call in the expressly malicious **non-HIA test bridge**; it
falsifies a successful status/reply, leaving dirty real RAM behind.
The independent physical observer must reject the first dirty byte
with the failure exit, while retaining the marker that the first
four-page HIA scrub actually passed. Source/object/linked-image binding
remains unchanged. Eight distinct QEMU runs (two machines × four
scenarios) are recorded in `build/page-zero-hardware-report.json`,
including image SHA-256, stdout/stderr and return codes.

This is a single-owner **test fixture** for identity-bound reuse and
data erasure, not a concurrent allocator, an authenticated frame
mapping, a native HIA physical-pointer authority, IOMMU/DMA isolation,
SMP shootdown, or a substitute for the missing privileged HIA backend.
The full 17 gates and 422 syscall rows remain HOLD.
