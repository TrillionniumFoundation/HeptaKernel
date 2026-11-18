# Pinned recursive Linux tree inventory

This is a **real, byte-preserving audit of the fixed upstream Linux Git tree**.
It is not a kernel implementation, a complete Kconfig dependency solver,
or an architecture/ABI/driver-compatibility qualification. The full-rewrite
manifest remains unchanged, with `inventory_complete=false` and all 17
full-acceptance gates still open.

The script requires the actual Git objects of the pinned Linux commit in
`compatibility/linux-source-lock.json`. It **fails closed** if the source
repository's HEAD is not exactly that commit. It does not require an internet
connection once the objects are available. The CI workflow checks out the
exact commit from the stable maintainer mirror and runs the same program.

```sh
python3 -I -B tests/test_linux_inventory.py
python3 -I -B tools/linux_inventory.py \
  --repo /path/to/exact-pinned-linux-checkout \
  --lock compatibility/linux-source-lock.json \
  --out build/linux-inventory
```

## Outputs

- `source-paths.jsonl`: **every recursive tracked leaf**, including regular
  files, executable blobs, symlinks and Gitlinks, in lexicographic raw-byte
  path order. Each record includes original path bytes encoded as Base64,
  a readable UTF-8 path when valid, mode, Git object ID, type and blob size.
  Neither unusual filenames nor nested directories are dropped. Gitlinks are
  recorded as opaque links, not mistaken for source already imported.
- `kconfig-declarations.jsonl`: lexical `config` and `menuconfig`
  declarations from the **exact immutable tracked blobs**, with file identity
  and original source line. The script does not infer dependencies, expand
  `source` directives or prove that an option is reachable.
- `report.json`: pinned commit/tree identities, independent SHA-256 digests
  of both output files, counts and explicit limitations. It is written last.

The parser uses NUL-delimited `git ls-tree -r -z -l`, never a newline- or
whitespace-delimited listing. The self-test uses paths containing newlines,
backslashes, invalid UTF-8, symlinks, a Gitlink, uncommitted source poisoning
and a deliberately incorrect commit lock. A separate CI step compares the
complete reconstructed path set against a second `git ls-tree` invocation.
A source object missing from the Git repository is a hard error.

For further work, extract and verify every Kconfig dependency graph, per-arch
syscall number and UAPI layout, device IDs and driver activation conditions.
Then map the resulting obligations to actual HIA implementations and
independent behavioral tests. No counts in this report represent Linux
implementation coverage, and none should change
`compatibility/coverage.json` status without corresponding evidence.

The inventory artifact is retained by GitHub Actions, rather than committing
tens of thousands of upstream identifiers into the HeptaKernel development
history. An artifact is only evidence for the exact baseline and candidate
referenced by its workflow run.

## Directory Git objects and UAPI subindex

The pinned Linux source audit now records every recursive directory's Git
tree OID in `directory-objects.jsonl`, preserving raw-byte names; the root
tree OID remains in the report. The `uapi-paths.jsonl` artifact projects
tracked architecture and common UAPI source entries from the complete source
path ledger, with original object modes, OIDs and sizes. Each new artifact
has its own SHA-256 in the same exact-candidate report. The existing full
Git-tree CI now independently compares all directory paths and object IDs
with a second `git ls-tree -r -t -z` traversal, and checks that the UAPI
projection is exactly present in the source ledger.

Generated headers, dependency resolution, device ID coverage and ABI
semantics are **not** established by these source indexes. The earlier
experimental duplicate Python inventory was removed so this remains the
single canonical inventory implementation and workflow.

## Lexical Kconfig source edges

`kconfig-source-edges.jsonl` now records each `source`, `rsource`, `osource`
and `orsource` directive encountered in every tracked Kconfig blob. Each row
binds its original path, exact blob OID, source line, directive kind and
Base64-encoded raw operand. The corresponding SHA-256 and per-kind counts
are bound into `report.json` and verified by the independent GitHub Actions
inventory job. The adversarial fixture covers all four directives, quoted
variable operands, indentation, a literal `#` inside a quoted path, and
commented-out directives. Uncommitted worktree modifications do not affect
the ledger.

This is **not** expanded include resolution or a Kconfig dependency graph:
variables, relative-path semantics, optional includes and conditionals still
require an exact environment-sensitive parser. The full inventory and 17
Linux rewrite gates remain open.

## Lossless syscall-table source rows

