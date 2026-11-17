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
is required to fail. Neither this direct native object nor host testing
establishes that x86 hardware loaded an IDT. The current kernel bridge still
constructs and loads its IDT in `arch/x86_64/boot.S`. The next integration
must link this exact HIA object into PC/Q35 and use it to build the active
IDT before `lidt`, including an intentionally stale old-word fault injection.
Privileged `lidt`, hardware exception frame entry/IRET and IST still require
upstream HIA architecture support; no binary payloads or translated stubs
are counted as HIA.
