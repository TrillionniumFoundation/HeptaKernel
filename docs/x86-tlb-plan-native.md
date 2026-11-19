# Native HIA single-page TLB sequence admission (experimental)

`src/x86_tlb_plan.hepta` is **real Core v8 HIA source** compiled by the
unchanged pinned `selfhost_elf` compiler, producing ordinary native x86-64
code. It consumes a caller-provided, immutable sequence, and returns
an admission status. No executable privilege opcode is generated or invoked.

Input: 40-byte little-endian header `root, owner_root, page_va, profile, count`,
then exactly `count` 40-byte records `op, va, expected_old, observed_old, candidate`.
`1` = IRQ disable, `2` = PTE write, `3` = INVLPG, `4` = IRQ enable.
Only write records carry old/new values, only INVLPG carries the page VA,
and IRQ records have four zero parameters. The profile is exactly 15
(caller *claims* CPL0, single CPU, PCID off and global mappings absent);
root must be nonzero, 4 KiB aligned, within 52 physical-address bits, and
equal the claimed owner root. The 48-bit virtual page must be canonical and
4 KiB aligned.

Writes must be inside an IRQ mask, have an exact caller-observed old value,
change the entry, and await a matching INVLPG before another write or
IRQ enable. Subsequent writes to the same VA must use the previous
candidate as the entire old word, even across an INVLPG. At least one
write and a balanced mask pair are required. Up to 64 records are admitted.

Statuses: 0 accepted; 1 invalid length/count; 2 unsupported or inconsistent
caller-declared authority; 3 noncanonical or unaligned VA; 4 illegal operation,
dataflow, ordering or unbalanced final state. All paths are read-only.
The native differential oracle checks admission/refusal, input immutability
and a compiled dishonest always-success HIA negative control. An empty-PATH
second compilation must be **byte-identical**. `make test-x86-tlb-plan`
is included in `make test` and the Foundation workflow.

This is a **native HIA policy program**, not the actual HIA kernel
privilege/atomic backend. It cannot attest real CPL/CR3, PTE memory
readback, hardware A/D changes, page-table ownership, interrupt
mask execution, NMI handling or SMP state. It does not emit/execute
CLI, STI, INVLPG or CAS, does not synchronize the hardware TLB, and
does not permit recycling pages or closing any Linux syscall gate.
The current non-HIA QEMU observer remains necessary. Real
source-verifier-authorized privilege effects plus selfhost lowering
and QEMU fault tests remain the next blocking work.

The independent oracle includes 160 additional positive native plans across
canonical lower/upper addresses, independent roots, chained exact-old updates
and repeated mask/flush cycles. The report records source, native object and
shared-library hashes, with explicit hardware and Linux closure exclusions.
