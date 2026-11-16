# Native HIA x86-64 4KiB PTE policy leaf

`src/x86_pte_leaf.hepta` is a genuine HIA Core v8 `selfhost_elf`
program. It validates a prospective 4KiB virtual-to-physical mapping and
returns a **leaf PTE value**, rather than modifying a live page table.

The ordinary `f0(readbuf,mutbuf,mutbuf)` request must contain exactly
three little-endian u64 values: `(virtual_address, physical_address,
permission_flags)`. Flags are READ=1, WRITE=2, EXECUTE=4, USER=8,
GLOBAL=16. READ is mandatory; unsupported flag bits are rejected.
Both addresses must be 4096-byte aligned. Virtual addresses must be
canonical under **four-level 48-bit paging**, and physical addresses are
limited to 52 bits. A 16-byte reply contains little-endian
`(status, leaf_pte)`. Statuses: 0 accepted, 1 reply too short (no
writes), 2 malformed request length, 6 invalid geometry or bitfield,
7 W+X, user+global, or user-in-kernel-upper-half policy violation.
Every failed request with a sufficiently large reply returns value 0.

The encoded value sets Present, optional RW/US/G, and NX when EXECUTE
is absent. This policy assumes the CPU supports NX and **EFER.NXE has
already been enabled by a separately validated privilege/boot mechanism**.
For a real page table, enclosing parent entries, U/S inheritance,
PAT/cache attributes, physical reserved-bit constraints for the actual
MAXPHYADDR, speculative/fault behavior, TLB shootdowns, CR0.WP,
SMEP/SMAP, and safe page-table memory ownership must also be verified.
There is **no CR3 write, live page-table allocation, page-fault handling
or genuine address-space isolation here**.

`make test-x86-pte` runs a deterministic independent Python integer oracle
against the compiler-produced native HIA code, with malformed/canonical
address, W^X, USER/GLOBAL, reply guard, and a dishonest native HIA
allow-all control. CI independently parses/verifies the HIA Core source
and `tools/record_build.py` binds `src/x86_pte_leaf.hepta` to a
byte-identical ELF object and loaded test .text under empty PATH.

The present scope is a single pure x86-64 encoding/policy subcomponent;
QEMU does **not** install its output as an active mapping, and the
non-HIA `boot.S` remains. All 17 Linux acceptance gates and 422
syscall obligations remain open.
