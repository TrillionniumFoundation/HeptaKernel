# HIA-native x86-64 SYSCALL entry MSR admission (restricted profile)

`src/x86_syscall_msr_admit.hepta` is genuine upstream Core v8
`selfhost_elf` source. The pinned compiler builds `syscall_msr_admit` as
freestanding x86-64 native code without a C/assembly implementation.

The function accepts four **caller-provided snapshots** of IA32_LSTAR,
IA32_STAR, IA32_FMASK and IA32_EFER. Its exact restricted policy is:

* LSTAR points to canonical high-half virtual addresses
  `[0xffff800000000000, 0xfffffffffffff000)` (excluding the final page).
  CPU page-table access/executable permission is **not** established.
* STAR equals `0x0030000800000000`, selecting ring-0 CS 0x08 for
  SYSCALL and the installed SYSRET64 user CS 0x43 / SS 0x3b. This is
  the isolated GDT fixture, not the general Linux selector layout.
* FMASK includes TF, IF, DF, IOPL, NT and AC
  (`0x47700`), without forbidding additional masked bits.
* EFER includes SCE, LME, LMA and NXE (`0x0d01`), allowing other bits.
  NXE and the high-half restriction are policy requirements of this
  narrow 48-bit, four-level, NX-enabled profile, not ISA-wide necessities.

Return code 0 admits the supplied tuple; 1 rejects LSTAR, 2 rejects STAR,
3 rejects FMASK, 4 rejects EFER. The order is deterministic. This
selfhost-generated code **does not** execute RDMSR/WRMSR, SYSCALL, SYSRETQ,
read CR3, verify MSR provenance, establish kernel/user page separation, or
implement any Linux syscall. It cannot prevent a caller from changing any
MSR after checking. Neither the non-HIA bridge nor the complete 17-gate
coverage ledger is reclassified as HIA-native by this addition.

`make test-x86-syscall-msr-admit` compiles the real and separately HIA-built
dishonest all-admit programs, runs the independently derived bit-precise
Python oracle, rejects the dishonest version, compares object and
shared-library `.text`, and checks two empty-PATH compiler builds against
the candidate object. The full `make test` and Foundation CI invoke this gate
without altering `make full-acceptance` exit-2 HOLD semantics.

Next required work: an upstream HIA privilege/effect model and
`selfhost_elf` RDMSR/WRMSR/SYSCALL/SYSRETQ backend; independently captured
MSR and live GDT readbacks; kernel-high-half mapped executable entry
pages; actual hardware SYSCALL->handler->SYSRETQ state restoration; syscall
dispatcher, thread ownership, SMP, security, and complete Linux ABI tests.
