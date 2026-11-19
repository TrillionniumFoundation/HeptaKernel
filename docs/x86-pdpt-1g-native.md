# Native HIA 1GiB PDPTE writer

`src/x86_pdpt_1g.hepta` is real HIA Core v8 `selfhost_elf`
source, compiled with the pinned native compiler. It implements a restricted
single-owner, quiescent 1GiB page-directory-pointer-table (L3) leaf write.
It is not a general kernel virtual-memory manager or hardware-backed
privilege operation.

The 32-byte request is four little-endian u64 values:
`slot`, `expected_old`, `new_entry`, `caps`. The 4096-byte mutable
table holds 512 PDPTEs; reply consists of u64 `status` and `value`.
Capabilities are physical address width in low eight bits (32..52),
NXE enabled (bit 8), PGE enabled (bit 9), and CPUID PDPE1GB supported
(bit 10). No other caps bits are admitted. PDPE1GB is required even if
the requested entry does not set NX. The caller must bind these bits to
actual CPU state; this primitive does not read CPUID, CRx or MSRs.

For a new mapping, the entry must have Present and PS set. The base address uses bits
30..51 (1GiB alignment); bit 12 is PAT, **not** a frame-address bit.
Bits 13..29 and 59..62 are rejected. Low architecture flags and software
bits 52..58 are preserved. The admission also enforces W^X, disallows
User+Global, checks NXE/PGE and MAXPHYADDR, and compares the entire old
64-bit word before writing. A successful write changes only one PDPTE,
but its eight byte stores are **not atomic** and therefore are unsafe
under concurrent CPU ownership or active page walks.

`make test-x86-pdpt-1g` runs an independently coded byte-array oracle
over guarded request, reply, and page-table buffers, including reserved
bits, capability refusals, stale expected values, and a dishonest native
HIA all-accept negative control. `make record-build` recompiles under
empty PATH and compares native object and shared library `.text` bytes.
The same native object is now symbol-renamed without changing its .text and
linked into three isolated QEMU boot images. The non-HIA CPL0 harness reads
actual CPUID PDPE1GB, uses the active NXE/MAXPHYADDR profile, and requests
the genuine HIA function to install a present 1GiB RX alias at virtual
0x40000000 pointing to physical zero. After exact-old and table readback,
the explicit non-HIA CR3 reload makes a CPU page walk consume that PDPTE:
two distinct physical/virtual word addresses must match, and the CPU must
set the PDPTE Accessed flag. The stale-old negative image requires status
9 and no table write; an independent post-write decoy clears Present and
must fail before the hardware alias may be claimed. Both PC/32MiB and
Q35/64MiB run under TCG with qemu64 + PDPE1GB. These tests touch only
known in-image low-RAM bytes, not all memory described by the huge mapping.

The build-byte check compares the exact native HIA .text in all three live
images, and retains the distinct boot image hashes. This demonstrates one
restricted 1GiB hardware translation, **not** real-CPU qualification, HIA
CR3/privilege support, arbitrary firmware RAM access, physical ownership,
atomic CAS, SMP shootdown or frame reclamation. The 17 Linux full-acceptance
gates remain open.

## Exact-old 1GiB leaf removal (isolated native path)

A zero `new_entry` now selects a separate real-HIA admission path that
requires the **existing** PDPTE to be Present and PS=1, checks its 1GiB
physical address against MAXPHYADDR, refuses reserved address bits 13–29 and
unmodeled 59–62, and validates the *old* NX/PGE and PDPE1GB capabilities.
The complete old 64-bit PDPTE is re-read before the quiescent single-owner
write of zero. A stale second request must fail without changing memory.
The independent native byte-array oracle checks 320 removal/replay pairs and
negative old-entry/capability cases, plus the existing hostile all-accept
native control; the locked self-hosted compiler builds the production code.

This extends the bytewise owner-local PDPTE primitive; it **does not**
perform a native HIA INVLPG/CR3 reload, synchronized shootdown, 64-bit
atomic CAS, or safely release a physical 1GiB frame.

## Isolated 1GiB removal hardware fault and controls

Three additional Multiboot/QEMU images link the **same native HIA object**
into the exact previous 1GiB hardware alias scenario. The non-HIA observer
first establishes a real `0x40000000` 1GiB alias, reads two words through
the CPU MMU and checks the CPU-set Accessed bit; it then supplies that
*updated* complete PDPTE as `expected_old` to genuine native HIA removal.

* The positive removal image requires native status 0 and exact zero
  table/reply readback, then explicitly invokes non-HIA INVLPG and
  attempts a load from the warmed alias. The independent x86 #PF handler
  requires an IST1 stack, non-present supervisor read error code 0,
  exact faulting RIP and CR2, and the HIA result still zero before exit.
* The stale-old negative changes only PWT in the otherwise legal expected
  old value, requires native status 9, no write and a still-readable alias.
  It must not print a hardware-fault success marker.
* The bypass control deliberately restores the leaf *after* HIA removal.
  Following INVLPG, the formerly removed alias must still be readable;
  observing a #PF is not counted as success for this adversarial image.

PC/32MiB and Q35/64MiB both run in QEMU TCG with `qemu64,+pdpe1gb`.
Each scenario has unique output markers, debug-exit code, image/source
hashes and a byte-for-byte check of the HIA source compiler object
against the native text actually executing in all six images.
These are **isolation experiments**, not Linux `munmap` completion,
hardware qualification, atomic/linearizable page-table management or
reclamation. Privileged IDT, CR2, INVLPG and exception entry remain
explicitly non-HIA test code; the 17 full Linux gates remain HOLD.
