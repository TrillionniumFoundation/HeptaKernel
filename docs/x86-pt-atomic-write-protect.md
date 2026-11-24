# Isolated HIA-native atomic PTE permission downgrade

This draft integrates the experimental Hepta selfhost compiler from exact
commit afa29e97aba26351d366f9ecded027e127e77427 (PR #944) in an **isolated**
qualification path only. The production HIA toolchain lock and all 17 full
acceptance gates remain unchanged. The genuine HIA source derives the
4 KiB PTE slot from a low identity-mapped, page-aligned VA, validates the
provided table address and CPU profile, admits only present writable NX
entries, clears RW while preserving all other 63 bits, uses a hardware
aligned 64-bit compare-exchange against the complete expected old entry,
then executes native MFENCE and local INVLPG only after success.
Stale expected-old, malformed addresses and unsupported profiles are
refused. No intermediate byte-store or host assembler is part of the HIA
implementation. The independent NON-HIA fixture discovers actual CR3 and
parent table links, warms the real 4 MiB write translation (including A/D),
then observes the exact supervisor write #PF (error 3, CR2, RIP and
unchanged bytes) or distinct refusal/bypass controls. The generated native
ELF text is checked before and after linking, with an independent GNU as
encoding oracle and a deliberately removed CAS instruction.

The table/VA authority, physical table ownership, CPU capability provenance
and live mapping relation are caller obligations, verified only by the
isolated observer in this experiment. The result is not a full SMP
shootdown, global reclamation, user-space mprotect or Linux ABI result.
No prior full-target obligation or syscall row is narrowed. This draft
requires fresh independent exact-head CI; no result is inferred from #944.
