# Native dual-CPU scheduler guard pages (experimental HOLD)

Integrate the exact #238 native generation-bound raw IRQ entry and HIA
callback with a two-leaf native guard revocation before AP startup. The
fixed low identity tree is checked with the #234 upper, huge and low
identity tests; the low scan now includes both guards. The second guard
is derived at first + 20480, checked against all table pages and the
adjacent APIC PD, and its exact present identity PTE is observed before
the first mutation. Both leaves are revoked with the existing native
exact CAS, MFENCE and INVLPG. First refusal changes neither leaf; a
second rejection after first success returns distinct status 10, not
success. This is not an atomic multi-leaf transaction or a rollback API.
All mutations occur before AP startup; no remote TLB invalidation
or exclusion of concurrent arbitrary table writes is claimed.

The independent observer builds the actual low 4 KiB table, warms both
physical guard pages, and then invokes the native guard routine. Two
actual vCPUs retain their separate 16 KiB scheduler stacks and exact
generation-bound IRQ entry, overlapping residency, two IRQs apiece and
terminal same-frame IRETQ. The normal case independently checks both
actual non-present PTEs, 512-byte canaries and final lease/epoch states.
Two independent actual page-fault probes, one per CPU, read its own
guard after two IRQs and require exact CR2, saved RIP, supervisor-read
nonpresent error code, live CPU identity and released lease/epoch with
ISR clear. These are task-stack fault probes, NOT scheduler overflow
or IST fault containment. The prior #231-234 IST tests are inherited.

A stale valid expected first PTE and a genuine second-leaf physical
alias both refuse with both leaves unchanged; the alias marker is
actually read through the alternate mapping. Independently compiled
deletion of either revocation leads to a real readable guard (M).
A wrong valid expected second PTE yields a real failed CAS, status 10,
first PTE zero and the second marker still readable.

Local PC/Q35 16/16 focus-r2, exact native source
40d608198c8af41314ed5a03da84e58183758abcc1e9e4cb5e262d49077b2b6e,
object 139d5374dc369edd78330d1f07f383d50f2d15418f59288f9948fbf2953c9d98,
text 284b0a2cd3fe74ab1ab334f6e5b07cde0822329a127cfcb108def5e8c8363d1b;
two empty-PATH rebuilds per object, linked text checked byte-for-byte.
Initial duplicate SSA native compile rejection preserved; initial test
link omitted irq_entry_end and is preserved. Direct shell QEMU launch
timed out while stopped; Python subprocess rerun of same image passed,
with real interrupt trace. No original oracle was loosened.
CI reruns all 414 inherited cases plus 16 new cases; independent
qualification remains pending.

Fixed two CPU fixture with caller-owned page tables and pre-AP
revocation only. Not general CPU/page ownership, concurrent table
mutation exclusion, post-AP shootdown/reclaim, NMI/IST/error-code
entry, FPU/CPL3, migration or Linux acceptance. Both production
mains, fixed target/toolchain locks, 17 HOLD gates, 422 original
syscall obligations, 3s/5s/60s budgets and all historical failures
remain unchanged.
