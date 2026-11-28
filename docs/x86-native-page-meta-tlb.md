# Fixed local metadata TLB refresh before writer lease

Experimental HOLD; parent #251 exact b36e2a7bbca716ff6c9191421d532a7334a2cae4. A correct live metadata PTE alone does not imply that the currently cached local translation is correct. After the existing exact metadata leaf admission, HIA f8 now executes INVLPG for that metadata VA before any explicit or ordinary lease CAS. No earlier validation is removed.

The independent observer populates a real shadow translation, restores the original PTE without invalidating that translation, and proves a new marker write still reaches the shadow. The native acquisition then must write the original physical metadata lease only. Replacing the new INVLPG with MFENCE (not an invalidation) must acquire the shadow lease, while the original remains unchanged. This is observed for both CPU directions, PC and Q35. All 52 inherited focused controls plus 8 new controls passed (60/60), with existing guard/entry/owner/callback object hashes unchanged. The subject and images necessarily change. The ancestor 712 CI cases plus these 60 are planned for independent execution; no independent PASS claimed yet.

This closes only the demonstrated local stale-metadata translation gap under fixed live page-table access and cooperative mutation. It does not prove remote TLB completion, protection against remapping after the local invalidation, physical access to page-table pages, NMI or general CPU/page-table authority. Original Linux HOLD, locked main and toolchain, historical failures and original budgets are retained.

Source/object/text SHA256: e572b9f6b7a914e5b6efcd8af51196ac580bb11e0f810ef090b8bd2e6af63a7f / 5966872687bac8b7b1465df558aed29353b5fc140b48abb92617994e77d8d867 / 9005254de6b186319c13d08c1d3a25fde8c01c383e555c8e90f7a68e966ce75d.
