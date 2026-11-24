# Experimental fixed-page remote TLB invalidation

Parent: #179 exact aea82fb49e3fcc3ea5d4043961cc436bcdc677f5; experimental HIA compiler remains the exact #952 lock. This is an isolated two-vCPU PC/Q35 fixture, not Linux acceptance.

The BSP publishes a replacement non-global 4KiB PTE after AP1 has actually loaded the old mapping. The AP handler must observe the old page even after PTE replacement, reject an adjacent virtual address, execute native HIA f2 (APIC identity check, MFENCE, INVLPG), and return through the existing independent assembly interrupt bridge. AP1 itself reads the new physical page after IRET and only then publishes a completion ACK. BSP rejects a local attempt to call f2. The independent oracle checks the old and new physical page values and exact CPU identity; the native subject is linked without modification and checked byte-for-byte in the Multiboot conversion.

Two controls: the unique independently assembled INVLPG opcode is replaced by NOPs, requiring the AP to still read the old value and withhold ACK; and ACK publication is suppressed even though the AP reads the new value, requiring the BSP to classify the operation as incomplete. These controls must pass on both machine types. Results are pending exact-head CI; no old IPI tests are counted as new TLB evidence.

Non-HIA responsibilities: AP startup, IDT, interrupt entry/return, PTE publication, request/ACK transport and observer. Does not establish production resource authority, arbitrary address spaces, page reuse, full cohort completion, interrupt preemption, ordering across all hardware, or Linux ABI. All original full-acceptance gates and production locks remain unchanged.

## Independent oracle follow-up

Initial exact `62e64ddee4693b5110f70128b46a825bea5b23d5` PR run `45424811851` passed both positive machine cases but failed the first INVLPG-deletion control (PC, exit 37/`A` instead of 35/`F`); later cases did not run. This failure remains part of the evidence. The new oracle observes the AP translation immediately after f2 and before EOI/IRET, and requires that observation AND the post-return new value before ACK. The deletion control must observe the old value immediately and withhold ACK; it separately reports `F` if the old translation survives return and `R` if it has refreshed by then. The latter is not proof of the original stronger post-return stale observation; the report retains a separate Boolean for that original condition. No second invalidation is introduced. Distinct abort markers identify failures before f2 (`B`), immediately after (`I`), and unexpected ACK (`C`). New exact CI is required. The HIA subject and original positive and missing-ACK requirements are unchanged except for the added immediate read requirement.

## Native PTE publication follow-up (pending exact CI)

Parent exact 373b2cc62c2097309b2b15f7e15ca64a719f9ef6: PR run 45436811456 passed all six revised cases; both INVLPG-deletion cases returned R, not F. Original post-IRET stale condition remains false. This candidate preserves that Boolean and all three existing scenarios and moves fixed leaf PTE publication from assembly into native HIA f3, with locked CAS and fence. Independent readback checks invalid alignment, stale expected PTE, wrong CPU, and removal of the unique CAS opcode on both machine types. Eight scenarios planned; no new PASS asserted before exact CI.

f3 admits three distinct nonzero page-aligned low identity-mapped addresses, expected old supervisor non-global PTE with flags 3 or 35, enabled xAPIC and BSP identity. Caller still owns and supplies the actual table and backing pages. ACK publication, AP startup, IRQ entry/return, request transport, arbitrary cohorts, page reuse, and production authority remain open. No production lock or original acceptance gate changes.

## Generation-tagged native ACK follow-up (pending exact CI)

Parent #184 exact 049a5ac6915cfb46949195b839065c9949423793: PR run 45469466210 job 138713157880 returned eight PASS cases, including both PTE CAS deletion controls. Both INVLPG deletions returned R; original post-IRET stale condition remains false. Earlier oracle failures remain in history.

This candidate adds HIA f4: AP1-only live xAPIC identity, aligned bounded nonzero slot, nonzero generation below 2^63, immediate/post-return new value and zero flush status, then locked CAS from 2g to 2g+1 with fences. Independent observer sets pending generation 2 and canaries on BSP, tests wrong-CPU rejection, AP misalignment, failed status, stale and future generations while pending, duplicate after completion, and observes exact word on BSP. Missing ACK and deleted INVLPG still leave pending; independent deletion of f4 CAS must leave pending despite apparent success. Both CAS instructions separately identified by function range and raw bytes; deletion of either preserves the other. Ten QEMU cases planned, no new results until exact CI.

Observation values and slot pointer are caller-supplied, not a resource capability; no general authority, repeated generation lifecycle, AP startup, native entry/return, arbitrary cohort or reclamation claim. Original post-return stale condition and all full Linux gates remain unchanged.

## Native BSP completion consumption follow-up (pending exact CI)

Parent #185 exact `f8982e7d36f19c9ebb141bc168381a6da01ce901`: independent PR run 45480962944 reports 10/10 PASS, both INVLPG-deletion controls R; original post-IRET stale control remains false. All existing scenarios and that separate Boolean remain.

The new HIA f5 checks a nonzero aligned bounded slot, nonzero generation below 2^63, live enabled xAPIC state and BSP identity. It consumes the exact completed word 2g+1 using locked CAS to zero and MFENCE. Zero is a terminal fixture state, not an allocator or new request. Pending, wrong-CPU, invalid address/generation, stale, future and duplicate completion consumption must be rejected. The BSP independently verifies the word and adjacent canaries; the AP may not consume it. Deleting the f5 CAS must yield a false success with pending or completed storage unchanged, two distinct new controls on each machine. Exact source/object/range custody and the earlier five cases are preserved. Fourteen QEMU cases planned; no new execution claim before CI.

This does not prove ownership, repeated epoch initialization, arbitrary cohorts, page reuse or reclamation. A zero word only marks consumption of this one fixture generation. It cannot authenticate the observations previously supplied to f4. Full Linux acceptance remains HOLD.
