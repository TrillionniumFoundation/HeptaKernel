# Native bounded clocksource delta conversion

This HIA leaf converts **caller-supplied** cycle samples into elapsed whole
nanoseconds with an exact fixed-point remainder. It does not read a clock,
select or calibrate a clocksource, publish a timestamp, order concurrent
samples, implement a vDSO, or satisfy a Linux acceptance gate.

`f0` uses the pinned compiler's legacy SysV entry:
`(request_ptr, request_len, reply_ptr, reply_len, unused_ptr, unused_len)`.
Buffers must be valid and disjoint. The third borrowed buffer is unused and
may have length zero. The request is exactly 56 bytes, seven little-endian
u64 words: previous sample, current sample, counter mask, maximum admissible
delta, multiplier, shift, input fraction. The output is three little-endian
u64 words: status, whole nanoseconds and output fraction. The return register
also carries the u32 status.

| Status | Meaning |
|---|---|
| 0 | Converted successfully |
| 1 | Fewer than 24 output bytes: no read or write |
| 2 | Wrong request length |
| 3 | Invalid profile or out-of-range sample |
| 4 | Modular delta outside caller's permitted window |
| 5 | Converted whole nanoseconds exceed u64 |

With a sufficient reply buffer, refusal returns its status and two zero words.
Any reply tail, request and unused buffer remain unchanged.

The mask must contain contiguous low ones with width 2 through 64; both
samples must fit. The configured maximum delta is nonzero and at most
`mask >> 1`. Compute `delta = (current - previous) mod (mask + 1)`. A small
modular delta is evidence only under the caller's **same-counter, forward
sampling and bounded real elapsed-cycle** contract. Resets, long gaps that
wrap a full period, and inconsistent snapshots may alias valid values; this
leaf cannot detect them. Read and validate actual counter provenance upstream.

The scale is `1 <= multiplier <= 2^32 - 1`, `0 <= shift <= 32`, and
`0 <= fraction < 2^shift`. The output is quotient and remainder of
`delta * multiplier + fraction` over `2^shift`. Reuse the returned remainder
only with the same fixed-point scale. Two 32-bit limbs preserve the entire
up-to-96-bit numerator. Each intermediate limb product plus carry fits u64.
Overflow is checked **after** scaling, so a numerator larger than 64 bits
does not cause an erroneous rejection when the quotient fits.

Run on Linux x86-64 with GNU binutils and the source-rebuilt compiler pinned
in [the existing toolchain instructions](build.md):

```sh
python3 -I -B tests/test_clocksource_delta.py --compiler /absolute/path/to/native-compiler
```

The runner verifies the compiler identity, rebuilds the ELF object twice with
an empty PATH, checks no undefined symbols and binds the loaded code to the
object's exact `.text`. It executes the actual HIA code against a Python
big-integer oracle over every accepted counter width and shift, wrap and
window boundaries, all six statuses, and repeated conversions with remainder
carry. No clock-frequency measurement or boot test is implied.
