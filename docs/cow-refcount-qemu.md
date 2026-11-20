# Native HIA COW reference-count transitions in isolated QEMU

This experiment runs **original pinned HIA Core v8 selfhost_elf x86-64** from
`src/cow_refcount.hepta` on PC (32 MiB) and Q35 (64 MiB) with Multiboot E820,
reservation admission, and two independent HIA PMM states. The symbol-only
rename `f0 -> cow_refcount_f0` is checked against original `.text` bytes.
The table is actual, aligned, writable 4 KiB guest RAM; HIA itself performs
every reference-count table write.

A clearly **NON-HIA test bridge**, after authentic HIA PMM allocation, supplies
a test-only mapping for two slots (2,17), initializes the count table to 0x5b
except counts 1, and invokes share (1 -> 2), detach (2 -> 1), release (1 -> 0)
on both. After every transition the bridge checks actual guest RAM and all
16 receipt bytes. After both cycles an independent full 4096-byte byte
comparison checks that **all 4094 other slots remain unchanged**, together
with surrounding canary words. The return value alone never establishes
success. This does **not** bind the slots to an authenticated PMM frame handle;
the mapping from two PMM domains is test-only.

Three independent negative images, each on both machines, must fail:

* A genuine HIA malicious no-op returns success without writing RAM; the
  independent count readback catches it.
* A genuinely compiled HIA receives a stale expected-old detach count after a
  successful share. Only status 7, count 2 still present and an unchanged
  sentinel receipt produce the precise stale-refusal marker, before the
  expected failure exit. Generic failure is not accepted as a valid stale test.
* The honest HIA sequence completes, then a hostile NON-HIA bridge corrupts
  an unrelated table byte; the full-table oracle must reject it.

Run `make test-cow-refcount-hw`; `make test-boot` and `make test`
include the same two positives and six negative controls.
The machine/image SHA-256, actual command, return code and stdout/stderr
are recorded at `build/cow-refcount-hardware-report.json`.

This is **not** an atomic compare-and-swap, concurrent refcounting, a page
fault, true COW, or Linux userspace ABI. Physical address coordination,
privileged boot, E820 transport, machine-code linkage and observations still
rely on the explicit non-HIA test bridge. The entire pinned Linux 7.3.4
acceptance remains HOLD with the same 17 gates and 422 x86-64 syscall rows.
