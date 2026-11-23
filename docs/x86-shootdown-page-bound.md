# Native HIA bounded per-CPU shootdown page identity binding (HOLD)

This separate Core v8 `selfhost_elf` HIA module strengthens the previous
**caller-supplied** cross-CPU TLB shootdown acknowledgement snapshot preflight.
It still contains **no** IPI, CR3 read, INVLPG, atomic primitive, fence,
exception entry, hardware privilege effect or authority to recycle frames.

The immutable little-endian input is exactly `48 + 40*N` bytes for
`N=1..64`. The six 64-bit header fields remain expected CR3 root,
48-bit canonical 4KiB page VA, nonzero epoch, online CPU mask, target
CPU mask, and row count. Each 40-byte row is:

`{CPU index, claimed epoch, claimed root, completion flags, claimed page VA}`.

CPU IDs must be unique, below 64 and cover the target mask exactly; the target
mask must be a nonempty subset of online CPUs. The root is nonzero, 4KiB-aligned
and below 2^52; the VA is 48-bit canonical and page-aligned. Each claimed
acknowledgement must exactly match the header epoch, root, *and virtual page*,
with completion flags exactly 3. In particular, reusing an unchanged claimed
ack-row under a changed requested VA returns status 4. The existing v1 wire
format and its source remain unchanged; v2 is a new, incompatible 40-byte-row
profile, and no decoder guesses between the two formats.

Status 0 means the **untrusted record is internally consistent**. Statuses
1..5 respectively indicate wire/length error, header/profile violation,
duplicate/non-target CPU, stale or mismatched acknowledgement (including VA),
and missing target CPU. Full independent native differential byte-array
tests include valid 64-CPU input, CPU 63, forged page identity, header replay,
stale epochs and roots, malformed masks and lengths, and an always-accept
HIA negative substitution. Byte-identical empty-PATH compilation is required.

**Critical distinction:** binding a row to the page identity does not make
the row truthful or prove that an actual CPU invalidated this page. A malicious
host can still invent a matching row. Memory ordering, online-set stability,
atomic publication, IPI completion, actual CR3/VA observations and TLB
coherence need a trusted end-to-end implementation and independent hardware
tests. None of the 17 Linux acceptance gates or 422 syscall obligations are
closed, and no physical frame reclamation is authorized.
