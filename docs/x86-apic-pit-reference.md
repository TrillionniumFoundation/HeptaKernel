# Experimental composed native PIT and APIC reference windows

This isolated descendant of #191 (`f71bd7ac03273cc4c9922f020a74c67a199e2518`) preserves
the independently tested #190 APIC subject and #191 PIT subject in a
single genuine HIA compilation unit. The original functions are preserved
except for extending exports and renaming the four PIT functions to
f7..f10. The qualification checks that exact composition from the
original files. f11 is a real native function calling all four PIT
functions; actual relative CALL targets are independently decoded and
checked. Invalid poll budget is rejected before touching the timer;
a bounded wait failure still calls native stop before returning.

The calibration observer calls f7 to program each 12000/24000 tick
reference, f0 to arm a masked APIC, and f8/f9/f10 to run and stop the
PIT interval. It independently reads real APIC current count before
starting and after waiting, then calls f1 to sample and stop the APIC.
The original 25% overhead and [1.5,2.5] timing ratio bounds remain.
The original integer count estimator, dynamic APIC count programming,
real periodic IRQ delivery, EOI, stop and quiet-window checks remain.
The 60000-tick delivery and quiet windows use the composed native f11.
The independent observer still provisions the GDT/IDT, controls
interrupt enable, handles IRQ entry/IRETQ, and observes actual APIC
and PIT state. No assembly PIT count programming is needed in these
measured windows.

The previous independent PIT-only and APIC-only tests are unchanged.
A separate mutation deletes the private f8 gate-start OUT instruction,
requires HIA to refuse and confirms no gate start or retained APIC
count. Deleting the private APIC dynamic count store remains a distinct
control. Native window invalid budget and actual one-poll exhaustion
with gate cleanup are also exercised. Every subject object and linked
text is checked against exact compiler output. The final local run
passed 3477 independent pure arithmetic cases and 10/10 PC/Q35 cases,
with 5 IRQs in each short-period window and 2 in each long-period
window. Initial composition passed on PC but had a Q35 assertion
failure; three instrumented Q35 diagnostic replays passed and did not
identify a cause. The original failure is retained locally; the final
candidate uses the native preflight and exhaustion-cleanup additions
and the unchanged original APIC timing and IRQ criteria. Independent
CI and repeated qualification remain necessary.

This is a limited two-clock, single-CPU, fixed-port and fixed-APIC
experiment, not an independent external clock accuracy proof, a
scheduler clocksource, complete resource ownership, general teardown
or native IRQ context handling. The production toolchain lock, original
Linux inventory, 17 HOLD gates and 422 syscall obligations are untouched.
