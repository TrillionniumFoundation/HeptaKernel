# Native per-CPU generation-bound descriptor lease (experimental, HOLD)

The native HIA implementation preserves the live dense xAPIC identity,
GS binding, exact slab geometry and three descriptor-word comparisons
from PR #235. The single exported f1 takes the expected lease word and
explicit operation (0 acquire, 1 release). Even words are free, odd
words held. A locked exact CAS advances by one; stale, duplicate,
wrong-operation and invalid descriptor calls return zero. The last even
word is retired and the final odd word rejected, so no successful acquire
issues an unreleasable token. This assumes immutable descriptor geometry
and cooperative ownership, not exclusion of arbitrary metadata writes.
This is not the existing raw entry's 0/1 lease ABI and is not wired to it.

An independent observer starts two real QEMU vCPUs, released by one
shared start flag. Each acquires, rejects duplicate and wrong-operation
calls, releases, rejects stale release, checks wrong peer GS and corrupt
callback, then performs a second cycle. Both finish with word 4 and an
intact adjacent marker. Terminal-generation probes are explicitly
synthetic injections, not a reset API. Six independent source mutants
check the transition, stale comparison, parity, exhaustion, GS binding
and callback comparison. Both empty-PATH compiles match; linked native
text is byte-checked. Local r2: 14/14 PC/Q35, including dual-CPU positives.

r1 rejected all-ones but wrongly admitted the final even generation.
The r2 observer on the original r1 object gives W/35 on both platforms
with serialized negative controls; an earlier concurrent replay emitted
WW/35. Rejected files and reports are preserved in the isolated directory.
The new workflow reruns 364 inherited cases plus 14 new cases.

No general CPU/page authority, same-slot contention, concurrent metadata
mutation exclusion, scheduler stack switch, migration, NMI safety,
guard revocation or full Linux acceptance is claimed. Next integrate
the generation-bound lease with real native IRQ entry and terminal
restore on both CPUs, stable mappings and descriptor ownership.
Both production mains, locks, 17 HOLD gates, 422 syscall obligations,
original budgets and historical failures remain unchanged.
