# Native HIA TLB plan: caller-supplied entry-byte binding

The fixed HIA Core v8 `selfhost_elf` compiler emits the native x86-64 object
for `src/x86_tlb_plan.hepta`. Its exported `f0` does **not** issue CLI, STI,
INVLPG or a privileged write. It checks a proposed order of operations under
a caller-asserted single-CPU, exclusive-owner, no-global/no-PCID profile.

The 40-byte little-endian request header holds root, owner, page VA, flags
(exactly 15), and 1..64 rows. Each row has five little-endian u64 words:
operation (1 mask, 2 write, 3 invalidate, 4 unmask), page, expected-old,
observed-old, candidate. A request must contain exactly 40+40*n bytes.
The third ABI buffer is now an **exactly eight-byte mutable capability** to
the entry's initial little-endian value, read only by HIA. An undersized or
oversized entry buffer returns status 5. The first write's old word must
equal these eight bytes, not merely the row's self-declared observation.
Each subsequent write must use the previous candidate as old. Every write
must be followed by an invalidate of that page before a further write or
an IRQ unmask. Refusals never change the entry, request or reply.

`make test-x86-tlb-plan` independently derives outcomes from the request
and entry bytes, guards inputs and checks the deliberately dishonest native
HIA control, followed by empty-PATH native object identity checking.
Explicit positive sequences, wrong-initial-entry, missing/extra byte, stale
replay and forged-observation controls are included.

**Boundary:** A caller-supplied eight-byte capability is not a proof that
the bytes came from the active physical page-table entry or that they
remain stable. The function does not mutate any PTE or execute privilege
instructions. No native HIA CAS, CPU state observation, TLB shootdown,
interrupt handler, SMP/NMI safety or complete Linux functionality is
claimed. The non-HIA boot bridge is still required. All 17 Linux full
acceptance gates and 422 syscall obligations remain open.
