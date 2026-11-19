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
