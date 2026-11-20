# Native HIA shared-page detach plus copy

`src/cow_split.hepta` is genuine HIA Core v8 source compiled with the
pinned `selfhost_elf` compiler. It combines three changes in one native
call under caller-guaranteed exclusive, quiescent ownership: copy 4096 bytes
from a read-only source capability to a separate writable destination,
decrement an existing shared-source count, and initialize the unshared
destination count from 0 to 1. This removes the application-level gap
between a completed copy and separately requested counter transitions
**only under this single-owner precondition**.

The ABI is `cow_split(source:readbuf, destination:mutbuf, state:mutbuf)`
with exact sizes 4096/4096/4096. `state` contains a 16-byte header:
u16 source slot at 0, u16 destination slot at 2, u8 expected source count at 4,
u8 expected destination count at 5, and ten zero reserved bytes. The remaining
4080 bytes are u8 counters, indexed from byte 16. Indices must be valid and
distinct. The old source count must match the expected count and be at least 2.
The old destination count must match the expected count and be 0. The source
page and destination page must be distinct, non-overlapping capabilities.

Return codes: 0 success, 1 source size, 2 destination size, 3 state size,
4 nonzero reserved, 5 invalid or duplicate slots, 6 stale count,
7 disallowed ownership transition. On every rejected case **neither the
destination nor the table is written**; the read-only source is never written.
On success the entire page is copied, then two count bytes are written. Header,
other counts, and surrounding memory remain unchanged.

`make test-cow-split` compiles HIA native code, checks clean
empty-PATH source/object identity, exercises the independent byte oracle,
probes real OS read-only and inaccessible pages, and requires a malicious
genuinely compiled HIA success-only no-op to be detected by the same oracle.
Both the source and negative control are independently checked by the upstream
HIA Core assembler in Foundation CI.

This is a **single-owner primitive, not a complete COW fault handler**.
Its mutable header and counter table are supplied by the caller, not authenticated
physical frame capabilities. The HIA API cannot yet verify absence of buffer
aliasing or arbitrate SMP races, and has no atomic CAS, PTE installation, fault
entry, privileged TLB invalidation, or rollback on actual machine traps.
No QEMU hardware test of this *new* combined operation is claimed here; earlier
QEMU results for its constituent operations remain separate. All 17 complete
Linux acceptance gates remain HOLD and the 422 syscall obligations remain open.

## Isolated physical-RAM QEMU validation

The new test-cow-split-hw links the unchanged HIA selfhost_elf native object into
PC 32 MiB and Q35 64 MiB QEMU, with independent .text byte-identity checks.
Real E820 admission, HIA PMM allocation and HIA owner-state checks cover
the disjoint physical source 0x402000 and target 0x601000. Only the original
native HIA function copies 4096 bytes while transitioning source count 2 -> 1
and target count 0 -> 1 in a separate 4096-byte caller-owned table.

An explicitly NON-HIA RAM observer independently checks every source byte,
every target byte, all 4096 table bytes including unchanged header/reserved
fields, and guard words. Four per-platform malicious controls must be rejected:
HIA no-op disguised as success, stale expected-old rejected with exact status
6 and unchanged RAM, post-copy destination corruption, and post-copy source
corruption. The report preserves exact QEMU commands, source-image SHA256,
serial output and exit codes. None of this establishes authenticated physical
frame capabilities inside the HIA API, SMP atomics, PTE switching, TLB
shootdown, a real page fault handler or complete Linux COW. The bridge and
hardware observer remain NON-HIA. All 17 acceptance gates remain HOLD.
