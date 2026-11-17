# Native HIA four-level indexed snapshot walk (restricted x86-64 profile)

`src/x86_walk4_indexed.hepta` is **real HIA Core v8** compiled through the
same locked self-hosted native ELF backend as the original page-table
components. It adds hardware-style VA-derived selection of all four PTEs
and checks the three physical parent links, rather than trusting that the
caller selected the correct entries.

The `f0(request:readbuf, reply:mutbuf, tables:mutbuf)` ABI receives an
exactly 48-byte little-endian request containing six `u64` values:
`VA, MAXPHYADDR, CR3, PML3_PAGE_PHYS, PML2_PAGE_PHYS, PML1_PAGE_PHYS`.
The separate, caller-owned 16 KiB snapshot contains exactly four consecutive
4 KiB pages (PML4, PML3, PML2, PML1) in that order.

The HIA code validates the 32–52-bit physical-address profile; nonzero,
aligned, in-width page identifiers; and the non-PCID CR3 base (only PWT/PCD
low flags are admitted). It selects entries using VA bits 47:39, 38:30,
29:21, and 20:12. The PML4E, PDPTE and PDE physical addresses must link
to the supplied next-level page identities. It then applies the verified
4 KiB-only supplied-entry permission and reserved-bit policy inherited from
`src/x86_walk4_entries.hepta`. NX semantics assume the caller independently
verified EFER.NXE.

The 16-byte reply contains little-endian `u64(status),u64(result)`.
Result is the same success/physical-offset/permission bit packing as
`walk4`, and is zero on any rejection. The native `u32` function return
equals `status`: 0 success, 1 insufficient reply, 2 malformed request,
3 wrong snapshot length, 4 invalid page identity/physical-width metadata,
5 physical parent-link disagreement, 6 entry policy refusal. The too-short
reply must remain entirely unchanged; all snapshot and request memory is
read-only in behavior. All failures have independent test oracles.

The paired Python oracle examines actual bytes, derives each index
independently, and verifies the exact reply, unmodified request and table
buffers, guard sentinels, negative cases and exact HIA object/shared-text
identity. A separately compiled **dishonest HIA implementation** is a
mandatory rejection control. `make test` and the primary CI both run it.

**Scope boundary:** All pages and physical addresses are supplied by the
caller; a buffer labelled by a physical address is not independently
authenticated. This adds indexed, linked snapshot interpretation, **not**
actual CR3 reads, physical memory ownership, TLB synchronization, MMIO,
atomic page-table updates, SMP correctness, or a HIA privileged backend.
The non-HIA QEMU bridge remains. All 17 full Linux gates and 422 syscall
rows stay open; `make full-acceptance` remains HOLD.
