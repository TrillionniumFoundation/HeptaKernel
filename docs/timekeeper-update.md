# Native single-owner timekeeper update

The new `f0` validates an expected generation, reuses the clocksource arithmetic
in [the delta converter](clocksource-delta.md), and adds its whole nanoseconds
to a caller-owned monotonic total. It installs the next sample, fractional
carry, total and generation only after all checks succeed.

This is a **serialized borrowed-buffer** primitive: callers must supply
valid, disjoint request, reply and state regions and hold exclusive access
through the call. This is not a seqlock, concurrent publication, recovery or
atomic commit under a fault. In particular, the reply is temporary scratch
until return. No hardware clock is read; a caller must enforce the same sample
provenance, elapsed-cycle and scale contract as the delta converter. An
external owner initializes the whole state; reinitialization or switching
clocksource profiles requires its own synchronization and epoch protocol.

The request contains exactly two little-endian u64 words: expected generation
and current sample. State contains exactly eight: previous sample, fraction,
total nanoseconds, current generation, mask, delta limit, multiplier and
shift. Those last four profile words are never modified. The three reply
words are status, new total nanoseconds and new generation. The u32 return
register mirrors status. Rights and epoch/source identity are not inferred
from the generation.

| Status | Meaning |
|---|---|
| 0 | Updated; a valid zero-delta sample still consumes its generation |
| 1 | Reply shorter than 24 bytes, with no read/write after the length check |
| 2 | Request length is not exactly 16 bytes |
| 3 | Invalid scale, mask, fraction or sample |
| 4 | Delta outside allowed cycle window |
| 5 | Scaled step overflows u64 |
| 6 | State length is not exactly 64 bytes |
| 7 | Stale expected generation |
| 8 | Generation exhausted; never wraps |
| 9 | Adding the scaled step would overflow the total |

All denials leave the complete state and request unchanged on return. With
sufficient reply capacity, a failure returns its status and two zero words.
The caller should not attempt to read the reply or state concurrently.
The minimum addition is zero; success never decreases the accumulated value
or increments it via u64 wrap. Testing replay with the old generation
verifies refusal in the serialized model, not concurrent replay protection.

Run with the compiler in [the existing toolchain instructions](build.md):

```sh
python3 -I -B tests/test_clocksource_delta.py --compiler /absolute/path/to/native-compiler
python3 -I -B tests/test_timekeeper_update.py --compiler /absolute/path/to/native-compiler
```

The second runner verifies the pinned parent source, composes the exact
parent validation/arithmetic blocks with the new entry, and directly calls
the resulting **single native HIA object**. The compiled code has no
undefined symbols and the loaded section matches the emitted code. The
bigint oracle checks every output/status and saved-state byte, all ten
statuses, all mask widths and shifts, actual repeated native calls with
saved fractional feedback, and stale replay refusal. No Linux clock,
scheduler or full-acceptance gate receives credit.
