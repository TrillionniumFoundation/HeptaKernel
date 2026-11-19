# Native HIA PML4 root scanner on actual QEMU CR3 RAM

This isolated PC 32 MiB / Q35 64 MiB experiment uses unchanged
`src/x86_cr3_root.hepta` machine code produced by the pinned upstream HIA
Core v8 selfhost compiler. A clearly **non-HIA** long-mode observer reads
hardware CR3 and CPUID MAXPHYADDR, verifies CR3 equals the identity-mapped
PML4 page, and passes its actual 4096-byte physical-memory buffer to the
HIA routine. The expected root has exactly one present PML4E, at index 0.
Native HIA must scan 512 entries and report (status=0, present_count=1),
while the bridge checks that actual CR3 remains unchanged.

Independent negative cases: a copied root with PS=1 at PML4 must yield
status 7; a copied root with its required present bit cleared must yield
status 5. A separate selfhost-native dishonest always-accept HIA object
must visibly pass a forbidden snapshot and be rejected by the oracle.
Finally, a forged root with a *different, syntactically valid* physical
table pointer demonstrates a trust boundary: native HIA admission of
supplied bytes succeeds, but a non-HIA pointer comparison must refuse the
copy because it is not the live CPU CR3-named physical page.

All three images are run on both PC/32 MiB and Q35/64 MiB by
`make test-cr3-root-hw` (also in `make test`). The QEMU runner records
all commands, exact exit statuses, raw stdout/stderr, image hashes and
source/object machine-text equality in
`build/cr3-root-hardware-report.json`. An exit code 35 is expected only
for the explicitly named negative-control images.

The bootstrap, CR3 and CPUID reads, serial, all special-register I/O,
and identity mapping are **not HIA**. The experiment does not authenticate
firmware ownership, prevent concurrent root updates, prove RAM integrity,
perform atomic PTE replacement, invalidate remote TLBs or implement Linux
syscalls/process isolation. This is an actual CPU-root input test, not
HIA-native privilege semantics or a full Linux closure claim.
