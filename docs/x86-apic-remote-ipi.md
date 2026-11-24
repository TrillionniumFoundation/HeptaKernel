# Native HIA physical xAPIC IPI: independent two-vCPU experiment

This draft extends the exact #178 hardware-validated experiment without
changing production locks or coverage. The HIA f0 accepts the explicitly
limited two-vCPU fixture (BSP APIC ID 0, target APIC ID 1, vector 0x51,
UC-mapped xAPIC aperture 0xfee00000). It validates live APIC-base MSR,
xAPIC mode, sender ID and software enable. It polls ICR idle with a
bounded budget, writes the physical destination, checks destination
readback, sends fixed-delivery IPI, and checks idle/vector readback.
Its status zero means local dispatch readback, not remote completion.
HIA f1 is the existing checked highest-active-vector EOI implementation.

The independent NON-HIA observer starts the actual AP via INIT/SIPI,
installs an IDT and independent stacks, and verifies AP identity from
its local APIC. Only HIA sends the measured IPI and issues its EOI.
The actual AP handler verifies local ISR and identity, and the
post-IRETQ AP loop supplies its own IRR/ISR snapshot. The BSP must have
no corresponding IRR/ISR. Destination, send and EOI store-deletion
mutants and invalid base/destination/vector/stale/disabled refusals
require distinct outcomes; a timeout or generic guest failure is not
a PASS. Exact HIA object text is checked before and after linking.
Run both PC and Q35 with two vCPUs.

This is deliberately a finite topology experiment, not authenticated
APIC/MMIO ownership, native AP startup, native interrupt entry/IRETQ,
arbitrary CPU routing, remote TLB invalidation, or Linux SMP closure.
The new candidate requires independent exact-head CI.
