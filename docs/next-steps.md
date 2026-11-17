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
   fault-injection tests. The active 256-vector x86-64 IDT is written
   by a genuine native HIA table installer, including the x86-64 IST index,
   and checked with a stale-word QEMU refusal test. NX and WP fault images
   use HIA-encoded IST1 and independently require the CPU exception stack to
   fall inside the isolated 64-bit TSS IST1 region. The temporary non-HIA
   bridge still creates/loads TSS (`ltr`), loads IDT (`lidt`), samples CRx,
   enters exceptions, and never returns; these are not HIA backend closure.
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
   A two-zone QEMU observer now exercises distinct E820-admitted HIA PMM
   states and physical readbacks, but routing/state binding lives in a
   non-HIA fixture. The HIA read-only bitmap first-fit query can inspect
   current per-arena occupancy without claiming pages; link it to the HIA
   exact-claim primitive through a verified single-owner zone coordinator,
   then implement concurrent linearizable ownership and synchronization.
   Neither query nor a query-then-claim fixture establishes SMP safety.
   A separate native HIA reservation-suffix gate checks caller-supplied
   protected byte ranges. It now runs on the actual QEMU physical-allocation
   path after E820 against image/BSS, Multiboot info and mmap intervals,
   with native byte-identity checks and a conflict/bypass fault-injection
   control. This is still not complete authenticated firmware/UEFI
   reservation discovery or concurrent ownership.
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
