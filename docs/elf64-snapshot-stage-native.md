# Native HIA bounded ELF snapshot staging

This component adds `src/elf64_snapshot_stage.hepta` to the locked HIA Core v8
`selfhost_elf` path. It copies an entire caller-supplied 64-byte through 1-MiB
ELF image into a separately provided equal-size mutable staging capability
without libc or Linux system calls. The 16-byte success receipt is written
**after** the native HIA copy completes. Invalid source bounds (status 1),
wrong destination length (status 2), or receipt shape (status 3) are rejected
before any destination or receipt write. Success is status 0 and marker A5 5A,
with the remaining receipt bytes zero. The staging buffer retains a complete
byte copy if the caller later changes the original source.

The independent Python oracle checks exact content, input immutability,
guard canaries, read-only source with real inaccessible neighboring pages,
positive/negative sizes, short or long destination and receipt, late input
mutation, and a genuinely HIA-compiled dishonest no-copy program. CI also
checks object/shared-library `.text`, no undefined native symbols, and
two empty-PATH native object recompilations. It is wired into `make test`,
the Foundation workflow and its evidence artifact.

## What this does not establish

The caller must still ensure the source is stable **during** copying,
nonoverlapping buffer capabilities, a trusted stage allocation with exclusive
ownership, and prevention of DMA or SMP writes to staged memory. The receipt
is not a cryptographic attestation or authorization. This change does not yet
route the QEMU `boot.S` fixture's ELF layout checker, planner and page filler
to a new owned staging object, so it is a validated native building block, not
an authenticated immutable ELF snapshot, an atomic exec transaction, a user
PTE publisher or a Linux `execve` implementation. The 17-gate full Linux
acceptance remains HOLD, including all 422 syscall obligations.
