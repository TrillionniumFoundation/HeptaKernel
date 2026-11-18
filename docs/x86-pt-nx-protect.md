# Native HIA execute-disable downgrade (RX -> R/NX)

`src/x86_pt_nx_protect.hepta` is real HIA Core v8 `selfhost_elf`
source, compiled using the locked native compiler with no embedded machine
bytes, host libc or kernel Linux syscalls. It takes an exact 32-byte request
(leaf index, expected-old PTE, proposed-new PTE, CPU capability profile),
16-byte reply and a mutable 4 KiB leaf table. It refuses to change the table
unless the indexed 64-bit old value matches exactly, the old leaf is present,
read-only, executable (NX clear), physically in range, reserved bits clear,
and the candidate is exactly old OR (1 << 63). The operation only sets NX;
address, user, Accessed/Dirty, caching, PAT, global and software bits remain.
It additionally requires capability NXE and validates PGE for global leaves.

Responses: 0 permitted change; 1 short reply; 2 bad request length;
4 bad table length; 6 invalid leaf/transition/index; 8 bad CPU profile;
9 stale old PTE. Every refusal leaves the entire table unchanged. The
independent Python byte-level oracle exercises valid leaves, stale replay,
invalid and reserved bits, wrong NXE/PGE, wrong lengths, boundary indices and
mutable-buffer guards, against both the native HIA implementation and an
intentionally dishonest always-success HIA implementation. Build provenance
recompiles with empty PATH and checks HIA object against loaded .text bytes.

**Live single-CPU QEMU experiment:** An isolated PC 32MiB and Q35 64MiB
non-HIA bridge writes a RET opcode before HIA RX mapping, executes it,
captures CPU-updated PTE.Accessed, calls original HIA RX->NX code, and
compares the live PTE to the native reply. After a non-HIA INVLPG data reads
still succeed but instruction fetch must produce a real #PF with error 0x11
(P=1, W=0, U=0, I/D=1), exact CR2/RIP, and IST1 entry. Independent
negative controls demand a stale-but-valid old value be refused with an
unchanged PTE, and a deliberately restored RX PTE execute after INVLPG.
All three images must contain byte-exact original HIA .text.

This is still an exclusive-owner quiescent update, and its eight bytewise
stores are not a CPU CMPXCHG. Privileged INVLPG, CR2, exception entry,
and the initial test opcode writer remain non-HIA. SMP TLB shootdown,
provenance, concurrent safety and Linux `mprotect` are not implemented.
The non-HIA boot/exception bridge and all 17 Linux acceptance gates stay open.
