# Native HIA COW prepublication abort and zeroization

`src/cow_abort.hepta` is a genuine HIA Core v8 `selfhost_elf` native
routine. It addresses a concrete gap in the staged COW #PF path: after a
successful `cow_split`, a subsequently refused PTE change must not leak a
private destination frame, leave the source refcount decremented, or recycle
a page containing copied source contents.

Under **caller-guaranteed exclusive quiescence**, the caller must independently
check that the PTE still maps the original read-only source frame and that no
other actor can observe the unpublished destination. After a successful split,
the caller updates only the request header to the current post-split counts
and invokes `cow_abort(destination:mutbuf,state:mutbuf)`. Both buffers must
be disjoint, writable and exactly 4,096 bytes. The 16-byte header has u16
source/destination slots (bytes 0..3), expected post-split counts (4..5),
and ten zero reserved bytes. The remaining 4080 bytes are u8 counters.

A successful abort requires distinct in-range slots, matching actual counts,
source count in 1..254, destination count exactly 1. It then zeroes all 4,096
destination bytes, increments the source count and resets the destination
count to zero. Header and unrelated counters are not modified. Codes:
0 success, 1 invalid destination size, 2 invalid state size, 3 reserved
field, 4 slot, 5 stale count, 6 disallowed ownership. All rejected calls
must leave both buffers unchanged.

The independent native test covers fixed/random boundary cases, full byte
oracle, real operating-system guard pages, always-success malicious HIA,
and round trips with the genuine `cow_split` native object. It is also
part of the default `make test` and Foundation CI. The fixed HIA compiler
and byte-for-byte empty-PATH rebuild requirements are unchanged.

**Important:** This alone does not implement rollback in the actual QEMU
page-fault handler; the existing boot bridge has not yet been wired to call
it after an injected *late* PTE failure. A caller could still mistakenly
reclaim a page already published by a successful PTE update. The routine
cannot authenticate physical ownership or prove that a PTE is unchanged;
the non-aliasing and exclusive quiescence assumptions are external.
Its zeroing and counter writes are sequential, not a hardware atomic
transaction. Traps midway, SMP races, CAS, TLB shootdown, and general Linux
process COW remain unimplemented. The complete 17 Linux gates and all
422 syscall obligations remain HOLD.
