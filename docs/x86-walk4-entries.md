# HIA native x86-64 four-level entry policy (4 KiB only)

`src/x86_walk4_entries.hepta` is native HIA Core v8 `selfhost_elf`
code, exported as `walk4` with **six SysV u64 parameters**:
`VA, PML4E, PDPTE, PDE, PTE, MAXPHYADDR`. The caller is responsible
for selecting the entries at the four VA-derived indices from correctly
linked, owned physical page tables. The function does **not** read those
tables, resolve the links, or read CR3.

A return of zero refuses. A successful return sets bit 63 and packs the
physical 4 KiB leaf base plus VA offset into the low 52 bits. Bits 62,
61, 60 mean effective writable, user-accessible and executable,
respectively, computed across all four levels. Physical address zero is
therefore unambiguous on success. Bits 52–59 are zero.

The deliberately restricted mode admits only 32–52-bit physical
addresses, canonical 48-bit virtual addresses and four present 4 KiB
entries. It rejects PML4E/PDPTE/PDE PS and global bits, physical
addresses outside MAXPHYADDR, and reserved bits 52–62. PTE PAT and
global flags remain permitted. Bit 63 is interpreted as NX at any
level, assuming the caller has separately verified EFER.NXE=1.
No 1 GiB/2 MiB page, LA57, PCID, EFER, CR0.WP semantics, concurrency
or platform-independent TLB rules are implemented.

An independent Python oracle checks exact entry interpretation,
invalid inputs, randomized cases, the dishonest always-accepting HIA
negative control, and `.text` identity across the genuine HIA object
and linked shared image. These are supplied-entry semantics, **not**
a hardware MMU walk, a general VMM or complete Linux functionality.
The pinned HIA toolchain, full 17-gate HOLD, 422 syscall obligations,
and temporary non-HIA boot bridge remain unchanged.
