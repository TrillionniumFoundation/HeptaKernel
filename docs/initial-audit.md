# HeptaKernel initial audit and complete-rewrite acceptance contract

Audit date: 2026-11-15. This document records the initial state and the full target. Later implementation evidence must identify its exact candidate commit separately.

## Initial repository state

The initial GitHub API observation found an empty repository, created at
`2026-11-15T17:03:49Z`: zero branches, commits, source files and pull requests.
The repository metadata names `main` as its default branch, but that setting
does not establish an existing branch or commit. The contents endpoint returned
`This repository is empty.` Consequently there was no existing kernel,
implementation, build, test suite, license file, or branch integration to audit.

Sources:

- https://api.github.com/repos/TrillionniumFoundation/HeptaKernel
- https://api.github.com/repos/TrillionniumFoundation/HeptaKernel/branches?per_page=100
- https://api.github.com/repos/TrillionniumFoundation/HeptaKernel/contents
- https://api.github.com/repos/TrillionniumFoundation/HeptaKernel/pulls?state=all&per_page=100

The requested work is a new implementation of the complete Linux target in HIA.
An initial x86-64 boot and memory tranche establishes an executable starting
point. It does not change the complete target.

## Fixed Linux reference

The official kernel.org release index identifies Linux **7.3.4**, released
2026-11-10, as the stable release observed for this audit. The official
changelog begins with commit
`7595a62d45ee1a2297eafa5f2ef5d0a45142d84d`. The stable maintainer's GitHub
mirror resolves annotated tag `v7.3.4`, tag object
`8310b43a724c54668eeaa6860234078a7886915a`, to that same commit.
GitHub reports a valid tag signature; this audit has not independently
verified the signature with a locally trusted GPG key.

Sources:

- https://www.kernel.org/
- https://cdn.kernel.org/pub/linux/kernel/v7.x/ChangeLog-7.3.4
- https://api.github.com/repos/gregkh/linux/git/tags/8310b43a724c54668eeaa6860234078a7886915a
- https://github.com/gregkh/linux/tree/7595a62d45ee1a2297eafa5f2ef5d0a45142d84d

`compatibility/linux-source-lock.json` records this reference and the observed LTP reference
`686a331b6240e54ac3170717adfd28ec94cfe100`. The baseline must remain fixed
through each acceptance campaign. A later baseline update needs an explicit
delta inventory, rather than silently changing the denominator.

## What the source inventory establishes

The audited, untruncated tree listings contain:

| Inventory | Count | Meaning |
| --- | ---: | --- |
| Directories under `arch/` | 21 | Architecture source families; includes User-mode Linux |
| Directories under `drivers/` | 144 | Top-level driver families, not individual drivers |
| Directories under `fs/` | 76 | Filesystem-related source families, not 76 independent filesystem implementations |
| Directories under `net/` | 66 | Network source families |
| Directories under `security/` | 13 | Security source families |
| Rows in x86 `syscall_64.tbl` | 422 | 386 common/native-64 rows and 36 x32-specific rows |

Seventeen of the 386 native/common x86 rows have no implementation entry or
explicitly select `sys_ni_syscall`. Their baseline behavior must still be
preserved. Returning ENOSYS for a syscall that Linux implements does not earn
implementation credit. The 36 x32-specific rows do not constitute the entire
x32 ABI, because x32 also uses shared entries.

These are source inventory counts, not implementation coverage, test coverage,
or completion percentages. A full recursive file, Kconfig, UAPI, driver-device,
and architecture/compat ABI inventory remains to be generated. The incomplete
inventory is explicitly recorded in `compatibility/coverage.json`.

The syscall tables and initial directory listings are bound to the Linux
commit above. Relevant source paths are:

- `arch/x86/entry/syscalls/syscall_64.tbl`
- `arch/x86/entry/syscalls/syscall_32.tbl`
- `scripts/syscall.tbl`
- architecture-specific syscall tables and UAPI headers
- `include/uapi/`, `Documentation/ABI/`, `drivers/`, `fs/`, `net/`
- `tools/testing/selftests/`, `tools/memory-model/`

## HIA toolchain audit

The examined Hepta revision is
`f33d8da316de8fdf27b504371f1a5310997ff548`.

The self-hosted native profile supports typed integer values, control-flow
loops, internal calls, and checked borrowed byte buffers. It can produce
x86-64 machine code and a bounded ELF64 relocatable object profile. Its
legacy borrowed-buffer `f0` interface can support initial freestanding
memory algorithms when a boot environment supplies the buffers and ABI.

The same toolchain documents concrete limitations:

- General object linking is explicitly unimplemented: arbitrary external
  symbols/relocations, resource-bearing public signatures, a general linker,
  and additional ELF targets are outside the supported profile.
- Public scalar exports and the legacy borrowed-buffer `f0` entry are
  bounded interfaces. They do not supply a general kernel module ABI.
- Owned allocation brings `calloc` and `free` imports and assumptions about
  the Linux SysV loader and libc allocation contract. Such objects cannot be
  treated as freestanding kernel implementation without replacing those
  dependencies and verifying the replacement.
- The observed language/backend instruction surface does not supply the
  kernel privilege, interrupt-return, control-register, port-I/O, atomic,
  fence, or device-memory operations required for a complete kernel.
- The separately named Linux kernel object profile accepts only bounded
  straight-line u32 leaf functions. It rejects memory, allocation, calls,
  loops and external effects. It uses the existing LLVM emission path, and
  does not implement boot, MMU, devices or operating-system qualification.

Primary source locations:

