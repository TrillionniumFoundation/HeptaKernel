# Conservative Kbuild object-activation candidates

This additional scanner is a **partial line-level resolver**, not a make
interpreter, configuration closure, recursive object graph, driver implementation
or Linux acceptance claim. It is derived from immutable Git blobs at locked
Linux commit `7595a62d45ee1a2297eafa5f2ef5d0a45142d84d`.

Run with an explicit, **not inferred** profile:

```sh
python3 -I -B tests/test_linux_kbuild_object_activation.py
python3 -I -B tools/linux_kbuild_object_activation.py \
  --repo /path/to/pinned/linux \
  --lock compatibility/linux-source-lock.json \
  --profile /path/to/explicit-profile.json \
  --out build/kbuild-object-activation
```

A profile is JSON `{"schema":"heptakernel.kbuild-explicit-profile.v1","values":{"CONFIG_X":"y"}}`.
Only explicitly supplied `CONFIG_` tristates are considered known. The CI
uses an empty profile: it does **not** guess which Linux config is active.

The scanner recognizes literal `obj-y`, `obj-m`, `obj-n` and
`obj-$(CONFIG_FOO)` assignment LHS and their literal `.o`/directory tokens.
Only a strict subset of `ifeq`/`ifneq` with an explicitly known tristate is
evaluated. Unknown selectors, unsupported guards, dynamic tokens, `define`,
recipes, and includes are never silently accepted. Original Git object ID,
source byte spans, line number, original raw-byte SHA-256, assignment operator
and object token are retained. The independent fixture compares supported
branch conditions against GNU Make using y/m/n profiles, retains undecidable
rows, and checks hostile worktree mutation, wrong commit, invalid config,
non-UTF8 paths and symlink non-dereferencing.

`ACTIVE_LEXICAL_LITERAL` means the **assignment line**, in this limited syntax,
would be reached. It does **not** mean the object survives subsequent Make
variable reassignments, becomes linked, is enabled by a valid Kconfig profile,
or actually executes. Even a simple `obj-y += x.o` may be overwritten, omitted
by recursion or affected by an included file. No full build-graph statement
is emitted and unresolved paths are preserved. Read the complete lossless
source ledger from `tools/linux_kbuild_statements.py` alongside this derivative.

Full Linux architecture, driver, kernel and ABI work remains open: 17 gates
HOLD and 422 original x86-64 syscall rows not credited.

## Three-valued chained `else ifeq` and `else ifneq`

The first-match arm logic is now evaluated without treating GNU Make's chained
`else ifeq` / `else ifneq` as a separate nested conditional. An explicit
profile can activate exactly one known arm; a later arm is inactive if any
earlier arm is known to match. If an earlier guard is undecidable, subsequent
arms are never promoted to active merely because their own guard is true.
An unsupported `else ifdef` / `else ifndef` remains unknown; malformed
and repeated final `else` structures taint the complete file's activation
claims, including earlier candidate lines.

`tests/test_linux_kbuild_elseif.py` independently compares all three known
CONFIG_X profiles with actual GNU Make, tests an unknown earlier condition,
unsupported branch syntax, duplicate `else`, malformed clauses and orphan
`else` rejection. This narrows a subset of undecidable source lines; it still
does not evaluate includes, recursive variables, final Make variable values,
Kconfig validity, link reachability or build any driver.
