# Experimental ordered native HIA syscall MSR initialization

This is a successor to Draft #176 and preserves that independently tested
LSTAR-only subject. The exact experimental compiler remains Hepta #950
at 43ddfe0479f182792e17e80822ac00d75a78a4ac; binary SHA-256
05071e2abb7bb74982cdf8d67a58a8c16b7226ba17d4d65cd172135e90b77cb6.
No production toolchain change.

The genuine HIA subject validates the high-half canonical aligned
address, live CR4.LA57=0, EFER.LMA=1 and SCE=0, and all four expected
old MSRs before any write. It installs LSTAR, STAR (fixture kernel
selector 0x18), FMASK (0x201), then sets EFER.SCE last while preserving
the other EFER bits. Each write has immediate actual readback. Status
0 denotes exact readback, 6 invalid address, 8 invalid mode, 9 stale
input, 10 a mismatched write. This is a single-CPU, exclusive/quiescent,
trusted-configuration experiment; a mismatch may leave a prefix of
the MSRs configured. It is not an atomic transaction or exception-safe
rollback; machine faults during privileged access are outside this
function's handling. The selector and FMASK constants are fixture
policy, not a general Linux ABI or a SYSRET selector setup.

The non-HIA guest observer verifies all four live values before IRETQ
and uses actual CPL3 SYSCALL into the HIA-configured high-half address.
The entry observer verifies selectors, saved RIP/flags/RSP, RAX and
masked flags, switches stacks, and restores all four old MSRs. Each
of four stale-input controls must leave the MSRs unchanged. Four
independent WRMSR-to-NOP mutations must fail readback at the affected
stage, leave later MSRs untouched and keep SCE disabled. Noncanonical,
unaligned and already-active controls are also tested. All 12 cases
run on both PC and Q35 with source/compiler/object/linked-byte custody.

Local 2026-11-24 exact subject: 24/24 PASS using a directly launched
QEMU subprocess. Source SHA-256
55e762d910f7790a5ba3437f4493d6b003c6bbbd6dd38533962dea6b7e850fbc,
object SHA-256
4aa94ff2900d0335deed549ea4713bae5121bed31cec4d75e479cbdc09dd1fe5,
text SHA-256
2a2493d9fa3d6519ed0f25a3163cec4491064173b05a513787fc4691107f2cf7.
Independent exact-commit CI remains required.

The native entry/return trampoline, descriptor and page authority,
privileged-fault recovery, SMP ownership and Linux syscall dispatch
are not established here. All full acceptance gates remain HOLD.
