# Isolated HIA-native atomic execute-permission revocation

Stacked on the exact hardware-validated experimental PTE write-protect
candidate 00dedab5fc74c6dc9654dacb1ff71c6518d46d08, using the same independently rebuilt upstream HIA
compiler afa29e97aba26351d366f9ecded027e127e77427. The new genuine HIA
implementation admits only present, read-only, executable 4 KiB entries
with validated supplied capability fields, sets NX through full-word
aligned LOCK CMPXCHG, preserves all other bits, and executes MFENCE and
local INVLPG only on a successful expected-old comparison.

The separate NON-HIA guest observer follows the actual CR3 and table
links, provisions a tiny executable fixture in RAM, clears RW and
demonstrates execution before revocation. Success requires a precise
supervisor instruction-fetch protection fault (error code 17, CR2 and
RIP 0x400000), unchanged code bytes and exact NX PTE, with all other 511
PTEs unchanged. Stale expected-old, invalid capabilities/address,
writable and already-NX expected transitions, explicit restoration, and
a CAS-NOP object mutation must have their separate exact outcomes.
Original HIA ELF text is retained through linking; the fixture is only
an oracle, not HIA implementation.

Status: isolated draft pending new exact-head qualification. Live
physical table/address ownership, capability provenance, cross-CPU
shootdown, user mprotect and complete Linux functionality/ABI/driver
acceptance remain OPEN. The production toolchain lock, full acceptance
range and existing write-protection experiment are unchanged.
