# Experimental fixed-page remote TLB invalidation

Parent: #179 exact aea82fb49e3fcc3ea5d4043961cc436bcdc677f5; experimental HIA compiler remains the exact #952 lock. This is an isolated two-vCPU PC/Q35 fixture, not Linux acceptance.

The BSP publishes a replacement non-global 4KiB PTE after AP1 has actually loaded the old mapping. The AP handler must observe the old page even after PTE replacement, reject an adjacent virtual address, execute native HIA f2 (APIC identity check, MFENCE, INVLPG), and return through the existing independent assembly interrupt bridge. AP1 itself reads the new physical page after IRET and only then publishes a completion ACK. BSP rejects a local attempt to call f2. The independent oracle checks the old and new physical page values and exact CPU identity; the native subject is linked without modification and checked byte-for-byte in the Multiboot conversion.

Two controls: the unique independently assembled INVLPG opcode is replaced by NOPs, requiring the AP to still read the old value and withhold ACK; and ACK publication is suppressed even though the AP reads the new value, requiring the BSP to classify the operation as incomplete. These controls must pass on both machine types. Results are pending exact-head CI; no old IPI tests are counted as new TLB evidence.

Non-HIA responsibilities: AP startup, IDT, interrupt entry/return, PTE publication, request/ACK transport and observer. Does not establish production resource authority, arbitrary address spaces, page reuse, full cohort completion, interrupt preemption, ordering across all hardware, or Linux ABI. All original full-acceptance gates and production locks remain unchanged.
