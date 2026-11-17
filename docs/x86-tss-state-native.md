# Native HIA x86-64 TSS RSP0, IST1 and I/O bitmap provisioning

The pinned Core v8 `selfhost_elf` compiler translates
`src/x86_tss_state.hepta` directly into x86-64 ELF machine code, without
a foreign implementation or opaque instruction payload.

The exact 40-byte little-endian request has new RSP0, new IST1,
expected old RSP0, expected old IST1 and expected old I/O bitmap offset.
The reply is at least 16 bytes and mutable TSS is exactly 104 bytes.
Both pointers must be nonzero 48-bit canonical, 16-byte-aligned and
distinct. The old bitmap offset must fit 16 bits. Native code compares
all three old fields before any TSS mutation.

On success native HIA writes RSP0 (bytes 4..11), IST1 (36..43), and I/O
bitmap offset 104 (102..103); every other byte remains unchanged.
The reply is status 0 with the new IST1 pointer. Refusal leaves the whole
TSS unchanged: 1 short reply, 2 request geometry, 4 TSS geometry,
6 bad pointer/bitmap width, 9 stale old field. This is a *single-owner*
transaction, not an SMP atomic multiword update.

An independent integer/byte-array oracle tests all three stale-old
fields, canonicality, alignment, distinct pointers, malformed buffers,
randomized contents and guarded boundaries. A deliberately dishonest
native HIA implementation is required to fail the oracle.

The actual PC/Q35 QEMU boot bridge calls this native HIA writer before
native HIA GDT descriptor installation and non-HIA LTR. Positive paths
read back all three fields. Separate bare-metal stale-IST1 and stale-RSP0
fault images must each reject without partial mutation before LTR. NX
and supervisor write-protection #PF tests still verify hardware IST1.

RSP0 is prepared for a future CPL3-to-CPL0 transition. No user-mode
transition has yet exercised hardware RSP0 switching; LTR, LIDT, CRx,
exception entry/IRET, MMIO, atomic ordering and SMP ownership are not
native HIA. All 17 Linux gates and 422 syscall rows remain HOLD.
