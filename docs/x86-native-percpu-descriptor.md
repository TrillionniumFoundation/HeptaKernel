# Native per-CPU dense xAPIC descriptor admission (experimental, HOLD)

The HIA subject computes a distinct descriptor and 16 KiB scheduler stack
for a live xAPIC physical ID in the bounded dense range 0..count-1 (count
1..32). It requires a page-aligned low slab with exact extent: a 4 KiB
metadata page and count 20 KiB intervals (4 KiB reserved guard location
followed by a 16 KiB stack). The selected descriptor is at base+32*ID.
It checks live IA32_APIC_BASE xAPIC mode and MMIO ID, compares live
IA32_GS_BASE with the derived address, then reads the actual four descriptor
words with exact identity CAS (expected callback, stack low, stack top,
free lease). The callback must be outside the slab. Invalid admission
returns zero; the successful return is the actual derived descriptor address.
The four identity CAS operations do not acquire the lease.

An independent non-HIA Multiboot observer starts a second real QEMU vCPU.
BSP0 and AP1 have distinct descriptors, GS bases and stack intervals. Both
are released by one start flag; the observer checks each CPU's exact return,
wrong peer GS, real independently corrupted callback/low/top/lease with
unchanged words on rejection, invalid extent/base/callback overlap, and
AP1's rejection of an exact one-CPU layout. The positive case on each of
PC/Q35 requires both CPUs to finish and an untouched adjacent marker.
Seven separately compiled source mutants are detected independently:
wrong live ID, GS bypass, callback bypass, low bypass, top bypass, lease
bypass, and extent bypass. Negative controls are serialized to identify
the first expected failure without racing debug-exit. All linked subject
bytes are compared against the native object, with two empty-PATH compiles.

Local focus: 16/16 PC/Q35 cases (two actual dual-CPU positives and fourteen
negative controls). Earlier observer preparation failed because the source
split matched wait_ready instead of ready; the rejected observer is preserved
in the isolated development directory. The exact native source/object/text
SHA-256 values are recorded by the test. Existing #234 348 cases are
preserved and rerun in the new workflow; production main, locks, and
coverage are unchanged.

Scope: this is a live, dense two-CPU descriptor admission experiment, not
general CPU/page authority. Layout arguments, executable callback identity
and actual page mappings remain caller-owned. There is no mapping-alias
proof, no guard revocation in this fixture, no per-CPU lease acquisition
or lifetime exclusion, no AP interrupt dispatch on these scheduler stacks,
and no general SMP task migration. Next integrate admission with a native
entry/lease protocol that excludes concurrent descriptor modification,
protects actual mapped guard pages per CPU, and performs real scheduling
and terminal restore on both CPUs. Full Linux acceptance remains HOLD;
all original 17 gates, 422 syscall obligations and historical failures
remain unchanged.
