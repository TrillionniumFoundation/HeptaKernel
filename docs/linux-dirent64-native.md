# Native HIA x86-64 directory record

`src/linux_dirent64.hepta` emits one `linux_dirent64` record. It does not
implement the `getdents64` syscall or iterate a directory.

The request is three little-endian 64-bit fields (inode, already-resolved signed
directory offset as bits, and a zero-extended unsigned type/flags value), then
the raw name bytes without the trailing terminator. The distinct output buffer
starts at one record; the third capability is unused. The caller supplies valid
live and disjoint buffers. The returned 32-bit word is either the positive
aligned record length or a signed errno bit pattern: `-EIO` for a name whose
length is outside 1–4095 or whose bytes contain a slash, and `-EINVAL` for
flags wider than 32 bits or insufficient record capacity. All validation
precedes the first output write. Embedded NUL bytes are copied, as in the
pinned Linux formatter, and an additional trailing NUL is written. Record
padding and bytes beyond the record are left untouched.

The bounded test compiles and executes the freestanding HIA object, verifies
that the linked `.text` equals the emitted machine bytes, and checks all
candidate lengths with short, exact and oversized capacities. The C oracle
compiles the original pinned structure, file-type and limit headers along
with the extracted original name-validator body and record-size expression.
Seven records from a real x86-64 Linux host syscall are an independent layout
cross-check, not a boot of HeptaKernel.

```sh
python3 -I -S -B tests/test_linux_dirent64.py \
  --compiler /path/to/pinned/native-compiler \
  --linux /path/to/pinned/linux-checkout \
  --report /tmp/linux-dirent64.json
```

The fixture does not own file descriptors, advance directory position, resolve
a prior record's offset, handle syscall usercopy/partial faults, or negotiate
signals. Full Linux acceptance remains HOLD.
