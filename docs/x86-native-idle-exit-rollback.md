# Native idle exit rollback (experimental, HOLD)

The independent observer exercises the existing HIA native idle selector, bounded owner publication, guarded frame handoff and idle compensation on both entry and exit. After the second actual HLT, a native wake publishes task 0. The first exit attempt consumes its ready bit and transfers frames, but a stale owner publication is refused. The guard admits reversal; native reversal restores the parked task frame and the active idle frame. The native compensation restores the wake bit at a new generation, rejects replay, and the retry commits task 0. The independent observer checks the unrelated blocked slot, owner, switch count, ready word and task progress. An exit-only omission of reverse handoff must fail the unchanged readback on PC and Q35. All sixty prior scenarios are retained. This remains fixed BSP, caller-owned memory, nonnested IRQ, assembly orchestration and not an atomic multiword transaction. No acceptance gate or production lock changes.

## Local qualification

Exact compiler and inherited idle compensation object match parent. All 66 PC/Q35 cases passed, including 60 inherited cases and six new exit cases. Host calls: host_dispatch_calls=1100, host_compensation_calls=98219, host_running_block_calls=9512, host_idle_calls=10020, host_idle_compensation_calls=104587.

- ('idle-exit-rollback-short', 'pc', 33, 'P', 'bb1db0522902a3e7ead265fab208d202c0a5fa4df91d8b54f33449608e994402')
- ('idle-exit-rollback-short', 'q35', 33, 'P', 'bb1db0522902a3e7ead265fab208d202c0a5fa4df91d8b54f33449608e994402')
- ('idle-exit-rollback-long', 'pc', 33, 'P', 'dfe948397442995060469dddec99ad094fee0723a534615ddeb1c027f2f3915b')
- ('idle-exit-rollback-long', 'q35', 33, 'P', 'dfe948397442995060469dddec99ad094fee0723a534615ddeb1c027f2f3915b')
- ('idle-exit-rollback-skip-reverse', 'pc', 35, 'I', 'e8778ca28cd85838647ecbad9016546383f68a547defc819368006ffdb03cedd')
- ('idle-exit-rollback-skip-reverse', 'q35', 35, 'I', 'e8778ca28cd85838647ecbad9016546383f68a547defc819368006ffdb03cedd')
