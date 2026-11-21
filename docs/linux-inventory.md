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

## Pinned UAPI C tag lexical coverage (additional source inventory)

The separate `tools/linux_uapi_tags.py` inventories every lexical
`struct`, `union`, and `enum` tag mention from tracked regular UAPI header
Git blobs at the exact Linux commit. It records the source blob SHA-1, raw-byte
path, token byte position, line, optional tag name and local lexical class.
C comments and quoted literals are excluded; inactive conditional branches
and macro bodies remain visible. A malformed/unterminated lexical token aborts
rather than silently declaring the file complete. Independent synthetic-Git
tests check literal source offsets, forged worktree modification, disjoint
source scopes and wrong-HEAD refusal. CI retains the source manifest and
its SHA-256 report alongside the existing recursive source inventory.

This is a **source-level obligation discovery tool**, not a C-preprocessed
UAPI export list, type-layout resolver, ioctl ABI conformance test, or HIA
kernel implementation. It does not reduce any of the 422 x86-64 syscall rows
or the 17 full-acceptance gates.


### Phase-2 source splicing and provenance

The separate UAPI lexical tag index now performs LF/CRLF
backslash-newline splicing **before** removing C comments and literals.
This prevents a continued `//` comment from generating false type tags
and preserves tags or names whose identifiers cross a physical line break.
Every `byte_at` and `name_byte_at` still addresses the **original Git
blob**, not a normalized copy. The additional `raw_span` and
`name_raw_span` delimit the physical byte interval; removing the original
splice sequences reconstructs the logical token. Original physical source
line numbers are retained. The report format is
`heptakernel.linux-uapi-tag-lexical.v2` and old artifacts remain immutable.

This is still a lexical approximation, not translation-phase completeness:
C trigraph translation, macros, conditional activation, declaration
semantics, type layout and ABI export resolution are outside this
inventory. The pinned baseline and all Linux acceptance gates remain HOLD.


## Immutable Kconfig property-line candidate ledger

