# Native HIA x86-64 SYSRETQ candidate admission — restricted profile

This is **real HIA Core v8 source** in src/x86_sysret_admit.hepta,
compiled directly by the pinned native selfhost_elf compiler, not by C,
Rust, assembler or a substituted interpreter. The exported SysV AMD64
function sysret_admit(rcx_user_rip, user_rsp, r11_user_rflags) takes three
caller-supplied u64 arguments and returns a u32 status without memory writes.

The intentionally restricted four-level (48-bit) user-half admission
requires user RIP and RSP within [4096, 2^47). It requires RFLAGS fixed
bit 1 and IF bit 9, and admits only CF, fixed bit 1, PF, AF, ZF, SF, IF,
and OF (allowed mask 0xAD7; required mask 0x202). It refuses TF, DF,
IOPL, NT, RF, VM, AC, VIF/VIP, ID, high/reserved flags and kernel or
noncanonical addresses. Several **legal Linux user states**, including
single stepping with TF and user code with DF, are rejected. This
is a narrow safety experiment, **not** a complete Linux ABI return policy.

Return statuses are 0 (admitted), 1 (bad RIP), 2 (bad RSP), 3 (flags
outside the restricted return profile). An independent Python oracle
checks deterministic boundaries and seeded adversarial random triples,
including positive cases so an always-refuse implementation cannot pass.
A separately selfhost-compiled malicious HIA always-admit routine must
be identified by the oracle. Two empty-PATH rebuilds must produce
byte-identical objects and objcopy verifies linked object/shared-library
.text identity. The test is part of make test and the pinned foundation CI.

Critical omissions: NO SYSRETQ is emitted or executed; no genuine RCX,
RSP, R11, CPL0/CPL3 or CPU MSR capture; no authenticated IA32_STAR,
IA32_LSTAR, IA32_FMASK, EFER.SCE, kernel GS/base/stack ownership, LA57
handling, debug/signal frame semantics, exceptions, SMAP, interrupt or
preemption correctness, QEMU ring transition, Linux syscall dispatch
or general user-space ABI. A caller-supplied successful result is NOT
authorization to switch privilege. The temporary non-HIA boot.S bridge
remains and the pinned toolchain is unchanged.

The 17 full-Linux acceptance gates remain HOLD. All 422 original
x86-64 syscall source rows remain unimplemented.
