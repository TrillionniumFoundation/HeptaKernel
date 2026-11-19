# Native HIA x86-64 2 MiB user huge-page PDE commit

`src/x86_pde_2m.hepta` is an actual HIA Core v8 `selfhost_elf`
program, compiled with the unchanged locked upstream self-hosted HIA
compiler. It is separate from `src/x86_pt_commit.hepta`, whose validation
is for 4 KiB PTEs and **intentionally forbids the large-page PS bit**.

## Exact ABI and contract

`f0(request:readbuf, reply:mutbuf, table:mutbuf)` accepts a 32-byte
little-endian request: `slot, expected_old, candidate, caps` (four u64).
The table is one **exactly 4096-byte** page-directory page. The reply has
at least 16 bytes, containing u64 status and value. `caps` encodes
observed MAXPHYADDR 32..52 (bits 0..7), active EFER.NXE (bit 8), and
active CR4.PGE (bit 9).

Admission requires a present 2 MiB PDE with PS=1, physical base aligned
to 2 MiB and below MAXPHYADDR. The huge-leaf PAT bit 12, PWT/PCD,
Accessed/Dirty, and software bits 9..11 and 52..58 are admitted and
preserved; actual reserved address bits 13..20 and unsupported high-key
bits 59..62 remain rejected. The existing policy enforces W^X,
prohibits USER+GLOBAL, and refuses NX without NXE and GLOBAL without
PGE. The requested slot must be <512; all bytes of the existing entry
must equal `expected_old` before the first store. The successful
single-owner commit writes only the requested 8-byte PDE.

Statuses: 0=committed; 1=short reply (no writes); 2=bad request size;
4=bad table size; 6=invalid slot/PDE; 8=bad or unsupported CPU caps;
9=stale-old mismatch. Every refusal leaves the entire page directory
unchanged. An adequate reply receives status and a zero value.

This is **not an atomic CAS**. It requires exclusive ownership of the
page directory, stable capabilities and non-overlapping buffers. It
does not prove allocator ownership, upper-level U/S propagation, TLB
shootdown, SMP races, access/dirty emulation, PAT/MTRR, DMA, or kernel
memory lifecycle.

## Real QEMU hardware path

In the isolated CPL3->CPL0 #UD experiment, the NON-HIA bridge retains
CPU setup, PML4/PDPT U/S propagation, CR3 flush, `iretq`, and the
exception entry. The genuine HIA writer now **actually replaces the
two hand-written 2 MiB PDE stores**:

* slot 2 (4 MiB): `0x400085`, user-readable and executable, not writable
* slot 3 (6 MiB): `0x8000000000600087`, user-readable and writable,
  NX with hardware EFER.NXE enabled

The bridge checks the HIA reply and physical table readback before
flushing CR3. PC and Q35 QEMU then execute the same real CPL3 #UD and
TSS.RSP0 privilege-stack transition as before. The separate
`ring3-pde-stale` image mutates the expected-old word, requiring
status 9 and unchanged slots 2 and 3, and forbids proceeding to IRET.

`make test-x86-pde-2m` executes a separately written Python byte-array
oracle over guarded buffers, many valid and rejected inputs, and a
deliberately dishonest native HIA control. `make record-build` repeats
the native compiler with empty PATH, verifies undefined-symbol absence,
and compares the entire compiled `.text` against both linked QEMU
images and the fault-injection image. All outcomes are tied to the exact
candidate and recorded as distinct success, refusal and failure.

## Limits

This is a narrow actual page-table writer, not a privileged HIA
backend or Linux virtual memory manager. The HIA backend still lacks
`mov cr*`, `invlpg`, `iretq`, exception entry, MMIO, atomics,
ordering and general static linker facilities. The 17 complete Linux
acceptance gates and 422 x86-64 syscall obligations remain HOLD.

## Linux huge-page metadata admission (2026-11-18)

The original 2MiB PDE mask incorrectly rejected architectural cache/A-D/PAT
flags and Linux software bits. The native HIA guard now distinguishes the
2MiB frame address (bits 21..51) from the huge-page PAT flag at bit 12.
An independent byte-exact oracle probes every admitted flag, both reserved
ranges, combined flags, full expected-old mismatch and denied capability
combinations. Existing PC/Q35 hardware tests still exercise the actual HIA
writer; they do not establish PAT/MTRR semantics, atomicity, TLB shootdown,
SMP safety or general Linux huge-page compatibility.

## Exact-old 2 MiB PDE removal (isolated candidate, 2026-11-19)

A **zero** `candidate` is a removal request. The actual HIA Core v8 native
program now admits it only when the caller-supplied `expected_old` describes
a present 2 MiB leaf (P=PS=1), has no reserved address/high-key bits,
fits MAXPHYADDR and does not demand NXE/PGE features absent from the
caller-supplied CPU snapshot. Slot bounds and the complete eight-byte
current-word equality check still precede the write. A successful removal
writes eight zero bytes only at the selected PDE, and returns status 0 and
value 0. A replay after a prior removal returns status 9; an absent or
non-huge old entry returns status 6, even if its bytes match.

The independent byte-array oracle now includes positive removals with
different physical bases, software metadata and neighboring entries, stale
replays, invalid old-leaf forms, missing CPU features and the original
nonzero/W^X admissions. `make test-x86-pde-2m` and the complete Foundation
CI are the required native HIA evidence for the exact candidate; source-only
edits are not a pass.

This is single-owner quiescent **memory-byte removal**, not an atomic CAS,
a hardware-verified 2 MiB unmap, TLB invalidation, safe page-frame reuse or
Linux `munmap`. A later independent PC/Q35 hardware experiment must warm
the leaf, perform the genuine native removal, invalidate the translation via
an explicitly identified non-HIA bridge, observe #PF with exact CR2/error
code/IST, and reject stale and restored-PDE negative controls. Only a
future genuine HIA privilege/atomics backend can replace that bridge.
