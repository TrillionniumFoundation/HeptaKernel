# Native reserved-topology dispatch composition (experimental HOLD)

Parent: exact ff061a43d276d11210d74f23c513690fe372577d (#223).
This alternative extends the verified forward and reverse components, not
the production toolchain. A single HIA export takes six scalar arguments:
packed owner address/topology/reason, expected owner, packed slot table and
ready-word addresses, expected departing/target frames, two stack tops, and
expected ready word. The target ID is an expected binding for the caller-owned
frame, not selection authority. Native prediction and the existing native
policy both determine the selected ID. Incorrect target binding, reserved
idle bits, wrong reason, out-of-range or aliased metadata, wrong live owner,
nonempty departing slot, and insufficient rollback generation room are
refused. Preflight verifies live BSP periodic timer ISR, then owner and
departing slot via identity CAS, before mutating ready. Table endpoints,
owner and ready cell are excluded from both declared stack intervals.

Status 0 commits forward frame and owner; 64 is a no-switch policy result;
65 is invalid and 66 stale before handoff. After claiming ready, a stale
forward frame refusal (9) is followed by a repeated owner/empty-slot guard
and exact reason-aware compensation. A partial forward owner refusal (68)
uses inherited guarded reverse plus ready compensation. Only successful
compensation returns 69 (restored bitmap with advanced generation, not a
bitwise rollback of the generation). A failed ready compensation returns
67 and the other ambiguous post-claim failures return 70. The caller must
fail-stop on either and must never blindly retry. Committed owner is not
rolled back. No general transaction or cross-CPU exclusion is asserted.

Independent PC/Q35 observer uses the single export for all four actual
preemption, block, idle entry and exit switches and the no-wake idle stay.
Each switching path first supplies an in-stack stale target to exercise
actual pre-frame refusal and compensation; verifies original slots/owner,
advanced ready generation, stale compensation replay rejection, and then
retries with the correct target. No external policy/forward/rollback
orchestration is used for these transitions. Wrong ready alias and target
binding refuse before mutation. Two separately compiled fault controls
introduce a stale owner argument into the real forward helper (V/35) and
additionally a stale expected ready generation to the real rollback CAS
(Z/35); the independent observer checks actual slots, owner and ready
after these failures. The latter is a wrong expected generation control,
not a concurrent publisher race. A skipped compensation call is detected
(I/35). EOI, frame return and the final fail-stop are still handled by the
observer; native EOI/terminal path composition, synchronous sleep/wake,
native HLT, arbitrary CPU/task authority and SMP are not qualified here.

Desktop qualification-r1: 144/144 PC/Q35 (134 inherited rows and all
inherited object metadata identical; 10 new); eight inherited host
oracles, two empty-PATH native builds byte-identical. Initial native
compilation rejected duplicate SSA name code; preserved locally in
rejected-r1.hepta, fixed by unique partialcode name; subsequently added
table stack extent checks. No test relaxation.
Source/object/text SHA256:
- 6c62a8aa747ad2b27bb7ad393e00ee4abb65e3eae6f740bc0dfcac8cb7ce6bff
- ddfb649828d03a0d424b8777a45fbad024a565c4bde578e5db7da4094db92e66
- 0effabff739707cfb2998b77cca6cf236270ff765dae2159bdf3f331ef4cfdfa

Original 17 HOLD gates, 422 syscall obligations, all historical failures,
3s/5s/60s budgets, both main heads and production locks unchanged.
Independent CI must verify this exact candidate before any promotion.
