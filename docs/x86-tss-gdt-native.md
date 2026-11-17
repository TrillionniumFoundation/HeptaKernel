# Native HIA x86-64 64-bit TSS GDT descriptor (single owner)

`src/x86_tss_gdt.hepta` is compiled to real ELF64 x86-64 machine code
by the pinned HIA Core v8 `selfhost_elf` backend, not a foreign-code stub.

The ABI has exactly 32 read-only request bytes: `base`, `limit=103`,
`expected_old_low`, `expected_old_high` (u64 little endian);
at least 16 reply bytes, and exactly 48 exclusive mutable GDT bytes. The
native code requires a nonzero 16-byte-aligned canonical 48-bit base and
the precise 104-byte 64-bit TSS limit 103. It checks both old descriptor
words before installing the exact x86-64 available TSS low/high descriptor
in bytes 32..47, preserving all four earlier GDT slots.

Status 0 commits, 1 means short reply, 2 invalid request length,
4 invalid GDT length, 6 invalid base/limit, and 9 expected-old mismatch.
Rejection does not modify GDT. The independent Python integer oracle
checks guards, canonical/address limits, descriptor layout, expected-old
refusal and a deliberately dishonest native HIA control.

QEMU PC/Q35 now executes the HIA writer before non-HIA privileged `ltr`,
reads back the descriptor, and uses the hardware TSS/IST1 #PF switch
proven by the existing NX/WP paths. A stale-word image proves the writer
rejects before `ltr` or IDT installation. Exact HIA text is independently
rebuilt with empty PATH and compared against host and QEMU images.

This **does not** make TSS data/IST pointer provisioning, `ltr`,
`lidt`, exception entry/`iretq`, CRx operations or SMP atomicity
HIA-native. All 17 Linux gates and 422 syscall obligations remain HOLD.
