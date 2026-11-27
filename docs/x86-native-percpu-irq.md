# Native simultaneous per-CPU IRQ scheduler stacks (experimental, HOLD)

Integrate the exact existing `x86.irq.dispatch_on_stack` native entry from
#230/#961 with live dense xAPIC descriptor admission from #236. Two actual
QEMU vCPUs each deliver two real local APIC self-IPIs. Their GS descriptors,
original task stacks and 16 KiB scheduler stacks are distinct. At the first
interrupt the independent observer has both CPUs meet inside the acquired
raw scheduler-stack interval: each checks the other's live held lease before
publishing its observation, and neither can leave until both observations
are published. The native raw entry alone saves registers, acquires/releases
the 0/1 lease, switches stacks and executes terminal IRETQ. The observer
only measures stack/frame placement and passes arguments to the native HIA
callback; it neither acknowledges the IRQ nor restores a frame.

The HIA callback preserves the descriptor admission helper of #236 byte for
byte, validates the actual live CPU/GS/callback/stack geometry and held raw
lease, reads the delivered vector's ISR bit, performs checked native EOI,
then advances a separate per-CPU IRQ epoch with exact CAS and returns the
original frame. Epoch slots at descriptor+1024 are disjoint from all 32
possible descriptors in the 4 KiB metadata page; the terminal all-ones epoch
is refused before EOI. These epochs are not the generation-bound lease of
#236: raw entry retains its old 0/1 lease ABI. No stack size was increased.

Independent assertions verify original frame and scheduler-stack addresses,
post-HLT RIP, six GPR sentinels, original RSP, live GS, both released leases,
per-CPU epoch 2, cleared ISR and metadata/canary isolation. PC/Q35 14/14 in
local focus-r3: positives (P/33), no epoch publication (C/35), no EOI and
injected wrong live GS or exhausted epoch (T/35 with exact native UD2,
held lease and active ISR), wrong returned frame after EOI/epoch commit
(F/35 with exact native UD2, held lease and cleared ISR), and GS-admission
bypass with injected peer GS (Y/35). The last control also demonstrates that
the old raw entry itself does not restore or recheck GS after an arbitrary
callback. Negative controls are serialized; only positives require simultaneous
residency. Synthetic epoch exhaustion is not a reset API. Native callback
and original entry objects are each compiled twice with empty PATH, then
linked text is compared byte for byte. Local r1 2/2 and r2 10/10 are retained;
r3 separates the full descriptor and epoch ranges and replaces the initial
fixture-specific bound of two with a non-wrapping u64 epoch. CI reruns all
378 inherited cases plus 14 new cases.

This is two real CPUs with same-frame interrupt restoration, not yet an
arbitrary-task SMP dispatcher or migration. The raw entry must still acquire
and release the generation-bound lease, enforce descriptor/mapping ownership
and post-callback GS invariants, integrate actual guard pages and synchronize
sleep/wake. The fixture uses caller-owned identity mappings and an assembly
AP startup/observation bridge. General CPU/page authority, nested/NMI safety,
error-code/CPL3/FPU context, and full Linux acceptance remain open. Production
mains, locks, 17 HOLD gates, 422 syscall obligations, original budgets and
all historical failures remain unchanged.
