# Native bounded frame composition (experimental HOLD)

Parent: 71e6cf49e524f635ae38b6aec88470f930c9de90 (#219). The new HIA export accepts the slot table, a packed bounded topology (6-bit count, 5-bit departing ID, 5-bit selected ID), the two expected frame addresses and explicit stack tops. It rejects extra packed bits, invalid counts/IDs, same ID, unaligned/empty/overflowing table, and table overlap with either caller-owned stack interval. The native resolver checks the exact live parked frame, then the native frame transaction derives the departing slot from the same table and parks/consumes or reverses on failure. Inherited resolver and three frame functions are included byte-for-byte except private numeric function renames, verified by the test. This is not a lock, resource authority, general scheduler, or a multiword transaction.

The independent mixed IRQ observer retains all original slot, owner, ready, generation, rollback and replay checks. For each actual forward attempt, it additionally demands refusal of a valid in-stack but stale target, an out-of-range packed topology, and a table crossing 1 GiB, with unchanged slots and ready word. Both forward and guarded reverse transfers use the new single HIA export. The same four committed switches, four reversed attempts, no-wake idle return, final ready generation 13 and owner generation 4 remain required. Two independent native source controls (bypass resolver and alias source/target slots) fail H/35 on both PC and Q35. The original 98 scenario records, including exact image hashes, are identical to the parent local report. New object is not linked into inherited scenarios.

Desktop qualification-r1: 106/106 PC/Q35 (98 inherited + 8 new), both empty-PATH native compilations byte-identical; all inherited host oracles retained. No new host oracle or SMP claim. Independent CI required. All historical failures, original 17 HOLD gates/422 syscall obligations, original 3s/5s/60s budgets, both main branches and production toolchain lock remain unchanged. The observer still orchestrates policy/owner/compensation, and stack tops are caller-owned. No synchronous sleep, native HLT, arbitrary CPU or complete Linux acceptance claim.

Native SHA256:
- source_sha256: 446e073f61cd68dd1b9b126f09a5a0b1f05d6c7456f7e53dc07d87911f1fe3d0
- object_sha256: 3f6834d41ee0f45bc5cede14da7e2db34823a2464c65903056ac07014da56b79
- text_sha256: 051b2cebb529b406c2677140b35c59df9811257ce11047448cf176114c1201d8

New scenario results:
- bounded-compose-short pc: P/33 image e517c6730de285ce11ab684fe2b132c09041d4cc08fdec20536f905228c1b054
- bounded-compose-short q35: P/33 image e517c6730de285ce11ab684fe2b132c09041d4cc08fdec20536f905228c1b054
- bounded-compose-long pc: P/33 image 2f014dac3e3855a10f38e4698db88d4163bc7352c3f856516443fa4269713607
- bounded-compose-long q35: P/33 image 2f014dac3e3855a10f38e4698db88d4163bc7352c3f856516443fa4269713607
- bounded-compose-bypass-resolver pc: H/35 image 9aa67e40db4e68a2c1b1be7f277de29460c773dd2d850b9bdb926ac07236772f
- bounded-compose-bypass-resolver q35: H/35 image 9aa67e40db4e68a2c1b1be7f277de29460c773dd2d850b9bdb926ac07236772f
- bounded-compose-alias-slots pc: H/35 image 9ba95bd16f11811b7019a9ac1d626d29095964f7a1ba5e675e0168fa727aa1f6
- bounded-compose-alias-slots q35: H/35 image 9ba95bd16f11811b7019a9ac1d626d29095964f7a1ba5e675e0168fa727aa1f6
