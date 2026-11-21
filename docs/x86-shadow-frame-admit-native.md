# Genuine HIA shadow-table PMM frame admission

`src/x86_shadow_frame_admit.hepta` uses the pinned HIA Core v8 `selfhost_elf` native backend. This is a **snapshot preflight**, not a parent PDE publisher.

The exact 64-byte little-endian request describes proposed shadow 4KiB page physical address, old table physical address, expected old parent entry, candidate parent entry, PMM arena base, page count, reserved prefix count, and MAXPHYADDR width. The shadow and old table must be distinct, nonzero, aligned, within the declared MAXPHYADDR range, inside the same arena, and outside its reserved prefix. This deliberately supports only present writable nonleaf parent entries with exactly the low flags 0x003; other valid Linux PDE flags are not yet supported.

The state capability must be an exact 64+ceil(pages/8)-byte PMM header and bitmap image. HIA checks original PMM magic, base, count, reserved prefix and free-count bounds, as well as both selected allocation bits and zero header padding. Its native entry borrows this state as a read-only HIA view and returns a 16-byte receipt (candidate parent, shadow address) only if all gates pass. All rejections leave the receipt, request and PMM bytes unchanged. An independent Python oracle tests valid and hostile state/parent values; a separately compiled genuine HIA always-success function must be detected. Native object and shared library .text must be identical, and empty-PATH rebuilds byte-identical.

**Important limitations:** PMM bitmap allocation is not exclusive ownership: an unrelated module can supply an equivalent forged state, and this checker does not authenticate the parent entry's physical address or contemporaneous CPU CR3, forbid writable aliases, prove page pinning, or prevent post-check mutation. It does not verify the *entire* bitmap/free counter as `pmm_bitmap_integrity.hepta` does, nor does it execute CAS/INVLPG, synchronize APs, publish a PDE, or implement hardware exception rollback. Callers must still use existing independent PMM integrity and hardware readback gates. No new Linux capability, syscall, architecture, or acceptance gate is closed; the pinned 17 full gates and 422 rows remain HOLD.

## Live QEMU HIA PMM-to-shadow integration (isolated, single CPU)

`make test-shadow-owner-hw` links the *unchanged* locked native HIA PMM
(`src/kernel.hepta`), offline full-page PTE shadow builder
(`src/x86_pt_pair_shadow.hepta`) and frame admission preflight
(`src/x86_shadow_frame_admit.hepta`) into an isolated x86-64 boot. The
independent NON-HIA test bridge first admits the 17-page 0x600000 E820
arena, calls native HIA INIT and ALLOC_RUN(2), and checks the actual PMM
state and exact 0x601000/0x602000 frame allocation. The old frame is a
zeroed PTE table; the new frame begins with canaries. HIA constructs the
4KiB shadow page from the original snapshot and its complete output is
checked, word-for-word, before HIA validates the live PMM bitmap,
arena/width geometry and old/new nonleaf parent values. Only then the
non-HIA observer installs one parent PDE and reloads CR3; real CPU reads
must observe the two swapped physical data frames.

The PC 32MiB and Q35 64MiB matrices each contain positive hardware
execution and four independently distinguished negative controls:
stale expected parent word, clearing the HIA PMM shadow allocation bit,
a **separately HIA-compiled** dishonest always-success admission
function, and mutating the PMM allocation bit *after a successful
admission* followed by an independent second HIA check. Every negative
must retain the active old parent PDE, show intact shadow/old page
bytes, and exit with its *specific* observer marker. Python binds exact
source, compiled native objects, unique linked .text sections, QEMU
image digests, guest output and return codes to the candidate.

This test establishes neither an authenticated owner capability nor
linearizable publication. The HIA PMM snapshot could be forged and the
checker does not establish atomic compare/exchange, writable-alias
exclusion, DMA immunity, SMP page-table quiescence, AP TLB shootdown,
native HIA CR3/IRET/exception operations or recovery across faults.
The assembler is an explicitly non-HIA bridge, not a rewritten Linux
kernel component. These results do not alter the 17 HOLD gates or 422
unimplemented Linux x86-64 syscall rows.
