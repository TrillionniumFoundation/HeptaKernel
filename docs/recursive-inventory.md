# Pinned Linux recursive source inventory exporter

Use host-only `tools/pinned_inventory.py` against a **local Git object database** containing the exact pinned Linux 7.3.4 commit `7595a62d45ee1a2297eafa5f2ef5d0a45142d84d`. It does not fetch over the network, use HEAD, or accept alternate production commits. Example:

```sh
python3 tools/pinned_inventory.py --linux-git /path/to/linux --output /new/evidence-directory
```

It traverses all paths with `git ls-tree -rtz --full-tree` (not GitHub's potentially truncated recursive tree endpoint), checks the exact commit and root tree, and writes deterministically compressed lossless path/mode/type/object identities, all source Kconfig declarations, and discovered tracked UAPI header paths. Output contains the raw Git tree wire SHA-256, counts, per-file hashes and the complete Git root tree SHA. Non-UTF8 path identity is preserved as hex. Output directory must not already exist.

`make test-inventory` runs an isolated synthetic Git tree with nested directories, Kconfig declarations, UAPI headers, a tab-containing filename, reproducible bytes and wrong-commit rejection. It does **not** claim to have run the entire Linux inventory: run the exporter on the real pinned Git tree and independently replay artifacts before changing inventory evidence.

Hardware/driver IDs, evaluated Kconfig variants, generated UAPI, syscalls on every architecture, all compile-time options and behavioral Linux compatibility remain **open**. The exported raw inventory is necessary groundwork, not a completed Linux/HIA rewrite or a green full-acceptance gate.