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

A native HIA 4KiB RW->RO permission downgrade now preserves A/D, PAT,
physical frame and all other entry bits, and refuses stale expected-old
requests with an independent byte-level oracle and dishonest HIA control.
It assumes exclusive quiescent ownership: no native HIA TLB flush, SMP
shootdown, atomic 64-bit PTE CAS, or Linux mprotect is implemented; see
`docs/x86-pt-write-protect.md`.

Native HIA now has an additional exact-old **RX to non-executable** 4 KiB
PTE downgrade (`src/x86_pt_nx_protect.hepta`) preserving all other bits,
including Accessed/Dirty and physical frame address. It requires quiescent
exclusive ownership and an NXE-capable CPU profile. Native differential
oracle, dishonest HIA negative control, and source/object/loaded-text
binding cover this restricted transition. Hardware fetch-fault observation now exercises original HIA RX->NX
machine code on PC/Q35, verifying exact #PF error/CR2/RIP/IST1,
stale-old refusal and restored-execution bypass. The non-HIA
INVLPG/exception bridge remains; HIA privileged TLB invalidation,
atomic PTE replacement, SMP shootdown, ownership provenance and Linux
`mprotect` remain open.

An isolated CPL3 x86-64 user-to-supervisor permission hardware experiment now
uses the genuine original `src/x86_pt_user_revoke.hepta` native HIA .text on
a real 4KiB PTE. A first user-mode #UD demonstrates that the original user
RX page was executable; the explicitly non-HIA exception bridge calls HIA to
clear only U/S, preserving the CPU-updated Accessed bit. After a non-HIA
INVLPG and IRETQ to the **same user RIP**, the CPU must produce #PF with
P=1, U=1 and I/D=1 on IST1, with exact CR2/RIP/CS/SS/user RSP.
Two independent controls exercise a valid but stale expected-old value and a
deliberate post-HIA regrant of U/S, which must permit the original user UD2
to execute again rather than count a generic fault as success. Native HIA
also commits the first 4KiB user RX leaf; the test-only bridge still handles
parent-table pointers, privileged CR3/IDT/TSS, INVLPG and IRETQ. This is
single-CPU QEMU evidence, not atomic PTE writes, SMP shootdown, Linux mprotect,
or a fully HIA-native privilege/backend capability.

A native HIA 1GiB PDPTE commit/removal primitive in `src/x86_pdpt_1g.hepta`
checks the caller-supplied PDPE1GB/NXE/PGE and physical-width profile, 1GiB
alignment, reserved bits, PAT bit 12, W^X, USER+GLOBAL and exact-old entry.
The native byte-array oracle, dishonest control and empty-PATH machine-byte
identity remain required. An isolated QEMU TCG CPU/MMU experiment now exercises
a 1GiB alias first created by native HIA, observes CPU-set Accessed and then
uses native HIA to zero the *updated* PDPTE. Non-HIA INVLPG/IDT/CR2/IST1
hardware observation requires the exact subsequent supervisor non-present
read #PF. Independent stale-old refusal and post-HIA mapping-restoration
bypass images verify that rejection preserves access and restoration defeats
the fault, respectively, on PC/32MiB and Q35/64MiB. None of this supplies
native HIA privilege/CRx/invalidation, atomic CAS, SMP TLB shootdown,
firmware memory ownership, safe reclamation or Linux munmap semantics.
The full 17-gate closure remains HOLD; the 422 syscall rows are unchanged.

The single-page native HIA TLB ordering admission additionally binds its
first expected PTE old value to a separate eight-byte caller-supplied entry
capability rather than only a self-declared row observation. See
`docs/x86-tlb-entry-binding.md`. This is byte-level checking, not authenticated
physical RAM, a privileged HIA instruction backend, atomic CAS or SMP safety.


The genuine HIA Core v8 PML4-root admission primitive
(`src/x86_cr3_root.hepta`, `docs/x86-cr3-root-native.md`) now scans all
512 64-bit entries in a caller-provided, exactly 4 KiB CR3 root-page
snapshot, rejecting malformed present descriptors and absent required
root slots. It has independent byte-oriented native tests, dishonest HIA
negative control, deterministic object bytes and retained Foundation CI
artifacts. This is a *read-only supplied snapshot*, not proof that the
current CR3 points to that page or that live page-table RAM is immutable.
Hardware root ownership, verified privilege transitions, atomic updates,
TLB shootdown and full user/driver/ABI functionality remain unmet. No
full-acceptance gate is closed by this component.
