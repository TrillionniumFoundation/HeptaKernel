# Native HIA x86-64 IDT descriptor installation (single-owner)

The pinned upstream HIA Core v8 `selfhost_elf` compiles
`src/x86_idt_gate.hepta` directly into native x86-64 ELF machine code.
The three buffer capabilities are an **exact 40-byte read-only request**, an
at-least-16-byte mutable reply, and an exactly 4096-byte exclusive mutable
IDT. The SysV entry returns status u32.

The request consists of five little-endian u64 words, in order:
`vector`, `handler_rip`, `expected_old_low`, `expected_old_high`,
`ist_index`. The HIA function checks vector in [0,255], a nonzero canonical
48-bit handler address, and IST index in [0,7]. It then checks *both* old IDT
words before writing an exact 16-byte x86-64 interrupt-gate descriptor.
The descriptor uses supervisor CS=0x08, DPL=0, type 0xE, P=1 and the
validated three-bit IST index in bits 32–34. All reserved bits are zero,
and the supplied 64-bit handler address is retained. Status 0 may modify
the descriptor; 1 means short reply, 2 malformed request, 4 incorrect
table length, 6 invalid vector/handler/IST, and 9 stale old descriptor.
No rejection changes the 4096-byte table. The single-owner read/compare/write
is **not** atomic CAS or safe against concurrent SMP descriptor updates.

The independent Python integer oracle checks all 256 vector encodings,
every valid IST index, invalid indices >=8, handler canonicality, stale
expected-old values, malformed buffers and guard boundaries. The dishonest
native HIA negative control must fail. The actual PC/Q35 startup builds all
256 default IST0 gates using native HIA; the page-fault vector #14 is then
replaced by the same HIA function with **IST1** in isolated NX and CR0.WP
fault images. The non-HIA temporary QEMU bridge constructs a 104-byte
64-bit TSS, sets its IST1 to a separate 8 KiB stack, installs the TSS
descriptor in the GDT, and executes privileged `ltr`. The CPU must
deliver a genuine #PF through the HIA-produced IDT gate with the exception
frame's `RSP` strictly inside that stack. Only then may the native HIA
page-fault policy classifier accept the observed error code, CR2, RIP,
PTE and control-register state. The boot oracle requires the dedicated
hardware IST1 marker in both PC/Q35 NX and WP fault paths; intentional
NX/WP bypass images cannot satisfy these paths by raising a generic fault.

A negative QEMU image supplies a stale old IDT word for vector zero,
requiring status 9 with the original descriptor unchanged and refusal
before `lidt`. Native compiler self-rebuild, empty-PATH HIA object byte
identity, native oracle and dishonest controls, QEMU positive/negative
matrices, and full-target HOLD remain independent requirements.

This is **HIA-native IDT encoding including real IST selection and an
isolated hardware stack-switch test**, not HIA-native TSS construction,
`ltr`, `lidt`, exception entry, `iretq`, returnable fault handling,
IST-safe nested interrupt concurrency, or SMP correctness. Those operations
remain in the openly identified GNU assembly test bridge; the full pinned
Linux rewrite's 17 gates and syscall obligations remain unclosed.