The pinned-source inventory now emits `syscall-table-rows.jsonl`, one
record per nonblank, noncomment active line of every tracked
`scripts/syscall.tbl` or `*/syscalls/*.tbl` blob. Each binds the exact
Git object ID, raw-byte path, original line number and source bytes, lexical
columns, and an explicit `LEXICAL_ROW` or `UNPARSED` status. Unexpected
active formats remain visible instead of disappearing. A separate CI oracle
reads the original immutable Git objects and checks identity, completeness,
order and SHA-256, including an adversarial intentionally unparsed fixture.

This is an **upstream declaration inventory**, not syscall implementation or
behavioral qualification. It does not establish unique numbers across ABI
personalities, kernel dispatch, errno, compatible layouts or userspace
correctness. All 422 x86-64 syscall obligations and 17 full-acceptance gates
remain open, and `make full-acceptance` must remain HOLD.

## Immutable UAPI macro declaration rows

The pinned-source inventory now also emits `uapi-macro-rows.jsonl`.
For each tracked regular `.h` file beneath common or architecture-specific
UAPI directories, every lexical `#define` source line records its original
byte sequence, line number, macro name, raw-byte path and immutable Git blob
OID. The inventory reports the count of nonregular/unreadable UAPI headers
instead of silently resolving symlinks or dropping them. The artifact has a
separate SHA-256 in the exact-candidate report, and CI independently re-reads
all corresponding Git blobs to verify completeness, source order and bytes.

This is a **lexical declaration inventory**, not the set of exported ABI
constants after preprocessing. Definitions under inactive `#if` branches
are intentionally retained. Replacement-list continuations, macro expansion,
C type/layout compatibility, generated headers and arch-dependent expression
semantics remain unresolved. Existing syscall obligations, every full Linux
acceptance gate, and `inventory_complete=false` remain unchanged.

## Pinned module device-table source references

`module-device-table-mentions.jsonl` extends the immutable Git-object inventory
to same-line `MODULE_DEVICE_TABLE(...)` references in tracked C, header and
Rust text files, with raw-byte-safe paths, exact blob IDs, source lines, macro
argument tokens when parseable, and explicit `UNPARSED` entries. The
`report.json` SHA-256 and counts bind the new rows; the upstream CI independently
locates candidate files and reconstructs each match from immutable blobs.
Fixture tests retain comments and reject a malformed argument list without
dropping the line. Newline/invalid-UTF8 paths remain protected by NUL-delimited
Git output.

These are **lexical references, not actual resolved device IDs**. Inactive
preprocessor branches, comments and macro definitions can match; multiline
invocations and binary source files are not included. Resolving PCI/USB/ACPI/OF
identifier values, generated aliases, Kconfig activation and device-driver
behavior remains open. This addition neither changes `inventory_complete=false`
nor closes any of the 17 Linux gates or 422 x86-64 syscall obligations.


## Position-bound multiline device-table invocations

The second output, **module-device-table-invocations.jsonl**, closes the
same-line-only discovery gap in the earlier device-table index without
reinterpreting or erasing its 10,106 baseline lexical rows. Every matching
C/H/Rust source blob at the fixed Linux commit is searched for
MODULE_DEVICE_TABLE followed by zero or more spaces, tabs or physical
newlines and an opening parenthesis. Each retained record carries the
original Git blob OID, raw-byte path, absolute start/end byte offsets
(end exclusive), first/last physical source lines, exact source bytes
(Base64), and parsed bus/table identifiers only where both arguments
are plain identifiers.

Calls with line-separated arguments are included. Incomplete or compound
argument lists are explicitly UNPARSED; spans without a closing parenthesis
in the next 4096 bytes are TRUNCATED, not silently discarded. Comments,
preprocessor definitions and disabled branches are still lexical records,
not evidence that the call is active. The bounded lexer does **not** expand
macros, resolve includes or conditionals, interpret comments, prove C syntax,
or infer PCI/USB/ACPI/OF IDs; nonwhitespace between the macro name and
parenthesis and binary files are outside this lexer. Even a fully parsed token
pair is only a reference, not an implemented or qualified driver.

The new artifact, total/multiline/unparsed counts and SHA-256 are bound to
the pinned source tree in report.json. CI independently reconstructs
all byte spans from the immutable original Git blobs using a separate
byte-scanning oracle, and a distinct fixture covers multiline, malformed,
truncated, commented and invalid-UTF8/newline-path cases. The original
same-line artifact is retained for comparability and tested unchanged.
This is a source inventory improvement only: all 17 Linux acceptance gates,
422 syscall obligations, and inventory_complete=false remain open.
