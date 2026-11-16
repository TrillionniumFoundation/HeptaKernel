# Remaining implementation work

The acceptance target remains the full pinned Linux scope. The first bootable
allocator milestone closes only its stated component tests. Work proceeds in
dependency order, preserving the exact baseline and every unmet obligation in
`compatibility/coverage.json`.

1. Extend the actual upstream HIA verifier, native compiler and target profile
   for privilege instructions, interrupt entry/return, control registers,
   port I/O, MMIO, atomics/fences, static storage and linking. Test encodings
   independently and retain precise safety/effect semantics. Replace the
   current `.S` bridge only when equivalent HIA code has passed boot and
   fault-injection tests.
2. Import the complete source/Kconfig/UAPI/driver/ABI baseline inventory without
   truncation. The present first-level families and x86-64 syscall table are
   initial coverage obligations, not a complete translation inventory.
3. Extend the actual Multiboot-v1 QEMU handoff admission bridge to verified
   provenance on real hardware, UEFI and other platform transports. The
   current non-HIA `boot.S` obtains bounded Multiboot rows, copies them
   to the verified native HIA E820 checker and only then allows its fixed
   4–8 MiB test arena; it is not an arbitrary RAM discovery or ownership
   framework. Handle discontiguous usable ranges, all firmware/loader
   reservations, multiple zones, aligned runs and ownership. Then add
   a virtual-memory manager, permissions, W^X, page-fault handling and lifecycle
   tests. The current fixed arena must not be mistaken for discovery of RAM.
4. Implement interrupt controllers, clocks, task/context switching, user-mode
   entry, ELF loading and Linux syscall dispatch, with independent success and
   error-path tests before treating any syscall as implemented.
5. Build SMP/preemption, signals, process lifecycle, credentials and isolation;
   add VFS, persistent storage, filesystem and networking behavior. Use upstream
   tests and unmodified userspace as independent oracles.
6. Expand every architecture, configuration, filesystem, network and hardware
   obligation in the pinned baseline. Keep unsupported, failed, skipped and
   untested results visible and distinct. Complete formal/concurrency/security
   arguments where required by the claimed scope.

Source hashes, object and image hashes, test inputs, commands and actual outputs
must travel together. A new candidate invalidates evidence for changed behavior
until it is rechecked. Never close an obligation by renaming a file, emitting
opaque instruction bytes, generating placeholders, dropping failed cases, or
returning ENOSYS for an implemented Linux syscall.

`make full-acceptance` must remain HOLD until the complete ledger and its
independent evidence satisfy the full-target conditions. Its mechanical checks
are an evidence aggregator; a green manifest alone is not a correctness proof.
