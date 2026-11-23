# Native HIA whole-remote-cohort TLB acknowledgement preflight (HOLD)

The previous page-bound gate allows an untrusted target mask to omit online
remote CPUs. This real HIA Core v8 selfhost-compiled successor enforces exact
target = online_before & ~(1 << issuer), requires issuer to be online,
a stable claimed online_before/online_after mask. A one-CPU online cohort is admitted as a **distinct local-only status 6**, never as remote-acknowledgement success (status 0).
It also requires prior_epoch < requested_epoch, making exact replay invalid
when the prior-epoch value is trustworthy.

Wire: precisely 80 + 40*N bytes, N=0..64, little-endian. N=0 is allowed only if issuer is the sole claimed online CPU; such a request returns status 6, **not success 0**. Missing remote rows still return 5.
Header ten u64 words: root, VA, epoch, prior_epoch, online_before, online_after,
issuer CPU, target mask, N, reserved zero. The per-target 40-byte rows preserve
{CPU, ack_epoch, ack_root, completed_flags=3, ack_VA}. Root must be nonzero,
page aligned, below 2^52. VA must be 48-bit canonical and 4KiB aligned.
All targets must have exactly one row. Status 0 internally consistent;
1 malformed length, 2 profile/epoch/online/target issue, 3 CPU membership
or duplicate, 4 row disagreement, 5 missing CPU, 6 local-only with no remote work performed. Callers must distinguish status 0 from status 6 and obtain separate proof of local invalidation before any reuse. Input and output unchanged.

Pinned selfhost_elf emits actual x86-64 from .hepta with verifier,
two empty-PATH compilation equivalence, independent byte oracle, malicious
always-accept replacement and dedicated CI. This is NOT trusted online-set
provenance, remote CR3 proof, IPI, INVLPG, an atomic/fenced publication protocol,
authentic acknowledgement, Linux SMP, or permission to recycle physical frames.
In particular, a malicious party may fabricate *both* online masks and prior
epoch. All 17 full Linux gates and 422 syscall obligations remain HOLD.
