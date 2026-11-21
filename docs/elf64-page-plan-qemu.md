# Real native HIA ELF64 PT_LOAD plan → QEMU physical page fill

This isolated experiment composes the **unchanged locked selfhost_elf
machine code** from src/elf64_page_plan.hepta and src/elf64_page_fill.hepta on
both pc/32 MiB and q35/64 MiB in QEMU. A non-HIA observer constructs a
synthetic 7,292-byte ELF64 ET_EXEC image with one RX PT_LOAD, p_offset=0x107b,
p_vaddr=0x40107b, p_filesz=3073, p_memsz=8192 and p_align=4096. HIA
derives a 40-byte plan for each segment-relative page index, then unchanged
HIA fill code writes into separately E820-admitted, HIA PMM allocated 4 KiB
physical frames (0x601000 and 0x602000).

The independent physical-byte oracle expects 123 leading zero bytes, 3,073
known patterned file bytes, 900 tail zeroes in the first page and a
completely zero second page. It checks the entire original source, copied
envelope and guard words, selected header fields, status, receipts and both
physical pages. The linked object .text is independently compared with the
original HIA compiler output, including a dishonest native HIA no-op plan.

Two hardware platforms execute each of four scenarios:
- honest HIA plan + honest HIA page fill → debug exit 33;
- mutated PT_LOAD offset fails congruence, leaving physical pages and output
  unchanged → unique negative marker and debug exit 35;
- dishonest HIA plan returns success without modifying plan → detected
  separately by original-value readback;
- a hostile NON-HIA coordinator changes the HIA plan after return → detected
  by the external expected-value oracle *before* fill (this is explicitly
  **not** a HIA-authorized atomic seal).

This is a physical-memory component integration, not a genuine Linux ELF
loader, trusted file snapshot, user PTE publication, usermode execution,
ELF relocation, dynamic linker, execve, HIA privilege backend or SMP
linearizable operation. The synthetic file is owned by the observer, and
the non-HIA boot.S still drives privilege transitions. Never use this
limited experimental PASS to close any Linux full-target gate.
