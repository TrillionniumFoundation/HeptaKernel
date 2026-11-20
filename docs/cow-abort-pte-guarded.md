# Native HIA COW prepublication abort guarded against a live PTE

`src/cow_abort_pte_guarded.hepta` is genuine Core v8 `selfhost_elf` source,
not assembly renamed to HIA. This is a **restricted single-owner, quiescent**
step toward preventing the erroneous cleanup of a private COW destination
after a successful PTE publication. It does not replace the prior
`cow_abort` routine or modify the fixed HIA compiler.

## Input and result contract

The three HIA buffer capabilities are:
- `pte:readbuf`: exactly eight bytes, **directly bound by a trusted caller
  to the actual PTE in physical page-table memory**; no copied/forged PTE
  may be passed as evidence of liveness. In ordinary native tests this is an
  eight-byte buffer; independent QEMU hardware provenance is not yet proven.
- `destination:mutbuf`: exactly 4096 bytes, unpublished and exclusively
  owned by the caller.
- `state:mutbuf`: exactly 4096 bytes; header offsets 0:2 source slot, 2:4
  destination slot, 4 and 5 expected post-split counts, 6:8 zero, and
  8:16 the expected *prepublication* 64-bit PTE in little endian.
  Bytes 16:4096 contain 4080 u8 reference counts.

First the HIA function checks the exact readbuf length and state size,
then compares **all eight bytes** of the actual PTE against the frozen
expected PTE in the state header. The PTE must be Present+User+ReadOnly,
NX, non-Global, have a nonzero 4KiB physical frame address, and contain
no bits 52..62. This is a deliberately narrow policy: NXE and physical
address width remain externally validated. It subsequently performs the
existing abort checks for zero reserved bytes, distinct slots, matching
counts, source count 1..254 and destination count exactly 1.

Only after all checks pass does HIA zero the whole destination page,
increment the source count and reset the destination count to zero.
Failures leave the destination and state byte-for-byte unchanged.

Return values: 0 successful cleanup; 1 destination length, 2 state size,
3 nonzero reserved bytes, 4 invalid slots, 5 stale counts, 6 disallowed
ownership, 7 readbuf length, 8 PTE differs from frozen expected old, and
9 malformed or unsafe original PTE.

## Verification

`make test-cow-abort-pte-guarded` compiles the HIA source using the
locked selfhost compiler, checks exact object bytes under empty PATH,
and runs an independent Python byte oracle, canary checks, edge-slot cases,
negative malformed/stale PTE cases, real OS guard pages (including a
read-only PTE at the last eight bytes before PROT_NONE), a deliberately
dishonest always-success HIA implementation and round trips with the
**real** `cow_split` object. It is required by `make test` and Foundation CI.

## Unclosed properties

This step catches a live PTE that differs from a caller-saved original
only if the trusted caller really passes its *live* table location.
The source cannot authenticate its buffer pointer as the active CR3's
leaf, bind the PTE physical frame to a PMM owner, or prevent a concurrent
publisher from racing after the read. The expected PTE is still supplied
through mutable caller state. A+D hardware modifications can produce
conservative false rejections, and even a successful guard followed by
partial zeroing or count writes is not an atomic transaction. Real QEMU
execution of this **new** guard, privileged source-language PTE/CAS/INVLPG,
interrupt/IRET entry, SMP/TLB shootdown, and all Linux ABI functionality
remain open. Do not infer new closure from preexisting QEMU regression tests.

The complete 17 Linux acceptance gates and 422 x86-64 syscall obligations
remain HOLD; the Linux 7.3.4 and HIA toolchain SHA locks are unchanged.
