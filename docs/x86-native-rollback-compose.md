# Native guarded reverse and ready compensation composition (experimental HOLD)

Parent: 58f8afa526813795b8c06568a474095c24206962 (#221). The new HIA export combines the inherited owner-guarded reverse frame transfer with reason-aware ready-word compensation. Six packed scalar arguments encode owner/topology/reason, prior owner, table/ready addresses, source/target frames, stack tops, and prior ready word. It rejects an out-of-range or unaligned ready cell, alias with the owner or bounded slot table or either participating stack, and reasons outside 0..2 before reversal. It propagates reverse refusal without compensating. If reversal succeeds but ready compensation fails, it returns a distinct fatal 67: the frame has already been reversed and the caller must fail-stop, not retry or restore another context. This is not atomic across multiple words, and other stack/resources remain caller-owned.

In the actual mixed IRQ observer the four owner-refusal rollbacks (preempt, block, idle entry, idle exit) now use the same native export for both reversal and ready compensation. All original independent frame, owner, ready-generation, retry and no-wake checks remain. The new owner/ready alias refusal and combined replay refusal precede retry; the original separate stale compensation probe is retained. Two independent source mutants skip reverse or skip compensation and must fail I/35. A separate actual stale-ready injection increments the ready generation after forward handoff: it demands 67, exact reversed slots, unchanged owner and unchanged injected ready word, then terminates with Z/35 without retry. Both PC and Q35 must observe this dedicated outcome.

Desktop qualification-r1: 124/124 PC/Q35 (114 inherited, 10 new), both empty-PATH native compilations byte-identical. All first 114 scenario records and inherited object metadata are identical to the local parent report. All inherited host oracles retained; no new host-concurrency or SMP claim. Independent exact-head CI required. The caller still orchestrates forward policy/frame/owner and eventual EOI/IRET; no general scheduler, synchronous sleep/wake, native HLT, arbitrary CPU, resource authority, or full Linux acceptance claim. Original 17 HOLD gates/422 syscall obligations, 3s/5s/60s budgets, production lock, both mains, and historical failures remain unchanged.

Native SHA256:
- source_sha256: 29a4af1ba4fa5990c458aff69fa18186fb6b121aa6f87955c6932eed37cc5b0a
- object_sha256: 330e79fd27b989148661d451e5d396b0758134c659c97ccddf9f2d8463e55d04
- text_sha256: 42b5443f6fd93cccae83a1c561dd2cafd95ddf057259c3c967a72da11441c584

New hardware results:
- rollback-compose-short pc: P/33 image d10cfcb223fa6ffb429a948c4ace43a4ce0e7e955df6cd17f70efeefd461a264
- rollback-compose-short q35: P/33 image d10cfcb223fa6ffb429a948c4ace43a4ce0e7e955df6cd17f70efeefd461a264
- rollback-compose-long pc: P/33 image 4bb7da956c9e74c7467fdc0ddaff5408db891fdb1bf82953070a4f9af865031e
- rollback-compose-long q35: P/33 image 4bb7da956c9e74c7467fdc0ddaff5408db891fdb1bf82953070a4f9af865031e
- rollback-compose-skip-comp pc: I/35 image a130b8edc4c857d6d22577a5c0aeea6ee73fdacb21bf0a04c58a9918110f021c
- rollback-compose-skip-comp q35: I/35 image a130b8edc4c857d6d22577a5c0aeea6ee73fdacb21bf0a04c58a9918110f021c
- rollback-compose-skip-reverse pc: I/35 image b0a96058614d9dc76d43f945d50a6a2a8c4aa59bc9104df91834989d6fc595cf
- rollback-compose-skip-reverse q35: I/35 image b0a96058614d9dc76d43f945d50a6a2a8c4aa59bc9104df91834989d6fc595cf
- rollback-compose-stale-ready pc: Z/35 image 30785f287f7d7377dc5bdefafc15b3d7af85040bfb3039b280b18ba486ce4a97
- rollback-compose-stale-ready q35: Z/35 image 30785f287f7d7377dc5bdefafc15b3d7af85040bfb3039b280b18ba486ce4a97
