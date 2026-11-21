# Native HIA two-leaf prevalidated 4 KiB PTE update

`src/x86_pt_pair_commit.hepta` implements a restricted **single-owner**
two-PTE transition in the pinned Core v8 `selfhost_elf` language. The
64-byte request encodes (u64 little-endian) slot A, expected old A,
replacement A, slot B, expected old B, replacement B, CPU capability flags
and a zero reserved word. The 4096-byte table is a caller-supplied writable
page, and the receipt is exactly 16 bytes. Capability bits 0..7 encode
physical width 32..52; bit 8 is NXE and bit 9 PGE.

Both slots must be distinct and in [0,511]. Both candidate PTEs must be
present, refer to different nonzero physical 4 KiB frames within the declared
physical width, have no reserved bits 52..62, satisfy W^X and require NXE/PGE
for the relevant NX/Global flags. **Both expected-old words are checked
against the table before either entry is written**. Only after all checks
pass does the HIA native code update A then B and write a receipt containing
both new values. On admission failure neither the table nor receipt changes.
Statuses: 0 success, 1 wrong receipt, 2 wrong request, 3 wrong table,
4 invalid slots, 5 malformed capabilities/reserved word,
6 invalid/aliasing replacement leaf, 7 stale expected-old entry.

The independent byte oracle tests reverse-order slots, both stale-old
variants (especially stale B preserving A), malformed geometry/capabilities,
W^X, reserved flags, aliasing, canaries, full table readback, a genuinely
HIA-compiled always-success no-op negative control, and locked native
object/shared-library .text equality. Two isolated empty-PATH native
rebuilds must match the original object.

This is a **prevalidated ordered pair of sequential stores**, not a
hardware-atomic 128-bit transaction, rollback guarantee after faults,
linearizable SMP CAS operation or kernel page-table publication protocol.
The HIA compiler does not expose CR3, privileged INVLPG, IPIs, PTE CAS,
DMA exclusion, live page ownership authority or exception-safe recovery.
No real user PTE publication, `execve`, Linux ABI, or full gate is closed.
The existing 17 gates and 422 syscall rows remain HOLD.
