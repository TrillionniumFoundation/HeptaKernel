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
The 1GiB code is not linked into a boot image and **no hardware 1GiB
translation test is claimed**. Real hardware invocation, CR3/TLB coherence,
1GiB capability provenance, atomic CAS, SMP shootdown and frame reclamation
are open, as are all 17 full-Linux acceptance gates.
