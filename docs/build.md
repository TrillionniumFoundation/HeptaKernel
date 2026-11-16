# Build and verify the HIA kernel foundation

HeptaKernel currently builds a native HIA physical-frame allocator and executes
that same object in an x86-64 boot fixture. Its functional kernel source is
`src/kernel.hepta`. The temporary architecture bridge is
`arch/x86_64/boot.S`, written in GNU assembly. The bridge and the remaining Linux
subsystems still need HIA implementations before the full rewrite can close.

## Pinned inputs

The machine-readable lock is `compatibility/hia-toolchain-lock.json`.

| Input | Identity |
| --- | --- |
| HIA repository | `TrillionniumFoundation/Hepta` |
| HIA commit | `f33d8da316de8fdf27b504371f1a5310997ff548` |
| Compiler source | `examples/hia_bootstrap/selfhost.hepta` |
| Compiler source SHA-256 | `388b182e42675f11435867dd99520e9452a4ff48e23c0766a3952b662acc7627` |
| B1, B2 and B3 machine-image SHA-256 | `bfd603dd2b40974d2083b567b4295fb3975938da8435dd636514fc197c485de0` |
| Standalone compiler SHA-256 | `87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54` |
| Standalone compiler size | 673,903 bytes |
| Kernel source profile | `hia-asm.v1 hepta.hia.program.v8 selfhost_elf` |
| Kernel object target | ELF64, x86-64, SysV ABI |

The Makefile verifies the compiler digest before compiling the allocator or a
negative-control kernel. The HIA object must have no undefined symbols. The
allocator uses borrowed byte buffers and integer instructions, so its native
execution does not import libc, invoke Linux syscalls, or require a language
interpreter.

## Host requirements

The tested build host is Linux x86-64 with Python 3.12, GNU make, a C compiler
driver with GNU assembler, GNU binutils, Git, and QEMU's x86 system emulator.
On Ubuntu 24.04 the build dependencies can be installed with:

```sh
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  build-essential binutils git python3 qemu-system-x86
```

The C compiler driver is used to assemble the explicit `.S` architecture
bridge. It does not translate the HIA allocator into C. Python is used for the
external B0 toolchain bootstrap, packing test data, and independent test
orchestration. No Python process executes inside the booted guest.

## Reproduce the native compiler from source

Fetch a clean checkout of the locked commit. The cone sparse checkout includes
root files such as `pyproject.toml`, which upstream uses as a source-root marker.

```sh
git init .toolchain/hepta
git -C .toolchain/hepta remote add origin \
  https://github.com/TrillionniumFoundation/Hepta.git
git -C .toolchain/hepta sparse-checkout init --cone
git -C .toolchain/hepta sparse-checkout set \
  hepta tools examples/hia_bootstrap docs
git -C .toolchain/hepta fetch --depth=1 origin \
  f33d8da316de8fdf27b504371f1a5310997ff548
git -C .toolchain/hepta checkout --detach FETCH_HEAD
python3 -I -S -B tools/bootstrap_hia.py \
  --root .toolchain/hepta --output .toolchain/compiler
```

The bootstrap checks the exact checkout, its clean status, and the compiler
source hash. It performs the following sequence:

1. Upstream `build_seed` assembles, verifies and directly encodes the HIA
   compiler to B0 using Python and GNU ld. This is the initial external trust
   boundary.
2. B0 executes the HIA compiler source to produce B1. B1 produces B2, and B2
   produces B3. Every generation must match the locked machine-image digest.
   The upstream Python child transports the fixed ABI buffers and records
   results; the preceding HIA machine code performs each compilation.
3. B3 compiles that source with the upstream `selfhost_exec` output header to
   obtain a standalone compiler. Its complete executable bytes must match the
   locked compiler digest.
4. The standalone compiler rebuilds itself, and that rebuilt executable
   rebuilds itself again. Both run with an environment consisting only of
   `PATH=''`. Both outputs must be byte-identical to the locked compiler.
5. Source identity and the final compiler are read back before the bootstrap
   report is marked PASS.

The output directory must be new; retries use another directory so a failed
attempt's evidence remains available. Reports and each native generation are
written there. The final build tool is
`.toolchain/compiler/native-compiler`. The initial bootstrap and finite
self-reproduction checks do not constitute a proof of compiler correctness or
the upstream project's complete cold-qualification campaign.

An already available compiler with the exact locked digest can be supplied
without repeating the bootstrap:

```sh
make HEPTA_COMPILER=/absolute/path/to/native-compiler
make test HEPTA_COMPILER=/absolute/path/to/native-compiler
```

## Build outputs

After the source bootstrap:

```sh
make HEPTA_COMPILER="$PWD/.toolchain/compiler/native-compiler"
make test HEPTA_COMPILER="$PWD/.toolchain/compiler/native-compiler"
```

The native compiler consumes `src/kernel.hepta` on stdin and writes
`build/kernel.o` on stdout. HIA itself emits its machine instructions and ELF
object; no source generator is needed to edit or compile the allocator.

