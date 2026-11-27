# Native reserved-topology compensation (experimental HOLD)

Parent: c16f8d6f27b9fcce2b8b69b021871c959dfc3d6c. The new HIA export accepts the single reserved-last-slot topology and reason (0 preempt, 1 block, 2 idle wake). It rejects cross-mode requests, no-transition cases, invalid ready bits, incorrect round-robin choices and exhausted generations. The inherited compensation bodies are retained byte-for-byte except private numeric function names; preemption restores the original bitmap after the exchange, while blocking and idle transitions restore it after removal of the selected bit (or the empty bitmap on entering idle). Exact CAS advances the generation a second time; stale/replayed compensation is rejected.

Independent actual BSP IRQ observer: four forward frame handoffs on 0->1->0->idle2->0 each encounter an intentionally stale owner, then a live-owner guard, native reverse frame handoff, rejected reverse-guard replay, reason-aware native compensation, rejected compensation replay, and successful retry. Checks both frame slots, exact ready words, prior owner, task progress, no-wake idle return, final ready generation 13 and owner generation 4. Six actual interrupts; four committed switches and four rollbacks; task1 remains blocked. Wrong compensation route and skipped reverse controls each reject I/35 on PC and Q35. The original 90 cases remain unchanged in this runner.

Desktop qualification-r1: 98/98 PC/Q35 cases (90 inherited, 8 new), 89906 new host compensation calls, including sequential stale/replay and incorrect selected task controls. Host calls are not SMP evidence. Two empty-PATH native builds identical. Subsequent test pins the observed native object hash. Independent CI remains necessary.

Not a complete native dispatcher: the observer still orchestrates ready selection, frame handoff, owner publication, compensation and HLT. No general atomic multiword transaction, authority, synchronous sleep syscall, arbitrary CPU, or full Linux acceptance is claimed. All historical failures and original 17 HOLD gates/422 syscall obligations and original budgets remain unchanged. Both main branches and production lock unchanged.

Native SHA256:
- source_sha256: 8e43fbaf77f5645dfd464d02aaf94e35d89243190c2cb281c80c3f8cb83705da
- object_sha256: 31f3b97d3d07837e095a403261c18f5151e84774652dd8123892551d4baff1d0
- text_sha256: 535e698a175e58f9d7233074108f9032e12b7d03bcece310d62c06524b066d93
