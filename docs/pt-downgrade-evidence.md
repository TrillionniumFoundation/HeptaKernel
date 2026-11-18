# Native HIA 4 KiB protection downgrade evidence isolation

The HIA native RW-to-RO and RX-to-NX operations have distinct source files,
distinct machine objects, distinct guarded differential oracles and separate
malicious always-success controls. Previously, both host oracle scripts wrote
their JSON result to `build/x86-pt-write-protect-report.json`. Depending on
execution order, one report silently replaced the other. A successful CI job
could therefore confirm that each command returned zero, but the archived JSON
was **not** independent durable evidence for both operations.

The fix gives the native reports separate stable paths:

- `build/x86-pt-nx-protect-report.json` for RX-to-NX
- `build/x86-pt-write-protect-report.json` for RW-to-RO

Each passing result identifies its operation and binds SHA-256 of its exact
HIA source and compiled shared object. The independent
`tests/test_pt_downgrade_report_isolation.py` checks both current sources and
libraries, checks all 4,016 native calls and the positive/refusal distribution
for each, rejects crossed reports, forged hashes, missing tests and false
hardware/SMP assertions with 18 deliberately corrupted reports. Its result
is `build/pt-downgrade-report-isolation.json`. The foundation CI refuses
to upload artifacts if either native oracle or the cross-report check fails.

Previously published archives containing only one overwritten report must not
be reinterpreted as two independently archived differential campaigns. Their
CI logs and any separate full native build report remain separate evidence.
The new evidence is scoped to the exact candidate that produced it.

This is a host evidence-correctness repair. It does **not** change the existing
real HIA Core v8 source or object instructions; hardware QEMU RX-to-NX and
RW-to-RO acceptance was separately exercised. The current operations still
use a single owner, non-atomic bytewise PTE writes and a non-HIA privileged
INVLPG / CR2 / exception bridge. No concurrent SMP ownership, Linux mprotect,
native HIA privileged backend or complete Linux compatibility is established.
All 17 full Linux acceptance gates remain HOLD.
