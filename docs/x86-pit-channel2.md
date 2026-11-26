# Experimental native HIA PIT channel 2 reference windows

This is an isolated descendant of #190 at `d6f498a447902620856003e98ddaf60b4dc1bc62`. It adds
four true HIA functions in the existing experimental selfhost_elf profile:
f0 programs a stopped, speaker-disabled PIT channel 2 in mode 0 using
a 16-bit count in [1024,60000]; f1 raises gate with readback; f2 polls
the actual OUT bit with a nonzero finite iteration budget; f3 closes the
gate with readback. No host port I/O executes. Status codes: 0 success,
6 inadmissible arguments, 9 unexpected gate/speaker state, 10 control
readback failure, 11 count-latch failure, 12 poll exhaustion.

The compiler itself produces the port IN/OUT operations. The HIA f0
reads the latched count, and accepts only a count in [requested-1024,
requested] after confirming the gate/speaker/OUT bits are clear. This
bounded interval is experimental, not exact physical timing or a proof
that a counter never advances with its gate low. In the first local
attempt, the independent observer required the stopped count to equal
0x4937; it failed before calling the HIA subject. Diagnostic reads
returned 0x491f on PC and 0x4927 on Q35. The original failure and raw
observations are retained locally. The revised observer explicitly
bounds the initial distinct count within 4096 ticks and both requested
counts within 1024 ticks; the latter bound is also enforced by HIA.
There is no assertion of high-precision calibration.

The independent observer uses actual port reads and its own masked APIC
counter with divider 16. It exercises two reference windows (12000 and
24000 PIT ticks), rejects invalid input/active speaker state, checks
bounded wait exhaustion, checks OUT and gate on expiration, and requires
the second elapsed APIC count to be 1.5 to 2.5 times the first. It deletes
the precise count-high-byte write, gate-start write, status read, or
gate-stop write independently in the linked native object's private
function bodies; each modified subject must produce its distinct
failure path and independent hardware readback. The source and every
linked ELF text section are bound to the admitted compiler output.
Local isolated runs of both the earlier independent-only count readback
and the final native count-readback version completed 10/10 cases.
The final native source/object/text hashes are recorded in each run.

The fixed #952 experimental compiler is required; production compiler
locks and the parent #190 calibration tests are unchanged. The subject
does not establish exclusive PIT ownership, preserve arbitrary original
counter configuration, validate time against an external clock, provide
a scheduler clocksource, or compose these functions into #190 yet.
The observer may program and restore its own test setup; port 0x61
gate/speaker bits and saved APIC configuration are restored on its
terminal success/expected-negative paths. This is not complete Linux
driver, timing, or resource-authority acceptance. Independent
exact-head CI is required; all original 17 HOLD gates and 422 syscall
obligations remain.
