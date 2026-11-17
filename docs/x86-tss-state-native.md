# Native HIA TSS IST1 and I/O bitmap state (single-owner component)

The pinned HIA Core v8 selfhost_elf compiler directly translates
`src/x86_tss_state.hepta` to x86-64 ELF machine code. This is not an
interpreter or an assembly/foreign-code wrapper.

Request: three little-endian u64 words (24 bytes), respectively new
IST1 stack top, expected old IST1 and expected old I/O bitmap base.
Reply: at least 16 bytes. TSS: exactly 104 mutable bytes. A 48-bit
canonical, nonzero, 16-byte-aligned stack top is required. After
checking the current TSS fields against both old values, native HIA
writes IST1 at offsets 36..43 and disables I/O bitmap access by writing
104 to offsets 102..103. It preserves the other 94 bytes. On any
rejection the entire TSS remains unchanged. Codes are 0=committed,
1=short reply, 2=invalid request, 4=invalid TSS length,
6=bad stack pointer/old-IOMAP width, and 9=stale old value.

A deterministic independent Python integer oracle checks guard bytes,
old-value refusal, invalid buffer geometry, address and alignment
validation, correct two-field writes, and a dishonest native HIA
negative control. This is a standalone verified component; the active
QEMU TSS remains temporarily populated by boot.S until the bridge
integration is separately validated and merged.

It does not implement LTR, exception entry, IRET, hardware provenance,
SMP CAS, or privileged HIA backend support. The 17 Linux gates and
422 syscall obligations remain HOLD.
