# Native HIA x86-64 PML4 root-page admission

The real HIA Core v8 source is `src/x86_cr3_root.hepta`. The pinned
`selfhost_elf` compiler emits the native x86-64 ELF used by the independent
differential test, without libc calls, Linux syscalls or embedded foreign code.

The 24-byte request contains little-endian u64 words
`(candidate_cr3, max_physical_address_bits, required_pml4_index)`.
The third public argument remains the fixed self-host `mutbuf` ABI
holding exactly 4096 bytes of caller-supplied PML4 data. At each entry
read, native HIA creates a local `borrow.read` loan, passes the `readbuf`
capability to a typed private helper, and ends the loan before any next
control-flow transfer. This enforces the helper's read-only access while
preserving the pinned selfhost_elf entry signature. The actual native
machine code never writes to the PML4 data. The second
argument is a reply buffer of at least 16 bytes receiving
`(status, present_entry_count)`; on error the count is zero.

This deliberately restricted profile accepts physical-width 32..52,
nonzero CR3 root address under that width, CR3 low flags limited to
PWT/PCD (no PCID), and a required PML4 index 0..511. It scans *all*
512 PML4E words. A present entry must not have PS set, must have
zero bits 52..62, must contain a nonzero page-aligned subordinate table
pointer below the declared physical width. NX at bit 63 is allowed
only because this profile presumes EFER.NXE has already been established
by the independent CR3 CPU admission gate. Non-present entries are not
interpreted as hardware-present descriptors. The requested PML4 slot must
be present, but other slots may also be mapped.

Statuses: 0 accepted; 1 short reply (no writes); 2 malformed request;
4 root length mismatch; 5 no required present entry; 6 invalid CR3
profile/index; 7 malformed present PML4 entry. The validation is
*read-only* and no page-table entry is installed.

`make test-x86-cr3-root` compiles the exact source with the pinned
native HIA compiler, checks undefined symbols and empty-PATH deterministic
ELF bytes, compares the loaded library machine text to the object and
runs an independent byte-oriented Python oracle with immutable-buffer,
reply-guard, reserved-bit, physical-width and missing-mapping negative
cases, including an OS-mprotected read-only page. A separate
invalid HIA source attempting `buffer.store` through a private `readbuf`
loan must fail with invalid-source status 2; the same helper with that
store replaced by `buffer.load` must compile under the unchanged public
three-buffer ABI. External raw ABI aliases, snapshot races and root-pointer
provenance remain outside this property. An independently dishonest HIA unconditional-admit object must fail
the oracle's root-admission case.

**This is not authenticated physical RAM or actual CR3 ownership.**
The caller supplies the root buffer, physical width and intended slot; a
concurrently changing PML4 or a forged snapshot is not excluded. It
does not issue MOV CR3, INVLPG, atomic CAS or TLB shootdown, and does
not verify that all descendants are valid. The non-HIA boot bridge remains.
Complete Linux architecture/ABI/driver acceptance stays HOLD.
