# Pinned Linux Kbuild/Makefile source obligations

This is an independent, lossless source-byte inventory for Kbuild and
Makefile files in fixed Linux 7.3.4 Git commit
7595a62d45ee1a2297eafa5f2ef5d0a45142d84d. It is not a Kbuild
execution engine, a dependency solver or evidence that any driver works.

Run the adversarial test and exact pinned-tree extraction:

    python3 -I -B tests/test_linux_kbuild_statements.py
    python3 -I -B tools/linux_kbuild_statements.py \
      --repo /path/to/pinned/linux \
      --lock compatibility/linux-source-lock.json \
      --out build/kbuild-inventory

The source file ledger records every tracked Makefile, Makefile.*,
Kbuild and Kbuild.* leaf, including nonregular symlinks and gitlinks,
with Git object IDs, raw-byte-safe paths and modes. The statement ledger
records every original physical source byte from regular files in order:
comments and blank lines, Make assignments, include directives, rules,
conditionals and unrecognized syntax. Continuation lines are grouped,
but original bytes, line numbers and byte offsets are retained. Limited
assignment LHS/operator/RHS and CONFIG tokens are lexical references only.
No Makefile or untrusted worktree source is executed.

The independent GitHub Actions job reads each original immutable object,
checks every byte span and exact reconstruction, and retains SHA-256-bound
output artifacts. A poisoned worktree, non-UTF8 path, symlink and incorrect
pinned commit are covered by the isolated test. This complements existing
source-path, Kconfig, UAPI, syscall and MODULE_DEVICE_TABLE inventories.

Actual Kbuild conditional evaluation, recursive object linking, generated
sources, architecture-specific compilation, the runtime driver/device
matching map and full Linux behavior remain open. No claim of driver or
kernel implementation follows from an inventory entry. The original 17
acceptance gates and 422 x86-64 syscall source rows must remain HOLD.
