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
   bridge invokes `ltr` after real HIA transactionally installs RSP0,
   IST1 and the I/O bitmap offset in the TSS with independent stale-old
   refusal for RSP0 and IST1; the hardware RSP0 ring-transition path is
   now has an isolated PC/Q35 CPL3-to-CPL0 #UD hardware test: native HIA
   provisions TSS.RSP0 and the IST0 IDT vector, while an explicitly non-HIA
   IRETQ observer enters CPL3 with separate U/RX code and U/RW/NX stack
   pages. The hardware #UD frame must land exactly at TSS.RSP0-40, with
   user CS/SS/RIP/RSP verified. A post-HIA RSP0 decoy mutation must be
   detected at the *other* real exception stack. This is not a HIA privilege
   backend, user task or syscall implementation;
   the isolated CPL3 path now asks a genuine native HIA exclusive-owner
   2 MiB PDE writer to commit both user RX and user RW/NX huge-page
   mappings, with independent stale-old refusal and QEMU physical hardware
   execution. A genuine native HIA upper-level 4KiB table writer now
   validates PML4E/PDPTE present/RW/aligned table pointers, physical width,
   reserved and Accessed flags and expected old entry, then changes only
   U/S under exclusive-owner quiescence. Both real upper U/S grants in the
   isolated PC/Q35 CPL3 path use its native code, check actual table readback
   and separately reject an injected stale PML4E old value. The native
   source/object/live image bytes are independently bound; the 2MiB leaves
   remain native HIA as above. TLB/CR3 privilege and IRET/exception entry
   remain in the expressly NON-HIA test bridge. This is not a general
   VMM, a two-word atomic transaction, an authority proof, or a
   SMP atomically linearizable page-table manager;
   a native HIA single-owner paired CPL3 code/data GDT writer now
   replaces test-only assembler-preinitialized user selectors 0x30/0x38,
   with expected-old admission and a separate stale-word QEMU refusal.
   It is validated by the genuine CPL3 #UD stack path but does not implement
   IRETQ, context switching or Linux user execution. A native HIA
   single-owner GDT writer now installs the 16-byte 64-bit TSS descriptor
   at selector 0x20 with an independent stale-word negative control. The
   bridge loads IDT (`lidt`), samples CRx,
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

The native supplied-entry x86-64 4KiB four-level HIA walk policy
(`src/x86_walk4_entries.hepta`) combines canonical-address, present,
reserved-bit, physical-width and inherited RW/U/S/NX checks in genuine
HIA machine code, with independent native oracle and dishonest control.
It does not independently fetch or authenticate indexed physical tables;
actual CR3, TLB, ownership, concurrency, large-page and HIA privileged
backend closure remain outstanding.

The HIA indexed four-level snapshot reader (`src/x86_walk4_indexed.hepta`)
now computes all four VA indices itself and binds three physical parent
links against caller-declared page identities, with independent byte-level
oracles and a dishonest HIA control. These are copied 16 KiB snapshots, not
authenticated physical RAM nor a real CPU CR3/MMU walk. Hardware privilege,
source-provenance, concurrent mutation and TLB coherence remain open.

The native automatic indexed 4KiB/2MiB/1GiB snapshot translator
(`src/x86_walk4_auto.hepta`) derives page size from the first
L3/L2 PS bit and tests only traversed physical parent links. The 48-byte
request and fixed 16KiB copied snapshots still require L3/L2/L1 identities
even when huge-page descendants are unused. This is native HIA selfhost code
with an independent oracle and a dishonest HIA negative control, but does not
authenticate actual physical RAM, CPU 1GiB/NXE capability, ownership, CR3,
TLB/SMP synchronization or complete Linux compatibility.

The real HIA scalar access policy in `src/x86_access_gate.hepta` now consumes
HIA-translated page rights with an explicit CPL0/CPL3, AC, WP, NXE, SMEP
and SMAP snapshot profile. The independent native oracle and all-grant
negative control check the *caller-supplied* snapshot. Hardware CPL,
privileged CRx access, CPU-state provenance, coherent epochs and TLB/SMP
remain open; this does not implement Linux user-mode memory isolation.

Native HIA now has a restricted **leaf removal** primitive in
`src/x86_pt_revoke.hepta`: exact-old Present entry check, zero replacement,
quiescent single-owner write, independent native oracle and dishonest control.
It does not prove hardware MMU revocation, TLB shootdown, concurrent atomicity
or physical-frame recycling; see `docs/x86-pt-revoke.md`.

An isolated live MMU revocation experiment now calls native HIA
`x86_pt_revoke` on the real 4 MiB PTE after warming its translation, then
uses a clearly NON-HIA `invlpg` bridge. Hardware #PF must match exact
CR2/RIP, non-present-read error and IST1. Stale-old refusal and test-only
restored-mapping bypass are independent controls. This does not deliver
native HIA privilege/exception instructions, concurrent ownership,
multi-CPU shootdown or safe frame recycling; see `docs/x86-pt-revoke.md`.
