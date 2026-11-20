# Live x86-64 page-table check before native HIA COW abort

This experiment advances `src/cow_abort_pte_guarded.hepta` beyond a host
readbuf oracle into one real, isolated QEMU CPL0 write-protection #PF path.
The **HIA source and pinned native selfhost_elf object are unchanged**.
`arch/x86_64/boot.S` is explicitly a **NON-HIA hardware and provenance
observer**, not a HIA exception entry, compiler feature, or Linux VM.

## Physical experiment

Both PC/32 MiB and Q35/64 MiB first admit two physically distinct 4 KiB
frames through the retained Multiboot E820 data and HIA PMM owner checks.
Real HIA installs the read-only user/NX source PTE at the 4 MiB test VA,
and the CPU warms the mapping. The live leaf is `page_table_4m`;
the test bridge saves the resulting CPU-observed PTE, including A.

A real CPL0 write raises #PF with error P=1,W=1,U=0 at the exact
store and CR2. The original HIA `cow_split_f0` copies the full
4 KiB source and performs source count 2 -> 1 and private count 0 -> 1.
A deliberately valid-but-stale expected-old PTE passed to the original
HIA `cow_pte_f0` fails with exact status 9 and no PTE publication.
The bridge sets the post-split expected counts and freezes the **original
live PTE** in the HIA state header bytes 8..15. For the guarded case, it
calls original HIA `cow_abort_pte_guarded_f0` with the first eight bytes of
the **actual active page-table leaf**, *not* a copied snapshot; HIA
checks exact-old, then zeros the entire destination and restores counts.
The independent observer checks the complete 4 KiB source, destination,
4096-byte refcount table (including frozen PTE bytes), PTE, and sentinels.

## Failure controls

- `guarded-noop`: substitute a deliberately dishonest HIA function
  returning zero without mutations; full RAM readback must reject it.
- `guarded-stale`: change only the frozen expected-old PTE's cache bit.
  Exact HIA status **8** and unchanged 4096-byte refcount table, full
  destination, hardware PTE and guards are required.
- `guarded-published`: mutate the *actual live PTE* cache bit **after**
  the HIA copy, before guarded abort. Exact status **8** must refuse,
  again with full-byte no-write checks. This deliberately simulates
  a competing publication but is **not** an SMP race experiment.

Existing `abort` and `abort-noop` run unchanged alongside the new
controls. All four new modes must end with the expected negative-test
exit 35, their unique event marker, an observed hardware #PF, a prepared
HIA copy, and no false successful COW completion. The report includes
each exact boot-image SHA-256, QEMU command, stdout, stderr and exit.

Run `make test-cow-integrated-hw` with the pinned native HIA compiler.
It is part of `make test-boot` and `make test`. The Foundation CI checks
native object text identity before accepting the hardware observations.

## Boundaries

The new test only connects a live page-table **read** to a genuine native
HIA prepublication cleanup under a non-HIA caller's exclusive,
quiescent ownership assumption. It does not authenticate the CR3→leaf
path inside the HIA source verifier, make the eight-byte read atomic with
the 4096-byte zeroing, or prevent a publication immediately after guard
success. In particular, the injected PTE mutation is intentionally
serialized, not concurrently scheduled. Real native privileged HIA
CRx/exception/IRET/INVLPG, CAS/memory-ordering, SMP shootdown, lifetime
authority, comprehensive Linux process/syscall/driver/architecture tests
remain **open**.

The fixed Linux 7.3.4 commit and HIA toolchain lock are unchanged.
The entire 17-gate acceptance ledger stays HOLD and all 422 x86-64 syscall
rows remain unimplemented. Never treat isolated QEMU PASS as full closure.
