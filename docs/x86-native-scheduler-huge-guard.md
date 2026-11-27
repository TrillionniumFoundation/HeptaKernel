# Native sibling huge-page identity admission before scheduler guard revocation (HOLD)

Retain #232 exact live parent walk and low-leaf identity scan, exact leaf CAS,
MFENCE and INVLPG. After validating the low PD parent, native f5 checks each
of its other 511 PDEs for the prescribed 2 MiB identity physical base and
supervisor RW PS flags (131, 163, 227) with identity CAS. This rejects both
a huge alias of the low physical range and a different topology; it does
not authorize concurrent mutation or claim global physical alias freedom.

The independent observer installs a real 2 MiB mapping of physical zero at
VA 2 MiB, reads the guard marker through that alternate address, requires
status 6 without revoking the guard or changing the alternate physical base,
restores the original PDE and invalidates the alias. Independent deletion
of the new CAS must produce J/35. All inherited low-leaf, fake-parent,
leaf CAS, INVLPG and actual IST fault controls remain. Focus-r1 exposed a
masked INVLPG deletion (Q/35 instead of M/35); the additional huge-page
invalidation can evict the warmed guard. Focus-r2 explicitly rewarmed the
original guard mapping before revocation, with the same native subject and
unchanged expected outcomes.

Focus-r2: 18/18 PC/Q35, two empty-PATH native builds.
Source 2d829c2413c52797b4c33837c74062b8817a331c2bafd8537d946bcdadb73f74,
object 58a99b3153ff8e80ba00db698d505a0f043034ad5cd2c53af3a4e77c89b9a96a,
text 19165d38cad57044fca5f347846aad4611653c7c4ab259d33403d2f840f4ba3c.
Independent CI must rerun 196+26+56+14+16 inherited cases and the 18 new cases.

Fixed BSP, first 1 GiB directory only. Other PDPT/PML4 branches, page-table
ownership and concurrent mutation, arbitrary per-CPU authority, NMI/error
code/CPL3/FPU/GDT/TSS, synchronous sleep/wake, native HLT, general SMP/cohort/
reclaim/post-IRET stale, and full Linux ABI/subsystems remain open. Preserve
all 17 HOLD gates, 422 obligations, 3s/5s/60s budgets, both main refs, production
lock and historical failures.
