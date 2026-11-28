# Native dispatch policy composition (experimental, HOLD)

A single native HIA export accepts a versioned ready word and a scheduling reason. Reason 0 implements ordinary preemption and requeues the current runnable task; reason 1 implements deferred running-task blocking with peers and does not requeue; reason 2 uses the distinct reserved-idle table contract and handles last-runnable blocking, no-wake idle return, and wake claim. Other reasons return 65 before touching the slot. Existing native function bodies are included byte-for-byte apart from numeric function-symbol renaming, checked independently in the harness.

The two actual IRQ observers call the same new native export for each corresponding path. The independent assembly retains its previous frame, owner, ready-generation, register, stack and progress checks. Three separately compiled wrong-route controls must produce the original failure markers X, K, I on both machines. No original test, lock, budget or acceptance gate is changed.

Local exact-compiler qualification: 84/84 PC/Q35 scenarios, 66 inherited and 18 additional (12 positive and 6 wrong-route controls). The independent host oracle executed 45,391 calls, including stale-word rejection, malformed reasons, boundary masks, generation overflow, and canaries. The two empty-PATH native compilations are byte-identical. Earlier preparation rejected the exchange source header exports(f0,f1); the preparation script was corrected, not the compiler or oracle.

This is one native ready-policy entrypoint, not a unified end-to-end dispatcher. The caller still chooses the reason and topology; reasons 0/1 use a table with no reserved idle task, whereas reason 2 uses a final reserved idle index. Frame handoff, owner publication, compensation sequencing, EOI, and HLT orchestration remain separate; the observer is fixed BSP, nonnested, caller-owned. Neither SMP nor general resource authority nor complete Linux acceptance is established.

Native policy hashes (SHA-256):

- source_sha256: b3c9d577adf158eb374c828924a51ee87ddb748c0dc399dfd409787a06a7f69d
- object_sha256: 7fd1abb8efca9fe2a0d83a4ae3c62c2958ee12bdf982f5bf3124db082558028b
- text_sha256: b4490f043a4b3a60fb5056df7354dda82f29c0385cf297590488ae9e59f09221

New hardware results:

- policy-preempt-short pc: P/33 image 8899900f67e9934bbaae7248575182209a43032d07f29c72e3713ec822342590
- policy-preempt-short q35: P/33 image 8899900f67e9934bbaae7248575182209a43032d07f29c72e3713ec822342590
- policy-preempt-long pc: P/33 image 67e0ff235d322fec8e917953768f593dd8d2c994ec2a9dd5ab30fb4daff399a9
- policy-preempt-long q35: P/33 image 67e0ff235d322fec8e917953768f593dd8d2c994ec2a9dd5ab30fb4daff399a9
- policy-block-short pc: P/33 image 3a74544cdc0018189b3e1e8b95258b40645241fb8e9c855bddd2e925e528e02a
- policy-block-short q35: P/33 image 3a74544cdc0018189b3e1e8b95258b40645241fb8e9c855bddd2e925e528e02a
- policy-block-long pc: P/33 image 08e3f2eb8384b4077288d71b55559b999df928d0a62a36419d09382132405518
- policy-block-long q35: P/33 image 08e3f2eb8384b4077288d71b55559b999df928d0a62a36419d09382132405518
- policy-idle-short pc: P/33 image 99790eedd2a78bcce719a2cbe0ac0a27e8141dcf1ffb02945a2d8f55a30ad10b
- policy-idle-short q35: P/33 image 99790eedd2a78bcce719a2cbe0ac0a27e8141dcf1ffb02945a2d8f55a30ad10b
- policy-idle-long pc: P/33 image 22edb308eae45721e75693f7b33db90f3a968599ef655049c9304521014911f2
- policy-idle-long q35: P/33 image 22edb308eae45721e75693f7b33db90f3a968599ef655049c9304521014911f2
- policy-idle-as-block pc: I/35 image 963446e3f7001ded6ff8b2ff2c76e6e6332ea5e1f9300c27f8e39482ded851e2
- policy-idle-as-block q35: I/35 image 963446e3f7001ded6ff8b2ff2c76e6e6332ea5e1f9300c27f8e39482ded851e2
- policy-preempt-as-block pc: X/35 image 9cdcd8e122270becec935c47f3a32d3dd2c222357e296b0c02d47c149ac936d6
- policy-preempt-as-block q35: X/35 image 9cdcd8e122270becec935c47f3a32d3dd2c222357e296b0c02d47c149ac936d6
- policy-block-as-preempt pc: K/35 image c622e0dcacad59ef8842300bb662160e9d9fa61909b54279af0d01f17bb3bf90
- policy-block-as-preempt q35: K/35 image c622e0dcacad59ef8842300bb662160e9d9fa61909b54279af0d01f17bb3bf90
