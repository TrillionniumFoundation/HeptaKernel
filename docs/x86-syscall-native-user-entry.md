# Composed native HIA IDTR, CPL3 IRETQ and syscall MSR experiment

Build the original #177 ordered four-MSR implementation with two genuine HIA translation units on independently qualified #955. The restricted terminal IRETQ function requires a separate translation unit. Only public ELF symbol names are renamed; the observer checks byte-identical linked text for each of three subjects.

The independent boot fixture constructs a #UD gate, but executes HIA LIDT and checks the actual ten-byte IDTR with SIDT. It executes HIA four-MSR initialization and calls terminal HIA IRETQ into a genuine user RX page with a distinct RW/NX stack. The high-half SYSCALL observer checks the original CS/SS, RAX, RCX, R11, RSP, FMASK and LSTAR assertions. The fixture contains no IRETQ instruction; restoration of original IDTR and MSRs is independent observer code.

Twelve original MSR success/refusal/mutation cases are retained on PC and Q35. New IRETQ deletion must hit the exact terminal UD2 sentinel at CPL0, invalid flags must hit the exact guard UD2 at CPL0, and deleted native LIDT must leave the old descriptor untouched and not enter syscall setup. Objects, mutations and linked text are bound. New exact CI is required.

This advances native user entry, not native SYSCALL entry or return, arbitrary exception restoration, task lifecycle or resource authority. Both mains, production lock, 17 HOLD gates and 422 syscall obligations are unchanged.
