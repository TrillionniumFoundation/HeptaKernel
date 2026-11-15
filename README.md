# HeptaKernel

HeptaKernel is a HIA implementation project targeting the complete Linux kernel
interface and platform scope at the pinned Linux 7.3.4 baseline. The repository
started empty on 2026-11-15.

The current executable milestone is a **real HIA physical-frame allocator running
in a freestanding x86-64 QEMU guest**. The same HIA object is tested through its
native ABI against an independent model. Full Linux compatibility and a completely
HIA kernel remain unfinished.

## Implemented

- `src/kernel.hepta`: typed HIA Core v8 source, compiled directly to x86-64 by the
  pinned native HIA compiler. It implements initialization, physically aligned
  frame allocation, release, free-count queries, reserved-prefix protection and
  explicit failure results. There is no C allocator or hosted fallback.
- `arch/x86_64/boot.S`: an explicitly **non-HIA** Multiboot/long-mode bootstrap and
  independent boot-test observer. It provides page tables, a stack, exception
  failure handlers and serial output while HIA lacks those target primitives.
- Independent tests: set-model traces, exact bounds and read-only guard pages,
  two QEMU machine configurations, actual physical-page readback, and broken-HIA
  negative controls.
- A fixed upstream source/ABI ledger and a full-acceptance command that continues
  to report `HOLD` while any required implementation or evidence is missing.

## Build and verify

Requirements: Linux x86-64 host, the pinned native HIA compiler, GNU binutils,
GNU make, Python 3 for host test orchestration, and QEMU system x86.

```sh
make HEPTA_COMPILER=/absolute/path/to/hia-native-compiler
make test HEPTA_COMPILER=/absolute/path/to/hia-native-compiler
make full-acceptance
```

The last command currently exits with status 2 (`HOLD`). It is a separate
whole-project requirement, not the success status of the component tests.
The source-bootstrap recipe and CI are in [docs/build.md](docs/build.md).

## Evidence and boundaries

The initial native campaign passed 9,895 allocator ABI calls, including 32 fixed
random traces, plus a separate guard-page campaign. Two QEMU configurations
passed the boot fixture; an always-success stub and an out-of-bounds HIA program
both entered the explicit guest failure path. Source/object/image hashes and
the exact observed commands are retained in [validation/](validation/).

This implementation is single-owner and single-CPU. It manages one explicitly
supplied arena with a permanently reserved prefix. It does not yet discover the
machine's complete memory map, implement Linux's memory subsystem, run user
processes, expose Linux syscalls, or supply SMP, filesystems, networking or a
driver stack. The assembly bridge remains part of the unfinished HIA work.

- [Initial audit and full target](docs/initial-audit.md)
- [Allocator ABI and invariants](docs/allocator.md)
- [Build and test instructions](docs/build.md)
- [Full compatibility ledger](compatibility/coverage.json)
- [Ordered implementation backlog](docs/next-steps.md)

Kernel implementation authored here uses GPL-2.0-only. Reference files under
`third_party/linux/` retain their upstream notices; see [NOTICE](NOTICE).
