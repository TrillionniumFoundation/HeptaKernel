# Experimental native return-frame selection after terminal EOI (HOLD)

Exact parent: aecd8ee55d37c3b330cef6f6e7b7ddfa124066f4 (PR #226).

The new HIA export composes the unchanged native dispatch/fail-stop implementation (only its private function name changes) with the return-frame decision. On committed switch, it derives the selected task's expected next owner generation and target frame; on a no-switch outcome, it selects the departing frame and unchanged owner. It validates the aligned nonzero full 160-byte frame inside the corresponding bounded stack, confirms exact owner and empty live slot by identity CAS, and checks the timer ISR bit is clear after EOI. Only then does it return the actual frame pointer. Refusals 65/66 and recovered 69 remain status returns. A failed postcommit check traps with native UD2 without reversing ownership, ready publication, or EOI.

In the independent PC/Q35 observer, the HIA pointer is passed as the actual callback return value to the existing native raw IRQ entry/IRETQ; assembly retains independent checks against the expected address, all original GPRs, owner, ready, and slots. Four handoffs (preempt, block, enter idle, wake idle) and one no-peer stay use the returned HIA frame. Supervisor completion remains the inherited separate observer path. This is a native selection-and-return composition using existing native IRETQ, not a new direct terminal restore instruction in the same export. Caller-owned fixed BSP topology, nonnested interrupts, no general resource authority or SMP proof remain the experimental boundary.

The additional compiled controls return a slot address instead of a selected frame (O), return an owner address instead of the stay frame (I), and alter the postcommit expected owner generation (T). The latter exercises an actual failed identity CAS and precise UD2 after successful EOI, with committed owner/ready/frame slots unchanged and target progress still zero. It is a deliberately wrong expectation, not a concurrent publisher test. The independent handler terminates the experiment; it is not a production panic proof.

Desktop qualification: 180/180, including 170 inherited cases with identical case records and every inherited object record identical. Ten new cases (five per machine). All eight inherited host oracles retained; two empty-PATH native compilations match. New native hashes:
- source_sha256: 13e06a7a87552e3933e2cfc0f2fe7664b483c8e41e10e64cc16f9ac9b9c7dfe7
- object_sha256: f2108a939468a4af0bde748a32aedd6d2289a85d7aee58604dd7f26fd6bf2e1a
- text_sha256: 13fc2c811768667fad282a8e327b57bdd0ac2e25cfd0a848ed55aacdaac35b14


The production main refs and toolchain locks are unchanged. Full Linux acceptance remains HOLD: all 17 original gates, 422 syscall rows, original 3s/5s/60s budgets, historical failures, native direct terminal restore, synchronous sleep/wake, native HLT, general SMP/cohort/reclaim/authority, error-code and CPL3 context, FPU/SIMD, GDT/TSS, all VFS/storage/network/security/ABI/driver/architecture obligations remain in scope. This experiment does not close those obligations.
