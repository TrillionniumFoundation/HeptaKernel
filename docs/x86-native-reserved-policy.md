# Experimental reserved-idle topology (HOLD)

Parent: fb2ae62e6d7fbfda4c73fb7580d4087f9e63c555. The native entry accepts one bounded table (2..32 slots, last slot reserved for idle) and validates the bitmap before dispatch. Running preemption (reason 0) uses the inherited exchange with count minus one; running block (reason 1) uses the inherited idle-aware selection; idle wake/stay (reason 2) requires current to be idle. Cross-mode calls and any idle or upper ready bit are refused. Original policy and all inherited tests remain unchanged.

Independent observer: actual BSP IRQ sequence 0 -> 1 -> 0 -> idle2 -> 0, six delivered interrupts, four frame/owner switches, one no-wake idle stay. Two running tasks request blocking; progress of blocked tasks is checked, the idle HLT return is observed, only task0 is woken. Every native frame and owner transition has independent readback. Short/long pc/q35 positive cases and a wrong preempt-as-block native source mutant (I/35) pass. Host arithmetic/CAS oracle includes valid/stale/invalid masks and reason combinations; sequential calls are not SMP evidence.

Desktop qualification-r1: 90/90 scenarios (84 inherited + 6 added), 33602 reserved-policy calls. Two empty-PATH native builds byte-identical. The test now pins the observed native object hash. Local result is not independent CI. Assembly still orchestrates frame, owner, EOI, idle HLT and terminal return; no general transaction, resource authority, synchronous sleep syscall, arbitrary CPUs, or Linux acceptance. Original historical failures and all original gates remain open. No changes to production lock or main.

Native SHA256:
- source_sha256: 4205e25e5b1ebcf441fffb1c71597e178c650610a8be35eaf0211d6be027ba9b
- object_sha256: e673b2e97c1f5f937632a2ab7078e340b9a7dda10c249aa2fec2dd6eee287005
- text_sha256: 443f7233cf84ef7e10b57c621a876a0545a33d0025c57b9e50e5f05ac523d134
