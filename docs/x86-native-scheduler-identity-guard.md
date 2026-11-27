# Native low-leaf identity admission before scheduler guard revocation (HOLD)

The existing #231 live parent walk, leaf CAS, MFENCE and INVLPG remain
unchanged. A new native bounded loop, after the live walk and before the
leaf update, visits every other index in the first 512-entry 4 KiB leaf
table, checking exact identity physical address and supervisor RW flags
(3, 35 or 99) with an identity CAS. The guard index is left to the original
exact CAS; this preserves stale and replay semantics. This is a fixed,
non-nested BSP admission check, not a concurrent global page-table
ownership proof. No general alias proof is claimed outside this table.

The independent observer installs a genuine alternative mapping at
VA 0x1ff000, reads the guard marker through that mapping, requires rejection
without revoking the guard or changing the alternative mapping's physical
address, then restores the original leaf and invalidates that VA.
The original normal, actual fault, mapped-guard, missing-parent,
missing-leaf and missing-INVLPG controls are preserved; a new independent
machine-code deletion of the scan CAS must be detected. A valid-looking
but unlinked clone of the live leaf table makes the parent-walk control
independent of the new scan.

Exact local focus-r3: 16/16 PC/Q35 scenarios, two empty-PATH builds,
source 75880bf0e5ee7260af240794fa3da08c08613f2fccba664e7163bb51a6437df4,
object 707b4e5c077c599cae7581bc87532c56f3ac749731820ddb4dd48a41c0bcbbda,
text ba25fcefe112673fafcea16384ffb414bcd7424c230d9677b1a661f82cea5205.
Focus-r1 exposed a real masked negative control: the new scan also
rejected the invalid table, so the parent-CAS deletion passed. It is
retained; the clone probe separates the two checks. Focus-r2 had an
assembly source newline escape error; it is retained and fixed in r3.
No native subject or acceptance thresholds were changed between runs.

Independent CI must rerun all 196+26+56+14 inherited scenarios and the
16 new scenarios. Remaining: global physical aliases, page-table
ownership and concurrent mutation, arbitrary per-CPU resource authority,
NMI/error code/CPL3/FPU/GDT/TSS, synchronous sleep/wake, native HLT,
general SMP/cohort/reclaim/post-IRET stale and complete Linux ABI and
subsystems. The 17 HOLD gates, 422 obligations, original 3s/5s/60s
budgets, both mains, production lock and historical failures remain.
