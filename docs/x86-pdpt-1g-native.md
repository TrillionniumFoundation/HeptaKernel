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

A new entry must have Present and PS set. The base address uses bits
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
