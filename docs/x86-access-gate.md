# HIA native x86-64 access admission

`src/x86_access_gate.hepta` is directly compiled to native x86-64 by the
locked HIA Core v8 `selfhost_elf` compiler. Its exported scalar SysV ABI is
`x86_access_admit(mapping, intent, cr0, cr4, efer) -> u32`.

`mapping` is the 64-bit native result of the existing HIA 4-level translation
policy: bit 63 is the valid tag, bit 62 effective RW, bit 61 effective U/S,
bit 60 effective executable, bits 51:0 the physical address. Bits 59:52
are reserved and must be zero. The source deliberately does not accept
raw PTEs as a substitute for the independently verified page walk.

`intent` uses bit 0 for CPL3 (otherwise CPL0), bit 1 for write, bit 2 for
instruction fetch, and bit 3 for EFLAGS.AC (SMAP override on supervisor data
access). Writes and instruction fetches cannot be requested simultaneously.
All higher bits are invalid. CPU state is caller-supplied and must be measured
by a trusted privileged caller at the same quiescent epoch as the page walk.

Return status: 0 allow; 1 invalid mapping; 2 malformed intent; 3 incompatible
long-mode CPU profile (PE/PG, PAE, LME/LMA, PCIDE/LA57); 4 CPL3 accesses a
supervisor page; 5 write denied by effective RW and WP/CPL; 6 NX fetch denied;
7 SMEP denies supervisor fetch from a user page; 8 SMAP denies supervisor
data access from user memory without AC; 9 recorded NX without EFER.NXE.

The kernel must still implement **privileged HIA** CR3 read/write, TLB shootdown,
hardware page-table ownership, bounds and source provenance, NXE/SMEP/SMAP CPUID
support and coherent CPU snapshot sampling. The HIA page-walk access flags are
a *policy model*, not a hardware authorization or source of authority.
Firmware/MTRR/EPT, PKU/PKS, CET, shadow stacks, and Linux-specific
fault/recovery semantics are not represented. The CR4 privilege input can be
forged by an untrusted caller. No current 17-gate closure or 422 syscall
obligation changes.

`tests/test_x86_access_gate.py` checks native machine code against an
independent declarative oracle, exhaustively tests an access/mode/flag matrix,
includes randomized invalid cases and links the translation output from
`src/x86_walk4_physical.hepta` to the native access gate. Its malicious
HIA all-grant negative control must be rejected. The object/shared `.text`
bytes are compared, and all test results are tied to the exact candidate.
