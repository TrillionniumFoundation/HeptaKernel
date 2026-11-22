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

## Strict x86-64 numeric source projection (independent of implementation)

`tools/linux_uapi_ioctl_numbers.py` takes only the preceding immutable
`uapi-ioctl-macro-obligations.jsonl` and its hash-bound report. It preserves
**every original lexical macro call**, its defining blob, exact source byte
offset and ordinal; no unmatched source candidate may disappear.

It computes a 32-bit *candidate number* only for `_IO(type,nr)` and
`_IOC(dir,type,nr,size)` with independently parseable literal operands,
using the generic x86-64 layout: direction bits 30–31, size bits 16–29,
type bits 8–15 and number bits 0–7. A one-byte character constant can supply
the type. It refuses out-of-range fields; the parser never evaluates
arbitrary Python or C expressions. A `sizeof`-dependent typed macro,
a `_BAD` spelling, comments, missing parentheses, nonliteral operands,
or unsupported syntax retains an explicit unresolved record.

Output is `uapi-ioctl-x86_64-candidates.jsonl` and
`uapi-ioctl-x86_64-report.json`, both bound to the original source SHA-256,
Linux commit and immutable tree. Independent fixture and CI checks verify
the numeric bit construction, source offsets, field rejection, comment
filtering, negative controls, full row preservation and report identity.
No preprocessor, compiler-generated ioctl value, ABI type layout,
architecture other than x86-64, active configuration, compat conversion,
driver dispatch, or userspace behavior has been verified.

**These values are SOURCE CANDIDATES, not Linux ioctl ABI implementations.**
The complete 17 acceptance gates remain HOLD, as do the 422 original
x86-64 syscall obligations. This projection does not replace real ABI
experiments with unmodified userspace and corresponding handlers.
