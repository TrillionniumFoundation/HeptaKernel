# Experimental deferred running-task block and wake (HOLD)

The native block selector claims the next eligible peer from a versioned
32-bit ready bitmap without requeueing the departing task. With no eligible
peer it validates the live word with identity CAS and returns 64 without a
state change; it does not implement entry to idle. Invalid inputs return
65; stale exact words return 66. The caller still owns resources.

The independent three-task BSP observer adds a task-1 request written by
task 1 itself after checking all 15 GPRs, observed at IRQ 2. The native
block selector omits task 1 from the ready bitmap. The observer verifies
that task 1 makes no progress before the native wake publisher at IRQ 5,
and that task 1 resumes and progresses afterward. The observer retains
exact slot, owner, generation, register, stack and switch checks.
The erroneous native requeue variant must produce K on PC and Q35.
The original 32 rollback cases remain in the new test, with the previous
test unmodified. The added six cases exercise short/long positive and
requeue negative on both machines. The independent host oracle performs
9512 native calls including no-peer, stale word, width and overflow cases.

This is a deferred request handled by the next designated timer IRQ,
not a synchronous sleep syscall. Fixed BSP, non-nested IRQ, caller-owned
frames; no general multiword transaction, blocking rollback, idle
transition, resource authority, SMP or Linux acceptance claim.