The separate \`tools/linux_kconfig_relations.py\` records every lexical
\`depends on\`, \`visible if\`, \`select\`, \`imply\`, \`default\`,
\`range\`, \`prompt\`, \`def_bool\`, and \`def_tristate\` line across the
pinned Linux Git tree's tracked Kconfig files. Each record binds an immutable
Git blob ID and raw-byte-safe path to the physical source line, byte offsets,
exact original bytes and an unevaluated operand. Git symlinks are counted as
unreadable rather than followed; the worktree can be modified without changing
the immutable-object output. Its JSONL and SHA-256 report are retained in CI.

This is **only a lexical source obligation ledger**, not a Kconfig parser,
dependency graph, reachable build configuration, or HIA implementation. In
particular, help text can contain a matching line, line continuations are not
resolved, source/include variables are not expanded, and inactive branches are
not evaluated. CI independently replays all candidate source rows from pinned
Git blobs and retains explicit full-Linux HOLD. The 17 full-acceptance gates
and 422 x86-64 syscall rows remain unchanged.

## Kconfig property-to-declaration source candidates (additional audit)

`tools/linux_kconfig_scoped.py` adds a lossless classification layer over the
existing immutable `kconfig-relation-lines.jsonl` source inventory. It retains
**every** property candidate in original Git source order, with the original
path bytes, Git blob OID, exact physical source line and byte offsets. Each
candidate is labeled `SCOPED_LEXICAL_CANDIDATE`,
`HELP_TEXT_LEXICAL_ONLY`, `UNRESOLVED_CONTINUATION`, or
`UNBOUND_LEXICAL_CANDIDATE`. Only the first label carries a tentative
`config`/`menuconfig` owner and its original declaration line; all other
records deliberately have null owner fields.

Owner hints use the physical declaration and greater indentation, explicitly
discard an owner at structural `menu`/`choice`/`if` and include boundaries,
and refuse to attach a property when a preceding physical line ends in a
backslash. Properties in indented `help` bodies are still recorded, but
labeled as lexical-only rather than being silently interpreted as actual
`select` or `depends on` semantics. Raw-byte paths and Git object identity
are preserved even for non-UTF8/newline paths; unsupported symlink targets
are counted, not traversed.

`tests/test_linux_kconfig_scoped.py` covers misleading help text, structural
scope changes, continued lines, mixed indentation, malicious uncommitted
worktree edits and wrong-pinned-HEAD rejection. Both `make test` and the
pinned-source inventory workflow run this test. CI runs the new scanner against
the exact locked Linux source, checks the new source SHA-256, re-reads original
Git blobs independently, and verifies one-for-one preservation of *every*
earlier lexical source row. The result is retained as
`kconfig-property-scopes.jsonl` and
`kconfig-property-scopes-report.json` in the exact-commit Actions artifact.

This is **not** a Kconfig parser, evaluated dependency graph or resolved build
configuration. Mixed whitespace, relative source paths, active conditional
scopes, help grammar, multiline logical statements, variable substitution,
macro expansion, menu visibility and reachability remain unqualified. Even a
candidate owner is not yet proof of Kconfig semantics. It adds no Linux
functionality; all 17 full-acceptance gates, 422 syscall obligations and
`inventory_complete=false` remain unchanged.


## Source-root/relative Kconfig literal include target provenance

`tools/linux_kconfig_include_targets.py` projects **all** previously
recorded `kconfig-source-edges.jsonl` into tracked target-path identities
under the exact locked Linux Git root. Quoted static `source` and `osource`
paths are rooted at srctree; `rsource` and `orsource` are relative to
the containing Kconfig file's directory. Target metadata is read from the
existing raw-byte-safe full-tree source ledger and never from worktree files.
The resolver re-reads original immutable Git Kconfig blobs, verifies source
lines and the parent ledger digests, and refuses changed commit or tree
identities. It retains original row order and fields without omission.

Each edge is classified as a tracked regular literal, tracked nonregular
literal (including symlinks, which are never followed), optional/required
untracked literal, outside-tree path, or unresolved literal syntax or
variable/glob/escape. The files `kconfig-literal-targets.jsonl` and
`kconfig-literal-targets-report.json` are retained in the pinned-source
CI artifact with their SHA-256 and original Git commit/tree provenance.
Adversarial synthetic Git fixtures include forged worktree contents,
wrong HEAD, ledger tampering, root/relative anchoring and symlinks.

This is deliberately a **partial literal target source audit**, not the
evaluated Kconfig include graph. Branch conditions, environment substitution,
optional existence in generated build trees, globs, shell expansion, actual
menu configurations, compilation and driver activation remain unresolved.
Tracked target does not imply an active include; untracked required targets
may be conditional or generated. All 17 full Linux acceptance gates and 422
x86-64 syscall obligations stay unchanged, `inventory_complete=false`,
and `make full-acceptance` must continue to report HOLD.


## Physical-context review of Kconfig include candidates

The immutable literal include target report now also retains a
'source_context' for each original source/rsource/osource/orsource
lexical row. The original one-to-one source-edge ledger, path identities,
target resolution and SHA-256 checks remain intact. Physical context
distinguishes DIRECTIVE_LEXICAL_CANDIDATE, HELP_TEXT_LEXICAL_ONLY,
UNRESOLVED_PHYSICAL_CONTINUATION, and
UNRESOLVED_MIXED_HELP_INDENTATION. A source-looking line inside an
indented Kconfig help or ---help--- body is not counted as an active
include merely because a path happens to exist in the Git tree.

This conservative source-order classifier reads the original immutable
Git blob (not the worktree), tracks help indentation across blank lines,
handles tabs and CRLF, and marks immediate prior backslash continuations.
The pinned inventory CI independently checks aggregate classifications,
previous physical line provenance for continuations, and the existence
of a less-indented help header for help-body classifications. Adversarial
fixtures cover false include lines embedded in help, mixed indentation,
continued directives, and the original Git ledger tampering controls.

These are physical-line review hints rather than a complete Kconfig lexer
or proof of active include reachability. Nested grammar, generated source
roots, environment substitutions, conditions, and source-path semantics
still require evaluation. In particular, the original lexical counts may
include inactive help-body text and test-only source roots; no rows are
removed, and all 17 Linux gates and 422 syscall obligations remain HOLD.


## Explicit x86 root-profile Kconfig include frontier

The separate tools/linux_kconfig_root_closure.py creates a **possible lexical
root traversal** from the tracked Git blob Kconfig, with the caller specifying
SRCARCH=x86 and HEADER_ARCH=x86. It substitutes only these two explicit
identifiers (dollar-name, parenthesized or braced variants); unsupported
variables, shell expansions, globs and malformed paths remain unresolved.
Source/rsource semantics are inherited from the existing immutable literal
resolver, including refusal to follow symlinks or escape the Git tree.

The projection rechecks every original literal edge against the complete
tracked-path ledger before use; no lexical rows are dropped or rewritten.
Only DIRECTIVE_LEXICAL_CANDIDATE rows with a profiled **tracked regular
blob** target can create a traversal link. Help-body, continuation, mixed-
indentation, untracked, nonregular and dynamically unresolved rows remain
in the output with explicit exclusion or frontier status. Breadth-first
search records each first parent's original line, minimum root depth, Git
OID and complete explored/nonexplored lexical rows; cycles terminate
without artificial depth caps. The kconfig-profile-root-edges.jsonl,
kconfig-profile-root-files.jsonl and kconfig-profile-root-report.json files
are SHA-256 bound to their exact literal/source inventories, pinned
commit/tree and selected profile and retained by Inventory CI. Independent
Git tests cover cycles, relative paths, forged ledger identities, wrong
HEAD and worktree poisoning.

Run after the existing pinned Linux inventory and literal target audit:

    python3 -I -B tests/test_linux_kconfig_root_closure.py
    python3 -I -B tools/linux_kconfig_root_closure.py \
      --repo .upstream/linux --inventory build/linux-inventory \
      --srcarch x86 --header-arch x86

**This does not evaluate Kconfig.** The explicit x86 profile is not proof
of the environment selected by the kernel build; reachable conditional
lines may be inactive and unresolved syntax can omit real edges. No
generated build-tree includes, Kconfig expressions, architecture
configurations, driver enablement, ABI implementations or HIA backend
features are inferred. All 17 Linux full-target gates and all 422
x86-64 syscall obligations remain HOLD.

## Architecture-directory Kconfig root profile matrix

The pinned inventory now separately evaluates the existing conservative root
closure under **all 21 exact `arch/` directory labels** from
`compatibility/linux-source-lock.json`. For each profile it substitutes
`SRCARCH=HEADER_ARCH=<directory name>`; this is explicitly **not** a
Kbuild-derived or validated build configuration (for example, x86 personality
aliases and generated environment can differ). No live Kconfig evaluation is
claimed. The same immutable source path and include-line SHA-256 ledgers must
match across all profiles, and the existing independently checked x86 result
must match the x86 matrix member byte-for-byte.

`kconfig-arch-matrix-memberships.jsonl` binds each potentially reachable
regular Git blob, its source path and shortest traversal witness to its profile.
`kconfig-arch-matrix-union.jsonl` reports per-file profile membership without
losing repeated include paths. `kconfig-arch-matrix-report.json` contains
per-profile edge/file digests, route counts, union/intersection totals, and
explicit unresolved semantics. The independent CI step reconstructs set
memberships from raw rows, compares every OID to the pinned source ledger,
recalculates all counts and hashes, and retains the artifacts. A path not reached
by these *lexical directory profiles* is not declared inactive in real Linux.

This extends architecture-wide source auditing, not implemented HIA kernel
functionality: all 17 full acceptance gates and 422 x86 syscall obligations
remain open, and `make full-acceptance` must still report HOLD.


## Native x86-64 and x32 composite syscall source obligations

tools/linux_x86_syscall_matrix.py derives two source-only dispatch inventories from the original pinned 422-row arch/x86/entry/syscalls/syscall_64.tbl. It cross-checks the complete lossless syscall ledger, original immutable Git blob, SHA-256 digests, and vendored snapshot, rejecting malformed rows and duplicated numbers rather than dropping them.

Native x86-64 contains **386 source dispatch obligations** (339 common plus 47 64-only); x32 contains **375 source dispatch obligations** (the same 339 common rows plus 36 x32-special rows numbered 512–547). x32 dispatch numbers retain the high ABI bit 0x40000000. These 761 projected rows are **not** 761 distinct syscalls, nor completed syscall implementations; they retain all original 422 source rows and file/line/blob identity. Missing declared handlers and noreturn annotations are retained explicitly. The generated syscall-x86-native-obligations.jsonl and syscall-x32-obligations.jsonl files and syscall-x86-dual-report.json bind exact-source SHA-256 outputs.

Inventory CI independently reconstructs both dispatch tables directly from pinned Git source bytes and checks all rows, counts and negative fixtures. This does not establish x32 compat argument layouts, Kconfig activation, syscall trampolines, errno behavior or HIA kernel handlers. All 17 Linux gates remain HOLD; the 422 original syscall source obligations are unchanged.

The immutable upstream Git syscall table ends in one LF, while the existing vendored copy ends in two: exactly one additional final LF. The importer uses the upstream bytes as authoritative and independently records/validates this exact vendor-only difference and both SHA-256 digests; no input rows are removed.
