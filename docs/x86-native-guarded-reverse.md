# Native guarded reverse frame composition (experimental HOLD)

Parent: a270d7300f97a0c272ff63b0059844e1df2a66a3 (#220). The new native HIA export combines the inherited live-owner rollback guard and bounded reverse frame transaction in one call. It accepts packed low-32-bit owner address / high-32-bit forward topology, prior owner, slot table, source frame, target frame and packed two 32-bit stack tops. It rejects extra topology bits, mismatched departing ID and prior owner ID, invalid stack-top bounds/alignment and owner overlap with either stack interval; then runs the inherited live owner/frame/slot guard, and only on success constructs the swapped topology and invokes the inherited bounded frame composition. Both inherited implementations are byte-identical except private numeric function renames, independently checked by the test. Guard failure is propagated; no frame transfer is attempted. The guarded reversal still does not constitute a lock or an atomic multiword transaction.

The independent observer uses the new export for four real reversals, each with stale owner, malformed topology, incorrect departing ID and owner-stack alias refusal probes before reversal, and a replay refusal after reversal. It retains the unchanged owner, restored slots, ready compensation, retry, monotonic generation and no-wake checks. Native source controls bypassing the guard or skipping the reverse call are rejected on both PC and Q35. All first 106 scenario records and inherited objects are identical to the local parent report. The new object is not linked into those inherited scenarios.

Desktop qualification-r2: 114/114 PC/Q35 (106 inherited + 8 new); two empty-PATH native compilations identical. All inherited host oracles retained. Independent exact-head CI required. Initial helper bool-return/empty-effects version failed native compilation (exit 2); revised u64/trap helper compiled. Initial qualification-r1 positive PC failed I/35, after 106 inherited passes: wrong-ID probe set a bit that was already set for one departure; corrected to toggle the low departing-ID bit (no oracle weakening), targeted PC/Q35 smoke P/33, full r2 passed. Original failure retained:
{"case": "guarded-reverse-short", "machine": "pc", "image_sha256": "0c7e3bf86d1ab5c977264bc6d52ca7d651924fc52ef6c6fdebf8bb66e8c53f5f", "expected_rc": 33, "expected_serial": "P", "status": "FAIL", "returncode": 35, "serial": "I", "stderr": ""}

Native SHA256:
- source_sha256: 42c5095a11c3c79ead1bd057c9644c73c3783217bbe452cc3925a61c5f693b5a
- object_sha256: be2ce808d9b130d73995e9a658d8548c5e92a246060dcab64215d09ce15a25f8
- text_sha256: 094d1e6ae6895e94a945b4bb4c9f5feb080732702914867e5b61e06b4df4a18b

New cases:
- guarded-reverse-short pc: P/33 image 0fae009b206a9e1117484d67b37d968559ab729927a91f2224053c7f6174d3fb
- guarded-reverse-short q35: P/33 image 0fae009b206a9e1117484d67b37d968559ab729927a91f2224053c7f6174d3fb
- guarded-reverse-long pc: P/33 image 2dd2700d1415d5447214ef3ea6b987bfe49b6036eadbfff23390fc0968a29543
- guarded-reverse-long q35: P/33 image 2dd2700d1415d5447214ef3ea6b987bfe49b6036eadbfff23390fc0968a29543
- guarded-reverse-bypass-guard pc: I/35 image 04642971e9f2485e67378029666e5cf1de12fefb3f889f1389d47a2f9b57652a
- guarded-reverse-bypass-guard q35: I/35 image 04642971e9f2485e67378029666e5cf1de12fefb3f889f1389d47a2f9b57652a
- guarded-reverse-skip-transfer pc: I/35 image b68b14303b5a68cfc8e01325548d02993ad7479af23dfcf2157bf70d03b49dcd
- guarded-reverse-skip-transfer q35: I/35 image b68b14303b5a68cfc8e01325548d02993ad7479af23dfcf2157bf70d03b49dcd

Scope: fixed BSP periodic IRQ, nonnested, caller-owned addresses/stacks/table. Separate forward policy, owner commit, ready compensation, EOI/IRET orchestration remain; this is not complete dispatcher, resource authority, native HLT, synchronous sleep/wake, arbitrary CPU, SMP or Linux acceptance. Guard and compose perform separate identity checks; no concurrent mutation safety claim. Both main branches, production lock, original 17 HOLD gates/422 syscall obligations, all historical failures and original 3s/5s/60s budgets unchanged.