- https://github.com/TrillionniumFoundation/Hepta/blob/f33d8da316de8fdf27b504371f1a5310997ff548/tools/hia_selfhost_contract.py
- https://github.com/TrillionniumFoundation/Hepta/blob/f33d8da316de8fdf27b504371f1a5310997ff548/tools/generate_hia_selfhost.py
- https://github.com/TrillionniumFoundation/Hepta/blob/f33d8da316de8fdf27b504371f1a5310997ff548/hepta/hia_machine_x64.py
- https://github.com/TrillionniumFoundation/Hepta/blob/f33d8da316de8fdf27b504371f1a5310997ff548/hepta/hia_linux_kernel.py

Therefore, a temporary `.S` boot/privilege bridge may make useful HIA
algorithms executable in a kernel context, but the bridge remains a non-HIA
target component. It must stay visible in source and artifact provenance,
and the full-HIA gate stays open until the language and backend can replace
and validate it. Renaming assembly to `.hia`, embedding its machine bytes,
or running a hosted HIA program on Linux would not close that gate.

## Machine-readable completion ledger

`compatibility/coverage.json` includes 17 full-target gates, the initial source-family
obligations, and every row in the pinned x86-64 syscall table. All begin as
unimplemented in the empty-repository snapshot. Each later entry needs
implementation paths, evidence paths, candidate commit and scope.

A useful future inventory generator should:

1. Verify the exact Linux commit and enumerate `git ls-tree -r -z` without
   losing paths, submodules or symlinks. Record tree/blob IDs.
2. Extract every `config`/`menuconfig` declaration from tracked Kconfig
   files, preserving file context and architecture dependencies.
3. Parse every architecture syscall table and UAPI generation rule. Keep ABI,
   syscall number, entry name, obsolete/reserved status and structure layout
   obligations distinct.
4. Map drivers to Kconfig/Makefile selection, bus and hardware identifiers,
   firmware requirements, and testable device/platform configurations.
5. Map source families to behavior and tests. A file-to-file translation map
   is useful provenance but is insufficient evidence of equivalent behavior.
6. Retain unimplemented and currently untestable requirements explicitly.

Allowed states distinguish work in progress, implementation without tests,
scope-limited verification, failures, blocked execution, and genuinely
inapplicable baseline cases. Unsupported hardware, skipped tests, missing
labels and timeouts must never become passing tests.

## Acceptance gates

The machine ledger specifies the full requirements. The critical dependency
order is:

1. **Target semantics and builds.** Extend the real HIA language, verifier
   and machine backend for privilege, faults, MMIO, atomicity, memory ordering,
   static storage and linking. Bind target objects to actual HIA sources and
   make exact-candidate builds reproducible.
2. **Boot and memory.** Verify firmware entry, CPU modes, memory maps,
   reserved pages, exceptions, paging, permissions, faults and allocator
   invariants. Test corruption, exhaustion and invalid inputs before adding
   concurrency.
3. **Execution and ABI.** Implement interrupts, timers, preemption, SMP,
   process context, user-mode transitions, syscalls, clone/exec/wait, signals,
   restart behavior and credentials. Preserve ABI layouts and errno behavior.
4. **Persistent and network behavior.** Add VFS, block I/O, filesystem
   families, sockets and network protocols with independent peers and crash
   recovery tests. Then expand the full driver/platform matrix.
5. **Isolation and concurrency.** Verify user/kernel boundaries, LSM,
   namespaces, cgroups, privilege transitions, lock ordering, RCU and memory
   ordering under adverse scheduling and resource pressure.
6. **System compatibility.** Run pinned upstream tests and unmodified
   Linux workloads against both reference Linux and the same HeptaKernel
   candidate. Complete the remaining architecture, ABI, configuration and
   driver obligations before claiming complete closure.

The official kernel testing guide distinguishes in-kernel unit behavior
(KUnit) from user-visible/system behavior (kselftest). LTP adds independent
kernel and system-library test cases. These are complementary sources of
evidence. Their source code need not itself be rewritten in HIA to test the
new kernel; their exact versions, build configuration and dependencies must
be recorded.

Sources:

- https://docs.kernel.org/dev-tools/testing-overview.html
- https://docs.kernel.org/dev-tools/kselftest.html
- https://github.com/linux-test-project/ltp/tree/686a331b6240e54ac3170717adfd28ec94cfe100
- https://docs.kernel.org/core-api/wrappers/memory-barriers.html

## Evidence rules

Each acceptance report should preserve the candidate commit, toolchain
commit, build commands, configuration, image hashes, emulator/hardware
identity, raw serial/stdout/stderr, exit codes and expected test IDs.
Reference and candidate must receive the same workloads and comparable
budgets. Independent test data should not be derived from the candidate's
implementation. Negative and fault cases belong beside positive cases.

A successful boot marker proves that execution reached that point. A
successful host-side allocator test proves that specific allocator contract
in its host context. Neither alone proves Linux ABI compatibility, hardware
driver coverage, HIA target purity, or whole-kernel correctness.

## Licensing and provenance

The pinned Linux `COPYING` describes GPL version 2 only with the
Linux-syscall-note exception, and points to file-specific licensing rules.
Preserve the original SPDX expressions, authorship notices, upstream paths
and revision for any translated or incorporated source. Record original HIA
code separately from translations, and preserve licenses for toolchain
components. The upstream syscall table is explicitly marked
`GPL-2.0 WITH Linux-syscall-note`.

Sources:

- https://github.com/gregkh/linux/blob/7595a62d45ee1a2297eafa5f2ef5d0a45142d84d/COPYING
- https://docs.kernel.org/process/license-rules.html

## Initial disposition

**The empty-repository audit is complete. The complete Linux rewrite is
unimplemented at the audited starting point.** The next concrete milestone
is real HIA memory and page-allocation code with independent host tests and
a QEMU boot through an explicitly temporary boot bridge. All wider Linux
and HIA-purity obligations remain in the ledger until separately evidenced.

