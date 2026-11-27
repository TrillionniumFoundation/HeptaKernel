# Native upper-tree alias admission before scheduler guard revocation (HOLD)

On the fixed four-level BSP identity topology, preserve #233's live parent
walk, low 4 KiB and sibling 2 MiB identity checks, exact leaf CAS, MFENCE
and INVLPG. New HIA f6 requires exact zero in every otherwise unused slot
of PML4, PDPT and the APIC PD. f7 checks the fixed adjacent APIC PD address
(pd0 + 4096) for alignment, extent and disjointness from root, PDPT, PT and
guard page, binds PDPT[3] to that table via f1, and admits only the expected
UC APIC huge leaf at index 503 (0xfee0009b, accessed/dirty variants). All
checks occur before guard leaf revocation. This covers the prescribed
current page-table tree; it is not general page-table authority, a proof
against cached aliases, or atomic exclusion of concurrent writers.

Independent actual alias probes map the same guard physical marker via
PML4[1], PDPT[1], PD3[0], and an altered APIC PDE. Each reads the marker
through the new virtual address, requires status 6 and unchanged guard
leaf/alias physical base, restores the entry and invalidates the alias.
Separate machine-code CAS deletion controls for f6 and the APIC leaf both
produce J/35. Existing low-leaf/huge alias probes, stale and fake-table
rejection, precise IST overflow #PF, mapped control and deletion of
parent/leaf/scan/huge CAS and INVLPG remain intact.

Local focus-r1: 22/22 PC/Q35, two empty-PATH builds; original 16384-byte
scheduler and task stacks unchanged. Initial HIA duplicate SSA in upper
block rejected with exit 2; retained rejected-r1.hepta locally and renamed
only that block's bindings. Exact source decfc916e64e70ddb6e5209e3f1ad5d410aeb38ddb8e47ee7ffd1664916bcaf3,
object c5853e7a8c743183069ba46a2848b9b900adefa79ef8b0072fae03e7ee38259f,
text 1f7a54aabbc22c6806bc93511c4178fe5add03003b299520265112b7a0e4a0f2.
Independent CI must rerun all 196+26+56+14+16+18 inherited cases and
22 new cases; local evidence is not independent CI.

Still fixed BSP, non-nested, fixed identity topology and caller-owned
tables. General page ownership, concurrent mutation, arbitrary per-CPU
resource authority, NMI/error code/CPL3/FPU/GDT/TSS, synchronous sleep/wake,
native HLT, SMP/cohort/reclaim/post-IRET stale and full Linux ABI/subsystems
remain open. Preserve 17 HOLD gates, 422 obligations, original 3s/5s/60s
budgets, both main refs, production lock and all historical failures.
