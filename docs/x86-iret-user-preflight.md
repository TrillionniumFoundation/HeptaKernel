# Native HIA admission before a real x86-64 IRETQ test transition

The true fixed Hepta Core v8 selfhost_elf compiler builds
`src/x86_iret_user_admit.hepta` as a freestanding native x86-64 ELF object.
This scalar preflight is directly called **before**, but never replaces, the
explicit NON-HIA IRETQ in `arch/x86_64/boot.S`.

The restricted 64-bit x86-64 initial user frame has five scalar inputs:
RIP, RSP, RFLAGS, CS and SS. The admitted selectors are 0x33/0x3b, with
canonical low-half RIP, 16-byte-aligned low-half RSP and a nonempty stack
page below RSP. Fixed bit 1 in RFLAGS is required, with only the deliberately
restricted 0xAD7 flags mask allowed (IF may be zero or one). The pinned
Linux x86 UAPI correctly identifies RFLAGS bit 0 as CF (carry) and
bit 1 as fixed; 0x3 and 0xAD7 are legal in this restricted profile.
Bit 3 is reserved and disallowed. The oracle
now sweeps all 64 bit positions from three independently admitted bases. The initial RIP
may not point into the writable page ending at RSP. Return codes are
0 admitted, 1 RIP, 2 RSP, 3 selectors, 4 flags and 5 executable-stack alias.
No write or privilege effect is claimed.

The independent Python oracle tests >10,000 scalar tuples, object/shared .text
identity, two empty-PATH native rebuilds and an intentionally dishonest
compiled HIA always-allow implementation. QEMU/TCG tests on PC 32 MiB
and Q35 64 MiB exercise the original positive CPL3 HIA initial-stack
readback and a new negative: the bridge passes RIP=0x601000, inside the
HIA-prepared user stack page, to the native HIA gate. The real CPU must **not**
execute IRETQ on this rejection; the expected rejection marker and debug-exit
are checked separately from the positive CPU exception-frame path. A malicious
always-allow gate cannot pass that negative.

A separate PC/Q35 QEMU negative now passes RFLAGS 0xA (reserved
bit 3 set) to the genuine HIA scalar preflight, requires status 4,
checks a distinct diagnostic marker and exits without reaching IRETQ.
The existing legal CPL3 entry remains the positive control; the stack-RIP
collision is a distinct negative. This tests refusal on an actual boot
path, not native HIA privilege execution.

The bridge continues to own GDT/TSS/IDT, CR3, IRETQ, CPL3 instruction
fixture and exception frame. Caller-provided scalar state is not hardware
authenticated. This is **not** an implemented IRETQ HIA opcode/effect verifier,
not an atomic multi-core authority, ELF execution, Linux execve, general
signal return, or complete task/context switching. Do not increment
any of 422 Linux syscall obligations or the 17 full-target gates. The
locked Linux and Hepta source/Compiler SHA values are unchanged; full
acceptance remains exit 2 HOLD.
