# Native compensation for idle selection before owner commit (experimental)

New real HIA f0 computes the exact prior selection using the same bounded
round-robin rule, rejects an out-of-range/current/idle ready bit, a wrong
selected task, an idle no-peer non-transition and insufficient generation
room. It reconstructs the expected post-selection word and uses one exact
locked CAS to restore the prior bitmap with generation advanced again.
It refuses stale state and replay without mutation. This is a ready-word
compensation primitive, not a multiword transaction.

In the actual PC/Q35 observer, IRQ 2 performs the last runnable task's
forward frame handoff to idle, then deliberately attempts stale owner
publication. The native owner refuses; the native rollback guard admits
the live state; the existing native frame handoff reverses the slots.
The guard refuses replay after reversal. The new native compensation
restores the empty bitmap with generation 3, refuses stale replay, and
the original native selector retries, reaching generation 4 and idle.
The next IRQ has no wakeup, returns the same idle frame, and the next
wakes task 0. Final ready generation 6, owner generation 3, five IRQs,
three actual switches, one idle stay and one rollback. Task 1 stays blocked.

A compiled source mutant fails to advance the rollback generation and is
detected by the independent hardware oracle on both machines. All 54
#214 cases remain in the expanded suite. Host oracle covers entering idle,
ordinary selection and selection from idle, stale generations, wrong
selection and bound/overflow rejection; it is sequential, not concurrent.
The actual frame rollback test is entry to idle only; leaving idle has
host arithmetic/CAS evidence only. No post-owner-commit rollback, general
atomicity, resource authority, native HLT, general dispatcher or SMP claim.
Original historical failures and all Linux HOLD gates remain unchanged.

Desktop qualification: 60/60 PC/Q35.

Host idle compensation calls: 104587

Native object identity:

```json
{
  "source_sha256": "2d86d0581211522e9b1935f80dfbb89b8edb3d644b5da4ddb51984be906025aa",
  "object_sha256": "c4975cb6f2b4af844e25c01d9d8b35e7d23fd7872a52bb86f98812ed2a842509",
  "text_sha256": "b24fd81ce03ce00621b9198d0dded72f8f29c34006d75924d2f3fa4024736196"
}
```
