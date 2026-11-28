# Native HIA regular-file write-limit planner

`src/vfs_write_limits.hepta` implements the decision and count update of
Linux 7.3.4's
[`generic_write_check_limits`](https://github.com/gregkh/linux/blob/7595a62d45ee1a2297eafa5f2ef5d0a45142d84d/fs/read_write.c).
Linux source commit: `7595a62d45ee1a2297eafa5f2ef5d0a45142d84d`; file
Git blob: `ccaaa454dce0240a38c1cb0fa88896dd347b541f`.

The caller supplies a resolved nonnegative write position, nonnegative
requested count, current file size limit, superblock maximum file size, and
a normalized `O_LARGEFILE` presence bit. It supplies separate live request,
reply and unused capabilities for the native SysV x86-64 `f0` symbol.
The planner has no other inputs or effects.

The request is exactly five little-endian u64 words, in the order above.
All scalar values except the flag and infinity sentinel must fit in nonnegative
signed 64 bits. The `RLIM_INFINITY` sentinel is all one bits; the flag is
0 or 1. A reply capability of at least 24 bytes receives three little-endian
u64 words: status, count as observed after the decision, and a signal-needed
bit. The return is the status as u32. Only the first 24 reply bytes are written.

- Status 0 permits at most the returned count.
- Status 27 corresponds to Linux `-EFBIG`. A finite limit at or before the
  position sets the signal-needed bit (the Linux helper would request
  `SIGXFSZ`). That check precedes the filesystem/legacy limit, including
  on a direct zero-count helper call. Otherwise the finite limit clips
  the count first. Without `O_LARGEFILE`, the helper replaces the
  superblock maximum with `MAX_NON_LFS = 2^31-1`, not the minimum of the
  two. The later filesystem/legacy refusal does not request a signal and
  retains any earlier count clip. Count on error is diagnostic only.
- Status 1 means a short reply and writes nothing. Status 2 means a
  malformed request and writes status with zero count and no signal.

The test extracts the original C helper from the exact locked file for an
independent compiled oracle. Its shims supply only the scalar file fields,
`rlimit` and an observing (non-delivering) `send_sig`. The tested constants
are from the pinned `include/linux/fs.h` and the asm-generic fcntl,
resource, signal and errno-base UAPI headers. The native product links
only the actual HIA object; the C oracle is loaded separately by the
test runner. The runner verifies both compiler and Linux source SHA-256,
identical empty-PATH compilation and exact linked .text equality.

```sh
git -C /path/to/linux show 7595a62d45ee1a2297eafa5f2ef5d0a45142d84d:fs/read_write.c > /tmp/hk-read_write.c
python3 tests/test_vfs_write_limits.py --compiler /path/to/native-compiler --linux-source /tmp/hk-read_write.c
```

This is not a write syscall, file-open policy, inode lookup, append/prewrite
resolution, swapfile/NOWAIT check, write implementation, or signal delivery.
The caller must provide a coherent trusted snapshot; the helper does not
read a live VFS, control task credentials or implement time-of-check
synchronization. No Linux ABI row or full-acceptance gate is credited.
