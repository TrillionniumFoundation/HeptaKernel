# Pinned UAPI ioctl macro source-span inventory

`tools/linux_uapi_ioctl_macros.py` enumerates **every immutable Git blob** in
the fixed Linux 7.3.4 source tree satisfying the existing `is_uapi` header-path
predicate. It records each directly written UAPI `#define` whose replacement
text lexically invokes an `_IO`, `_IOR`, `_IOW`, `_IOWR`, `_IOC` or `_BAD`
variant. Continuation lines are retained as a single raw source span, including
line endings, offsets, the original Git blob OID, raw base64 bytes and all
lexical invocation names in source order.

The tool does not run the preprocessor or C compiler. Tokens in comments or
inactive branches are retained as candidates, and valid expressions that
refer indirectly to a helper macro (or define a numeric ioctl constant) may
not appear in this narrowly defined `_IO`-invocation ledger. These omissions
are **explicit open inventory work**, not silently treated as unsupported
Linux interfaces. It makes no attempt to infer ioctl numbers, 32-bit compat
packing or reachable driver handlers. No ABI row is credited as implemented.

## Reproduce

Use the exact Linux commit in `compatibility/linux-source-lock.json`:

```sh
python3 -I -B tests/test_linux_uapi_ioctl_macros.py
python3 -I -B tools/linux_uapi_ioctl_macros.py \
  --repo .upstream/linux \
  --lock compatibility/linux-source-lock.json \
  --out build/linux-inventory
```

The outputs `uapi-ioctl-macro-obligations.jsonl` and
`uapi-ioctl-report.json` retain the full source-span ledger and SHA-256
binding. The independent Inventory CI step verifies each returned raw span
against the **pinned original Git blob** and checks the path/blob OID against
the separately enumerated entire Git tree. The local adversarial fixture
tests CRLF, multiline definitions, an unterminated continuation, non-spliced
backslashes with trailing whitespace, dirty worktree exclusion, a rejected
wrong HEAD and a rejected non-SHA commit lock.

Both `inventory_complete` and `full_rewrite_complete` remain `false`. The
original 422 x86-64 syscall table entries and all 17 whole-Linux acceptance
gates retain their original scope. This source audit is a prerequisite for a
future full ioctl ABI comparison, **not** an implementation of ioctl or a
kernel privilege capability.
