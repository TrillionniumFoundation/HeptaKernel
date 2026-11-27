# Bounded native dispatcher stack depth (experimental, HOLD)

The preceding frame-content experiment found an actual cross-task stack write
in an outer-wrapper variant. Keep the original 16384-byte task stack layout
and the original 16376-byte usable span; do not hide overflow by enlarging it.
This candidate removes two simultaneously live dispatch wrappers: the native
export directly calls the existing dispatch transaction, then calls the
unchanged-equivalent checked EOI helper after unwinding, and finally admits
only 0/64/65/66/69 (all other statuses trap at the export's fatal block).
The frame-content helper and the dispatch transaction remain byte-identical
in HIA source. This is actual HIA compiled with the exact inherited
experimental native compiler; no external assembly dispatch replacement.

The independent machine-code oracle conservatively sums every fixed prologue
allocation, saved RBP and return address along the longest direct call chain,
including mutually exclusive paths. It checks local stack adjustments,
branch destinations, direct calls, return forms and frame-relative accesses,
rejects the parent's 16880-byte chain, and requires the replacement and all
independent fault variants to be at most 15352 bytes. The normal new chain is
15136 bytes; owner fault 15168, partial and unknown fault 15200, EOI and
content bypass 15136. A 512-byte reserve covers the fixed hardware/raw IRQ
frame and the inspected callback/terminal exception overhead; a distinct
512-byte bottom canary in each task stack is checked by the observer. The
secondary direct callback targets have independently computed smaller bounds.
The observer's fixed pushes and call-alignment helpers are inspected in
each linked image. This is a bound on stack depth for this exact fixed,
non-nested BSP dispatch fixture, not a proof of arbitrary pointer aliasing,
production panic handling, NMI/exception nesting, or general stack authority.

Local focus r3: 26/26 actual QEMU PC/Q35 cases, normal short and long,
recoverable owner refusal, fatal 67/70/71, five corrupted control-word
faults, content bypass, and a deliberately damaged bottom canary. Each new
candidate builds twice with empty PATH. Original #228 qualification 196/196
remains unchanged; independent push and PR artifacts were compared to the
local #228 report (all cases and object metadata matched). The new CI reruns
all 196 inherited cases before the new 26; both must pass. The first focused
oracle incorrectly disallowed the compiler's legitimate (%rsp) access and
stopped before QEMU; r2 accepted only in-allocation fixed RSP references and
passed 26/26; r3 added return/secondary-callback/observer stack checks and
passed 26/26 with identical images. Earlier #228 actual overflow evidence,
all historical A/37 failures, and all original tests remain unchanged.

General per-CPU scheduler/IRQ stacks and resource authority, native terminal
restore, synchronous sleep/wake, HLT, arbitrary CPU/SMP, error-code and CPL3
frames, FPU, GDT/TSS, TLB cohort/reclaim, post-IRET stale, ABI, VFS, storage,
network, security, architecture and driver obligations remain open. No
production lock, main, 17 HOLD gates, 422 syscall obligations or original
3s/5s/60s budgets are changed. This is not Linux acceptance.
