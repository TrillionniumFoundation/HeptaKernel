# Native idle selection and timer wake (experimental)

This candidate reserves the final table index as the idle context (2–32
entries including idle). The ready bitmap must exclude idle and current,
and all higher bits. The native selector claims a peer without requeueing
the outgoing context, or commits an empty bitmap with an incremented
generation and returns the reserved idle index. An already-idle empty
request uses an exact identity CAS and returns 64; malformed/overflow
and stale requests return 65 and 66. This interface is for blocking or
idle departure, not normal runnable preemption.

In the independent PC/Q35 observer, task 0 and task 1 request blocking,
then the last runnable task switches into a distinct idle stack. The
observer executes HLT with IF set. The next timer IRQ must capture the
exact post-HLT RIP, exactly one idle-loop iteration and unchanged
progress for both blocked tasks. It publishes task 0 through the existing
native ready publisher; native idle selection claims it without adding
idle to the bitmap. Native frame handoff, owner CAS, raw IRQ and IRETQ
remain in the actual path. Task 0 must subsequently progress while task
1 remains blocked. Four interrupts and three switches are required.
Wrong empty-generation advancement and skipped HLT are independent
negative controls. The original running-block test is retained, and
its 38 scenarios are also exercised by the new test.

Scope: fixed BSP, non-nested, caller-owned resources and independent
assembly observer including HLT and scheduling calls; no native HLT
lowering, autonomous wait queues, general SMP, transaction, or idle
rollback claim. The already-idle no-peer case is host-tested, not
an additional actual IRQ path. The existing Linux acceptance matrix,
compiler production lock and timeout thresholds remain unchanged.
