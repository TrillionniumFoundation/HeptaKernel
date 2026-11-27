# Native running-block compensation after refused owner publication

Experimental candidate; full Linux acceptance remains HOLD. The native running-block
operation removes the selected peer without requeuing the departing task. The
ordinary runnable-exchange compensation cannot be used for that different bitmap
transition. The new HIA function checks the bounded table count, distinct task
indices, aligned low canonical slot, ready width, absent departing bit, present
selected bit, and room for two generation increments. It derives the exact
post-block word and CAS-restores the original bitmap at generation +2. A stale
word refuses without a write.

The independent PC/Q35 observer retains all 38 running-block and inherited
hardware scenarios. At IRQ2, after task1 requests a block and the real native
block and frame handoff have run, the observer submits a stale owner publication,
verifies refusal, validates the rollback guard, reverses the frame handoff,
compensates the ready word with the block-specific native function, checks replay
refusal and retries the block. No blocked task executes before the native wake.
The final generation is independently checked. Additional controls omit the
reverse handoff, corrupt the compensation bitmap, or refuse a reverse consume
after reverse park, and check fail-stop before EOI/IRET. The host oracle exercises
the new native operation and actual native block/compensation composition.

Scope: fixed BSP, non-nested interrupt gate, three CPL0 tasks, caller-owned stacks
and table, independent assembly dispatch observer. This is a compensation path
before owner publication, not a general multiword transaction, not concurrent
resource ownership, not synchronous sleep, not an actual idle transition and not
SMP. Identity CAS is not a lock. Original acceptance obligations, negative
controls and toolchain production lock remain unchanged.
