# Offline replay of the pinned Linux inventory and closure checker

This branch combines the exact source-checker files of HeptaKernel #259, #264,
and #266. It records a local offline replay from the complete object pack for
the pinned Linux 7.3.4 commit `7595a62d45ee1a2297eafa5f2ef5d0a45142d84d`;
the tree is `d07c331ebf5acbde9ebf9caea9eac6e33b07ad77`. The source Git object
database was fetched without a working-tree checkout, then replayed with
`GIT_NO_LAZY_FETCH=1`. This is source accounting only. An independent
`git ls-tree -rlz` comparison matched all 96,081 paths and their mode, type,
object ID and size.

- [Inventory](report.json): 1,942 Kconfig paths with 1,935 lexical include edges.
- [Kconfig literal edges](kconfig-literal-targets-report.json): 1,911 tracked
  literal matches and 24 remaining lexical/nonliteral/untracked cases. These
  aren't failures of active Kconfig: test, conditional and generated paths
  can appear, and active-graph evaluation is outside this replay.
- [x86-64 and x32](syscall-x86-dual-report.json): 422 original table rows,
  386 native x86-64 and 375 x32 dispatch obligations.
- [i386 compatibility](syscall-ia32-report.json): 462 source rows.
- [Full acceptance](closure-report.json): still HOLD; no gate is promoted.

Run from the HeptaKernel candidate with `LINUX_OBJECTS` set to the absolute path
of a local Git repository whose HEAD is the pinned Linux commit and whose
original objects are complete. `OUT` must be a fresh destination.

```sh
export GIT_NO_LAZY_FETCH=1 GIT_TERMINAL_PROMPT=0
OUT=build/linux-inventory-replay
make test-closure test-linux-inventory
python3 -I -B tools/linux_inventory.py --repo "$LINUX_OBJECTS" \
  --lock compatibility/linux-source-lock.json --out "$OUT"
python3 -I -B tools/linux_x86_syscall_matrix.py --repo "$LINUX_OBJECTS" \
  --inventory "$OUT" --lock compatibility/linux-source-lock.json \
  --vendor third_party/linux/arch/x86/entry/syscalls/syscall_64.tbl
python3 -I -B tools/linux_x86_ia32_syscall_matrix.py --repo "$LINUX_OBJECTS" \
  --inventory "$OUT" --lock compatibility/linux-source-lock.json
python3 -I -B tools/linux_kconfig_include_targets.py --repo "$LINUX_OBJECTS" \
  --inventory "$OUT" --lock compatibility/linux-source-lock.json
make full-acceptance # expected exit 2 and explicit HOLD
```
