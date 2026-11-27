# Native raw IRQ entry during actual preemption (experimental)

The CPL0 no-error-code xAPIC timer gate points directly to the native export of
the experimental HIA compiler, pinned to upstream 25c165ba7c80e3e1124acd4efb083c637fbb275a.
It saves all fifteen general-purpose registers before any ordinary prologue,
validates the original hardware frame, validates the caller-owned GS_BASE
descriptor and calls an ordinary ABI-preserving dispatch callback. The callback
performs the previous independent scheduler experiment and returns the selected
frame pointer; the native gate validates and restores the selected frame with
IRETQ. The observer contains no IRET and no hardware-frame register-save entry
stub; its callback pushes only three of its own callee-saved ABI registers.

Two calibrated timer periods on PC/Q35 exercise nine delivered ticks, four
actual task switches, per-tick original register values, progress in both
tasks, saved RSP/RIP, teardown and GS_BASE readback. The independent arithmetic
oracle retains all 3477 calls. The prior schedule CAS deletion, initial restore
IRET deletion and wrong-R15 restore controls remain; two additional mutation
controls change raw entry R15 save and raw gate IRET, with distinct failure
markers and checks before/after the first actual interrupt. All three native
objects are independently recompiled, their exact bytes checked after
symbol renaming and linking, and the original scheduling and restore objects
are byte-identical to the prior experiment.

The local isolated run passed 14/14 PC/Q35 scenarios. Independent exact-head
CI is required. This does not prove arbitrary IRQ entry, error-code exceptions,
user-mode transitions, FPU/SIMD, general scheduling, multicore authority,
stack/frame resource ownership, or Linux acceptance. The original full
acceptance scope and production toolchain remain unchanged.
