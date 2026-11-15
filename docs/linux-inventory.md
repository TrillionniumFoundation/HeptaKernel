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
