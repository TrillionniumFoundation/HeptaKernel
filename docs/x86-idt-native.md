# Native HIA x86-64 IDT descriptor installation (single-owner)

This implementation compiles `src/x86_idt_gate.hepta` with the exact pinned
Core v8 `selfhost_elf` backend into an x86-64 ELF object, independently
recompiled and compared byte for byte. The ABI is three buffer capabilities:
32-byte read-only request, at least 16-byte writable reply, exactly 4096-byte
exclusive mutable IDT. The SysV entry returns status u32.

The request contains four little-endian 64-bit words: vector, handler RIP,
expected low IDT descriptor word and expected high word. The code checks that
the vector is in [0,255], handler is nonzero and canonically 48-bit addressed,
and both prior IDT words equal the supplied expected values before writing.
It emits the exact two-word x86-64 interrupt-gate encoding: kernel code
selector 0x08, IST=0, DPL=0, type=0xE, P=1, reserved bits zero. It preserves
the requested 64-bit handler address. Only status 0 may alter the table;
status 1 means short reply, 2 malformed request, 4 table length,
6 invalid vector or address, 9 expected-old mismatch. This conditional
single-owner check is not atomic CAS and cannot be used for live SMP updates.

An independent Python oracle checks descriptor bytes, all 256 vectors,
stale expected-old inputs, malformed buffers, noncanonical handlers, and
guarded memory boundaries. A deliberately dishonest native HIA implementation
is required to fail. The native HIA IDT writer now executes in PC/Q35 before privileged
`lidt`, writing each of the 256 interrupt gates. The test bridge checks
both output qwords and selector/type fields, then overrides vector 14
using the same HIA implementation in NX/WP fault images. Actual hardware
page faults must still dispatch successfully through the HIA-written
descriptor to the existing assembly entry and HIA policy checker.
A fault-injected image supplies a stale expected-old word for vector
zero, requiring status 9 with neither IDT qword modified and an
independent pre-LIDT refusal marker. Byte-for-byte HIA compilation,
native guarded oracles and all existing QEMU controls remain required.

This is a live HIA IDT **table construction** milestone; it is not
HIA-native privileged `lidt`, exception frame entry/IRET, TSS/IST or
concurrent SMP update. No binary payloads or translated stubs are
counted as HIA.
