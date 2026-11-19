# Native HIA x86-64 CR3 state admission (restricted profile)

This component is compiled **directly** from `src/x86_cr3_gate.hepta`
with the locked HIA Core v8 self-hosted ELF backend and an explicit
`exports(cr3_admit)` scalar ABI. The conventional `f0` buffer entry
cannot accept five scalar parameters. The native `cr3_admit`
function takes five SysV AMD64 `u64` arguments:
`candidate_cr3, observed_cr0, observed_cr4, observed_efer, maxphyaddr`.
It returns a `u32` admission result without touching hardware state.

The deliberately restricted initial four-level long-mode profile requires
CR0.PE/PG/**WP**, CR4.PAE, EFER.LME/LMA/**NXE**, a 32–52-bit physical-address width,
CR4.LA57=0, CR4.PCIDE=0, a nonzero 4 KiB-aligned root page-table base,
PWT/PCD as the only permissible CR3 low bits, and no unsupported high bits.
The WP and NXE requirements are deliberate *policy* restrictions:
CR0.WP=0 would allow supervisor writes through read-only mappings, while
EFER.NXE=0 does not provide the execute-disable semantics needed by this
kernel's NX page policies. A CPU with an otherwise valid long-mode state
but either bit clear is rejected with status 2. These are not universal
requirements for a legal x86-64 CR3 load. The independent oracle exercises
missing WP and missing NXE separately, including positive instances with
both bits set.
This is not a claim that all legal Intel/AMD CR3 configurations are supported.

Result codes: 0 = admitted, 1 = bad width, 2 = mode unavailable,
3 = PCIDE/LA57 outside this initial profile, 4 = bad root/flags/width.
A dishonest all-accepting program is separately compiled from actual HIA
and must be rejected by an independent native oracle.

The scalar inputs are **caller-supplied observations, not authenticated CPU
state**. This checker does not perform CR3 reads/writes, validate the physical
contents or ownership of the root page tables, establish per-CPU TLB
invalidation, manage PCIDs, execute QEMU kernel-mode instructions, or prove
any Linux functionality. The boot bridge remains non-HIA. The upstream HIA
privileged verifier and self-hosted machine-code emitter are still required
before using this admission predicate as part of a privileged transition.
All 17 full Linux gates and 422 syscall obligations remain open.