GNU ld links the HIA object with the assembly bridge and the explicit linker
script to produce `build/kernel.elf`. A final `objcopy -O elf32-i386` gives the
QEMU Multiboot loader an ELF32 container, `build/kernel-multiboot.elf`; it does
not recompile the x86-64 HIA instruction bytes. The bridge begins in 32-bit
protected mode and switches to long mode before calling the HIA entry.

| File | Purpose |
| --- | --- |
| `build/kernel.o` | Directly generated HIA ELF64 object; entry symbol `f0` |
| `build/kernel-host.so` | Host test container for the same HIA `.text` bytes |
| `build/kernel.elf` | HIA object plus the temporary architecture bridge |
| `build/kernel-multiboot.elf` | QEMU-loadable Multiboot boot image |
| `build/native-report.json` | Native differential-test results and source/object hashes |
| `build/boot-report.json` | VM commands, image hashes, serial output and exit observations |
| `.toolchain/compiler/bootstrap-report.json` | Compiler source, generation and self-reproduction evidence |

`make clean` removes generated files under `build/`. The external source and
compiler remain under `.toolchain/` and are not part of the repository source.

## Native functional acceptance

```sh
make test-native HEPTA_COMPILER="$PWD/.toolchain/compiler/native-compiler"
```

The hosted test first checks that the loaded shared object's complete `.text`
section exactly matches the emitted HIA object's `.text`. It then calls the
real HIA entry with independently guarded buffers. A separate set-based model
predicts allocation, release and free counts after every operation.

Coverage includes exact metadata capacities, non-byte-aligned bitmap tails,
reserved prefixes, exhaustion and reuse, actual physical alignment, integer and
address boundaries, malformed requests, short buffers, header corruption, and
32 reproducible randomized traces of 250 operations each. The maximum 65,536
page arena uses exactly 8,256 bytes of metadata. The retained native report
states the actual total call count.

The external ABI remains a trusted-call boundary: the caller supplies valid,
disjoint live request, reply and state regions. The allocator is single-owner;
it does not implement locking, atomic operations or concurrent allocation.
Metadata is trusted kernel memory. Header invariants and encountered
contradictions are checked, but arbitrary metadata tampering is not covered by
a complete bitmap/popcount validation on each call.

## Separately validated HIA E820 RAM-region admission

```sh
make test-memory-map HEPTA_COMPILER="$PWD/.toolchain/compiler/native-compiler"
```

The freestanding HIA object `build/e820-region.o` accepts a canonicalized
E820-style firmware map supplied by a trusted caller, evaluates whether one
proposed arena is wholly contained in enabled type-1 RAM, and refuses overlap
with any enabled non-RAM region. It does **not** read a real firmware handoff
and is **not yet linked into the QEMU boot**. The native test makes 3,033
checks against an independently implemented model, binds the shared library
`.text` to the HIA object, checks that buffers are not corrupted, and executes
an intentionally unsafe always-allow HIA negative control. The pinned Core
verifier checks both HIA sources independently. The scope and limitations are
in [e820-region.md](e820-region.md).

## Bare-metal execution acceptance

```sh
make test-boot HEPTA_COMPILER="$PWD/.toolchain/compiler/native-compiler"
```

The guest bridge validates the Multiboot handoff, establishes its stack and
supervisor page tables, enters long mode, installs exception handlers, and
calls the separately compiled HIA object. It checks the allocator's replies,
metadata and guarded memory, and touches the allocated physical frames in the
guest. `tests/boot-cases.json` is an explicit external table of expected results;
it is not consumed by the HIA allocator as an oracle.

Two positive runs use QEMU TCG: the `pc` machine with 32 MiB and the `q35`
machine with 64 MiB. Each must produce exactly one
`HEPTAKERNEL HIA PMM PASS` marker and the success debug-exit status.

Two negative runs replace the HIA implementation with intentionally broken
kernels. An always-success stub must fail the independent observer. An actual
out-of-bounds HIA operation must reach the guest's diagnostic fault path. The
negative tests require `HEPTAKERNEL BOOT FAIL` and the explicit failure
exit status; a timeout, emulator crash, or silent triple fault is not a pass.

These are single-CPU execution fixtures with asynchronous interrupts disabled.
There is no userspace, process scheduler, syscall implementation, production
virtual-memory policy, filesystem, network stack, or general device ecosystem
in this image. QEMU observations do not establish hardware qualification or
Linux compatibility.

## CI and the full acceptance target

`.github/workflows/verify.yml` performs the pinned source checkout and bootstrap,
builds the real object and boot image, runs native tests and the two positive
and two negative VM cases, then retains reports and images as an Actions
artifact. The workflow's name, **HIA kernel foundation**, describes its scope.
A green run means these component checks passed.

The full Linux rewrite remains a separate acceptance target:

```sh
make full-acceptance
```

That target must remain failing while its tracked obligations are open. It
cannot be inferred from the foundation workflow, native test count, HIA source
extension, or a successful boot marker. The current architecture bridge is
still GNU assembly, and the pinned HIA language does not yet expose the
privileged CPU, port-I/O, interrupt, MMIO, and atomic operations needed to
replace it.
