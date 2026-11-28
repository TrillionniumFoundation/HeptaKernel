# Native independent scheduler stack (experimental, HOLD)

Preserve the old #229 196 inherited and 26 new cases. Use the new upstream
native x86.irq.dispatch_on_stack() operation rather than the original raw IRQ
gate. No assembly callback stack pivot is added. Task stacks remain 16 KiB;
the observer provides a distinct 16 KiB scheduler stack and caller-owned GS
descriptor. The original hardware integer frame remains on the interrupted
task stack; native raw entry passes it to the bounded dispatcher on the
separate stack. Independent observation verifies actual callback RSP equals
scheduler_top-8, lease=1, task GPRs and progress, and lease=0 on normal return.
Linked stack intervals, exact native machine code and the original dispatch
bound plus 512-byte overhead and 512-byte canary are checked.

Final exact local candidate: 56/56 QEMU PC/Q35 cases, including normal short
and long, invalid bounds, overlap with interrupted frame, busy lease, pre/post
canary faults, transient-stack return pointer, stale release, deleted stack
switch/acquire/release, five actual control-word corruptions after the
bounded dispatcher returns successfully, and eleven original rollback/fatal/
frame controls through the separate stack. Exact #UD RIP/instruction,
IF, APIC ISR, owner/interrupt count and lease are independently checked.
Selected control-word checks precede release. Only native terminal restore
follows release. The first hardware oracle revision rejected the legitimate
new RSP comparison; the final oracle verifies its exact linked operand and
preserves original stack-operation checks. The final declaration requires
atomic, the native object and all 56 images match the prior full pass, and
the final exact candidate was rerun. Earlier failures are retained.

Still fixed non-nested BSP, caller-owned descriptor/mapping/callback; canary
is not a guard page, virtual disjointness is not physical-alias proof. Arbitrary
per-CPU assignment, concurrent CPU authority, guard/page ownership, generic
fault/panic handling, NMI/error-code/CPL3/FPU/GDT/TSS, synchronous sleep/wake,
native HLT, SMP, cohort/reclaim, original post-IRET stale and complete Linux
ABI/VFS/storage/network/security/drivers/architectures remain open. Historical
A/37 and the #228 cross-stack write remain distinct evidence. No original
17 HOLD gates, 422 syscall obligations, 3s/5s/60s budgets, locks or main change.
