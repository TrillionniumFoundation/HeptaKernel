# Native HIA ELF64 initial stack: CPU CPL3 readback (isolated QEMU)

The original locked Core v8 `src/elf64_start_stack.hepta`, *not* assembly
standing in for HIA, writes 128 bytes of an ELF64 initial stack to the final
128 bytes of a physical 4KiB page. This experiment extends the independent
physical-byte checks with actual x86-64 CPL3 loads of that HIA-written page.

The single-owner QEMU bridge authenticates neither the ELF image nor the
original user process. It obtains the real Multiboot memory map, runs existing
native HIA E820/reservation gates, initializes native HIA PMM state and admits
the physical frames at 0x601000 and 0x602000. It invokes the original
`elf_stack_f0` with base 0x601000, AT_ENTRY=0x401000,
AT_PHDR=0x400040, PHENT=56, PHNUM=3, then checks all 4096 output bytes, its
receipt (SP=0x601f80, written=128) and the adjacent frame canary.

Only **after** that byte-level check, the clearly **non-HIA**
`arch/x86_64/boot.S` test bridge copies a small RIP-independent user-code
fixture into physical 0x401000, uses *native HIA* upper-table U/S grants,
2MiB RX code and RW/NX stack PDE construction, the previously HIA-created IDT,
GDT and TSS, and finally enters CPL3 with a non-HIA IRETQ. At the exact HIA
AT_ENTRY the real CPU loads argc from user RSP, AT_PHDR from RSP+32 and
AT_ENTRY from RSP+96 into registers, then triggers UD2. The real #UD CPU
frame must land on the TSS.RSP0 stack and show CPL3 CS/SS, the exact user
RSP=0x601f80 and the exact post-instruction RIP. The independent CPL0
observer checks **hardware-carried** registers, not only a producer receipt.

The companion hostile test edits the *physical stack* AT_PHDR value after the
unchanged native HIA write, from 0x400040 to 0x400041. The CPL3 CPU must
carry the changed value into RDX; the separate negative observer checks the
real hardware frame before emitting its expected negative marker and a
failure exit. A stale copied output or cached HIA receipt must not pass as
an uncorrupted CPL3 load.

Run `make test-elf64-stack-ring3` to execute both cases on PC/32MiB and
Q35/64MiB. The 4 raw QEMU outcomes, complete stdout/stderr, commands,
source/object/image SHA-256 and exact candidate SHA are retained in
`build/elf64-stack-cpl3-qemu-report.json`. Existing HIA source verifier,
native byte identity, guarded host differential oracle, dishonest compiled
HIA negative and 12 physical QEMU cases remain mandatory through
`test-elf64-stack-hw`. The Foundation CI runs the new tests via
`make test-boot` and retains the new report.

**Strict limits:** the CPL3 instructions are an assembly **test fixture**,
not unmodified Linux userspace and not part of an HIA-native implementation.
IRETQ, CR3/TLB, IDT exception entry, privilege and MMU setup, even the
calling/ownership provenance, remain in non-HIA boot.S. This does not
implement ELF file acquisition, authenticated mapping, stack randomization,
Linux auxiliary vectors beyond these fixed fields, execve, process lifecycle,
interrupt safety, SMP, drivers or full ABI. Every existing Linux obligation
and all 17 full-target gates stay HOLD; `make full-acceptance` must exit 2.
