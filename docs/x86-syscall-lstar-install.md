# Experimental native HIA LSTAR installation

The isolated source `src/x86_syscall_lstar_install.hepta` uses the genuine
selfhost candidate in Hepta Draft #950, pinned at
`43ddfe0479f182792e17e80822ac00d75a78a4ac`. Its independently rebuilt
compiler must have SHA-256
`05071e2abb7bb74982cdf8d67a58a8c16b7226ba17d4d65cd172135e90b77cb6`.
The production toolchain lock is unchanged.

The subject admits only a 16-byte-aligned high-half 48-bit canonical
target, actual CR4.LA57 clear, actual EFER.LMA set and SCE clear, and the
exact expected live LSTAR. It performs a genuine WRMSR and rereads the
result. Status 0 means exact readback, 6 invalid address, 8 invalid mode,
9 stale old value, and 10 mismatched readback. The subject does not write
STAR, FMASK or EFER. It assumes caller-controlled CPU ownership and
quiescence; the check/write is not a concurrent atomic transaction, and a
processor fault during WRMSR is not handled here.

The isolated non-HIA Multiboot observer establishes supervisor-only
high-half mapping, user RX code, separate RW/NX user stack, and GDT;
it independently verifies the other MSRs remain unchanged by HIA, then
sets STAR/FMASK/SCE and uses IRETQ to start actual CPL3 execution. The
user instruction executes SYSCALL. The observer independently checks
the high-half entry address, actual user and supervisor selectors,
RCX/R11, user RSP, FMASK-cleared flags and RAX. It switches the stack
before any stack memory access and restores the four original MSRs.

PC and Q35 each run six scenarios: actual syscall entry, stale old
value, noncanonical address, unaligned address, SCE already active,
and a malicious WRMSR deletion retaining the HIA readback. The latter
must return status 10, not false success. Exact object/linked ELF64/
bootable ELF32 text readback and independent GNU instruction oracle are
required. The positive scenario terminates inside the observer rather
than returning to user mode. The native entry trampoline, exception
recovery, IRETQ/SYSRETQ backend, selector setup, page ownership, CPU
resource authority, scheduling, and every Linux syscall ABI remain
unimplemented by this component. No full acceptance gate is credited.

The initial local authoring rejected reserved block names and an extra
terminal blank line; after correction the first shell-wrapped QEMU
probe timed out with no debug/trace output. The identical guest later
returned 33 with P using a direct subprocess; final local independent
PC/Q35 replay passed all twelve cases. Exact-candidate GitHub CI
must independently reproduce the result.
