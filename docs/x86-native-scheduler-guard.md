# Native scheduler stack guard page and IST fault containment (experimental HOLD)

The #230 separate scheduler stack is preserved at 16 KiB, with all three
16 KiB task stacks unchanged. A separate page immediately below the
scheduler stack is first identity-mapped and deliberately warmed; the
independent observer builds a 4 KiB leaf table and installs a dedicated
IST1 fault stack via the fixture TSS.

The HIA subject checks live CR3 and the admitted CR0.PG/WP and CR4 mode,
the five distinct aligned low pages, and each of the three live parent
entries with native identity CAS. It accepts only the fixed low identity
mapping with supervisor RW flags and the observed A/D variants. Native
leaf CAS changes the exact expected present PTE to zero, followed by
MFENCE and INVLPG. Misaligned address, wrong root, wrong table, stale
leaf and replay are rejected; the observer independently checks the
original and neighboring leaf.

The actual native IRQ dispatch runs with the distinct scheduler stack.
Normal short and long runs retain their original GPR/progress/lease
assertions. The overflow injection moves RSP to the exact lower boundary
and executes a real push. A real #PF is observed on IST1 with the exact
CR2 (scheduler_stack-8), RIP, supervisor write/non-present error 2, saved
RSP, CS and IF, active ISR and held scheduler lease; no target is published.
A mapped guard or deleted native INVLPG instead executes the push and
reaches the independent M sentinel. Deleting the parent CAS or leaf CAS
is independently detected as J. All 14 PC/Q35 cases passed locally on
the exact native object. Both empty-PATH compiles match. The original
196+26+56 cases remain in the new independent CI.

The first local observer incorrectly XORed the A bit of a dirty entry,
producing flags 67 rather than an admitted stale flags combination;
it failed J on both machines and is retained. The corrected basic
leaf-only candidate passed eight cases. Three attempted live-walk
versions failed native compilation (exit 2); splitting the range, parent,
and leaf helpers produced the final qualified native object. All rejected
source and logs are retained in the isolated work directory. No old
failures, budgets, locks or acceptance requirements were changed.

This is a fixed non-nested BSP and caller-owned identity topology.
The independent fixture sets up page tables, IDT, GDT/TSS and IST; it is
not a native implementation of those resource authorities. The native
walk is not a general mapping ownership proof, nor does it exclude
physical aliases or concurrent page-table mutation. The injected
overflow is an actual faulting push, not spontaneous production overflow.
The handler terminates the fixture; production fault/panic and arbitrary
CPU/NMI/CPL3/error-code/FPU paths, synchronous sleep/wake, native HLT,
SMP, cohort/reclaim, original post-IRET stale, full Linux ABI/VFS/storage/
network/security/drivers/architectures remain open. All 17 HOLD gates,
422 syscall obligations and original 3s/5s/60s budgets remain in force.
