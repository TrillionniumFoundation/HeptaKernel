# Native x86-64 stat device fields

The native HIA entry stages only `st_dev` and `st_rdev` in a caller-owned,
already allocated x86-64 Linux LP64 stat record. It preserves every other
byte; the caller must separately initialize all other fields and padding.
No kernel syscall, VFS lookup, user-pointer check, atomic publication,
copy-to-user, x32 or 32-bit compat behavior is implemented here.

The record format is pinned to Linux
[arch/x86 stat UAPI](https://github.com/torvalds/linux/blob/7595a62d45ee1a2297eafa5f2ef5d0a45142d84d/arch/x86/include/uapi/asm/stat.h).
Linux [cp_new_stat](https://github.com/torvalds/linux/blob/7595a62d45ee1a2297eafa5f2ef5d0a45142d84d/fs/stat.c)
uses the modern device encoder for both fields. In the scoped stat record,
they are eight-byte unsigned little-endian words at offsets 0 and 40, with
the upper halves zero. Neither statx nor the obsolete stat record uses this
contract.

The input consists of two little-endian u64 words carrying canonical internal
u32 device IDs. The exact 16-byte request and exactly 144-byte destination
are disjoint live regions; the third HIA ABI descriptor is unused. The entry
returns 1 for either invalid length and 2 if either input is wider than u32,
without writing any destination byte. Both codec calls finish before the
first store. With admitted inputs, it returns 0 and changes only the two
specified fields. This is no-write-on-refusal under the stated buffer contract,
not atomic concurrent update or fault rollback.

The checker concatenates the staging source with the actual
[`linux_devnum` body](../src/linux_devnum.hepta), removing only that module's
standalone header and public export directive. No codec is translated or
duplicated: the pinned compiler emits one native object, with direct HIA
calls from the staging entry to the same codec body. Standalone
`linux_devnum` is unchanged and independently retested. The test binds
eight actual upstream header blobs, asserts layout and widths in C, and
compares the entire record and canaries against the C oracle after each call.
The rejected cases verify unchanged buffers, and a separately compiled wrong
offset control is detected. The run also covers unaligned staging pointers.

```sh
python3 -I -B tests/test_x86_stat_dev_fields.py \
  --compiler .toolchain/compiler/native-compiler \
  --linux-root /path/to/locked/linux \
  --report x86-stat-dev-fields.json \
  --composed x86-stat-dev-fields-composed.hepta
```

The [local execution receipt](../validation/x86-stat-dev-fields.json) records
component and composed-object identities and exact counts. Full Linux remains
HOLD. See [build.md](build.md) for the pinned source bootstrap.
