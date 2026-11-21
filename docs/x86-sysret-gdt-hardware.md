# Native HIA SYSRET64 selector and isolated hardware transition

This milestone adds a **genuine pinned HIA Core v8 native** GDT writer
(`src/x86_sysret_gdt.hepta`), independently validated as an ELF64 x86-64
object from the unchanged selfhost compiler. The source writes one 8-byte
user code descriptor at selector 0x40 (RPL3 selector 0x43) in the enlarged
72-byte active GDT, after checking the exact old value and the existing
HIA-installed user data selector 0x38 (RPL3 0x3b). It never changes the
existing user IRETQ code at 0x30 or the data at 0x38.

The reason for a distinct descriptor is the architectural SYSRET64 rule:
IA32_STAR[63:48] supplies the selector base; returned SS is base+8|3
and returned CS is base+16|3. With base 0x30 these are 0x3b and 0x43.
Simply reusing the existing 0x33 IRETQ code selector would be incorrect.

The isolated PC 32 MiB and Q35 64 MiB images, when actually verified, use
native HIA to install that descriptor and the preexisting native
`src/x86_sysret_admit.hepta` to inspect candidate RIP/RSP/RFLAGS. An
**explicit NON-HIA** assembly test bridge programs IA32_STAR, IA32_EFER.SCE
and IA32_FMASK and executes real hardware SYSRETQ into a user RX page
containing UD2. The independently captured CPL3-to-CPL0 exception frame
must have CS 0x43, SS 0x3b, user RIP 0x400000, user RSP 0x602000 and
the preflighted required RFLAGS. RSP0, IDT vector 6, GDT 0x30/0x38 and
user page-table permissions are prepared by the existing true HIA modules.
A stale-old negative image refuses **before** privilege transition and
checks untouched GDT bytes. Unit tests include a separate compiled
malicious HIA no-op, immutable guards and byte-for-byte object/shared
.text identity, plus empty-PATH native rebuild.

These are hardware **test fixtures**, not a real HIA SYSRET instruction,
SYSCALL entry, privilege-effect verifier, safe kernel stack switch, Linux
system call, IRQ/preemption implementation, or SMP-safe facility.
SYSRETQ runs only inside the marked `arch/x86_64/boot.S` temporary bridge,
not in HIA code. Candidate MSR state, user RSP ownership, safe GS,
FMASK/error recovery and memory ordering are not established beyond the
isolated test. This milestone does not replace a Linux userspace or ABI.
All 17 full-Linux gates and original 422 x86-64 syscall rows remain HOLD.
