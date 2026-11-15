# Retained evidence

These reports record the first implemented HIA allocator foundation. They do
not close the full Linux rewrite. All positive execution reports refer to the
same HIA source and native object; `build-report.json` records their hashes and
proves that the exact HIA code is present at the invoked `f0` symbol in both
boot containers. CI regenerates evidence under its own exact Git commit.

| Report | Observation |
| --- | --- |
| `initial-repository.json` | Empty-repository GitHub observation before the first commit |
| `toolchain-audit.json` | Pinned HIA source/ABI audit, compiler reproduction and rejected unsupported operations |
| `bootstrap-report.json` | Fresh B0, B1/B2/B3 fixed point and two standalone empty-PATH compiler rebuilds |
| `native-report.json` | 9,895 actual allocator calls against the independent set model |
| `guard-pages-report.json` | 61 calls with exact buffers, inaccessible boundaries and read-only input pages |
| `boot-report.json` | PC/32 MiB and Q35/64 MiB boot, plus always-success and bounds-trap negative HIA kernels |
| `build-report.json` | Actual source, native compiler, object, linked library and boot-code identity checks |
| `closure-report.json` | Full Linux target remains HOLD, with pending gates and non-HIA target code |
| `attempt-history.json` | Incomplete initial QEMU driver attempt and the concrete driver correction |

The initial bootstrap requires upstream Python and GNU ld. The native HIA
compiler builds the kernel directly; Python does not implement its allocator.
The guest receives no host system-call/runtime service. The GNU assembly boot
and observer bridge is explicit target code and remains an open HIA obligation.

The local `candidate_commit` field is null because local execution preceded the
publishing commit. Source and artifact hashes are its binding evidence. Do not
invent a commit identity or relabel these reports as a later candidate. In CI,
`GITHUB_SHA` supplies the exact candidate and the reports are retained as run
artifacts. Compiler fixed points, finite tests and successful boot do not prove
general compiler correctness, Linux compatibility or absolute kernel safety.
