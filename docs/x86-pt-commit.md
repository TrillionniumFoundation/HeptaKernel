# Native HIA single-owner leaf PTE commit

`src/x86_pt_commit.hepta` is native HIA Core v8 `selfhost_elf`
code; the fixed compiler produces an x86-64 ELF64 object without libc or
host Linux syscalls. This is the **first actual HIA page-table write** in the
QEMU 4 MiB test mapping, not just a PTE integer returned to assembly.

## ABI and admission

The exported `f0(request:readbuf, reply:mutbuf, page:mutbuf)` takes a
32-byte request of four little-endian `u64` values:

- `slot` in 0..511, identifying an 8-byte 4KiB page-table entry
- `expected_old`, compared against all 8 bytes currently in the table
- `candidate_pte`, already produced by the separately checked HIA
  `x86_pte_leaf` for the intended virtual and physical addresses
- `caps` in the same bit format as the PTE encoder: MAXPHYADDR 32..52 in
  bits 0..7, active EFER.NXE in bit 8 and active CR4.PGE in bit 9

The mutable table capability must have **exactly 4096 bytes**.
The reply capacity must be at least 16 bytes, containing status and value
(u64 little endian). The native function checks the expected slot,
that the proposed entry is present, limits the physical address to the
observed MAXPHYADDR, refuses unsupported reserved PTE bits, refuses W+X
and USER+GLOBAL, and requires active NXE/PGE where appropriate.

The statuses are 0 (committed, reply value equals proposed PTE), 1 (short
reply, no writes), 2 (bad request), 4 (wrong table capacity), 6 (invalid
entry/slot), 8 (unsupported/malformed CPU capabilities), and 9 (stale
expected old entry). Every refusal with sufficient reply storage writes
status and a zero value, and **does not change any table byte**.

This is an **exclusive-owner conditional write**, *not* an atomic CAS:
the read/compare/store sequence is not linearizable against concurrent
writers. The caller must provide non-overlapping request, reply and page
capabilities, own the table exclusively, and maintain stable CPU capability
and page-table state across the call. No physical address provenance,
page-table hierarchy ownership, virtual-address policy, DMA access, SMP TLB
shootdown, IOMMU or privilege transition is established by this component.

## Real QEMU integration

In `arch/x86_64/boot.S`, the non-HIA bridge initializes the other 511
leaf PTEs and parent hierarchy as before, then passes the actual
`page_table_4m` page to `pt_commit_f0` before loading CR3. The bridge
checks the native status, returned value and actual entry readback.
A separate fault-injection image supplies a deliberately stale expected-old
entry, requiring rejection before CR3 is reloaded.

The NX fetch-fault and CR0.WP supervisor write-fault images now also execute
the native HIA commit first, so their x86 hardware protection behavior is
tested on a leaf **written by HIA itself**. Test-only bypasses still use
non-HIA mutation intentionally as negative controls.

`make test-x86-pt-commit` runs an independent Python byte-array oracle over
guarded request/reply/table regions and requires a deliberately dishonest HIA
implementation to fail. `make test-boot` covers PC and Q35 positive, stale
expected-old refusal and prior hardware fault/bypass controls. `record-build`
reproduces the exact HIA object with empty PATH and verifies that the
linked QEMU entry's complete `.text` remains byte-identical.

The rest of `boot.S` is **not HIA**. Table allocation, all higher page-table
levels, slot 1..511 initialization, CR3, CPUID, exception entry, CR0.WP,
EFER.NXE and fault handling still use the GNU assembly bridge. Privileged HIA
backend extensions remain required before replacing these operations. The
complete Linux 7.3.4 compatibility ledger, all 17 gates and 422 x86_64
syscall obligations remain open.
