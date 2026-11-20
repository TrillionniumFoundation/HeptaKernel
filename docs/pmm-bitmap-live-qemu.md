# Native HIA full PMM bitmap integrity on QEMU hardware COW

The existing genuine HIA Core v8 selfhost object scans the live 8192-byte
PMM state after HIA allocation of two real 0x600000-zone physical pages.
Its frozen 24-byte request binds base 0x600000, count 17, reserved 1.
The non-HIA observer checks unchanged whole state, request and active PTE,
and checks exact scanner status before the separate native HIA frame binding
and actual hardware write-protect #PF/COW/page-table switch and store retry.

Both PC/32MiB and Q35/64MiB execute five isolated images: normal success,
stale free count (status 5), erased reservation bit (status 4), dirty
bitmap tail bit (status 4), and malicious HIA always-success on the invalid
free count. Negative images must refuse before any write fault, with
independent Python markers and exit-code validation. Original HIA native
and linked text bytes must match. Raw QEMU commands, stdout, stderr and
image hashes are retained in the Foundation artifact.

Run make test-pmm-bitmap-hw (also part of make test-boot and make test).
This remains single-owner and quiescent: non-HIA assembly still performs
E820 handoff, privilege setup, CR3, INVLPG, exceptions and IRETQ.
Nothing here proves pointer provenance, concurrent ownership, atomic COW,
SMP shootdowns, or Linux ABI/drivers. All 17 full gates and 422 syscall
obligations remain HOLD; pinned Linux and HIA compiler are unchanged.
