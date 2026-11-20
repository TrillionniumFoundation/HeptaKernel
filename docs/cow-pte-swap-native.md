# Restricted native HIA COW private-frame PTE switch

`src/cow_pte_swap.hepta` specializes the existing genuine HIA Core v8
`selfhost_elf` 4 KiB PTE committer. It admits only a shared user leaf that
is present, read-only, NX, nonglobal and not a huge page. The replacement
must have a different nonzero 4 KiB physical frame within the declared
32–52-bit physical width and be **exactly the old PTE with its frame
substituted and writable bit set**; all other A/D, cache, PAT, user and
software bits are preserved. Unsupported NXE, malformed reserved bits and
out-of-range physical frames are refused.

The native HIA function reads and compares the live 64-bit table entry
before storing the new one. Failure statuses and the 32-byte request /
16-byte reply interface match `src/x86_pt_commit.hepta`.
`tests/test_cow_pte_swap.py` uses an independent byte-level Python oracle,
boundary, stale, invalid-bit and randomized cases. A separate compiled HIA
always-success no-op is required to fail the oracle. The original compiler
lock, empty-PATH byte-for-byte rebuild and complete baseline checks remain.

**This is not Linux COW closure.** The caller must authenticate and
exclusively own the page table and destination physical frame, stop
concurrent readers and mask interrupts. Writes are ordinary sequential
byte stores, not 64-bit CAS. This component does not copy a frame,
perform the fault handler, change CR3, invalidate TLB entries, synchronize
other CPUs, implement memory reclamation or establish hardware user-mode
behavior. Hardware fault and TLB effects remain unverified for this new
component. All 17 full Linux acceptance gates and 422 syscall rows
remain HOLD. The non-HIA `boot.S` test bridge remains explicitly separate.

## Isolated actual hardware-fault experiment

The original HIA `cow_pte_swap.hepta` machine code is renamed for the
linker without modifying its `.text`. An E820-admitted QEMU guest first
maps a source physical page (0x601000) read-only and NX at virtual 0x400000.
A real CPL0 store produces a precisely checked hardware #PF (P=1,W=1,U=0)
on an IST1 exception stack. Only then does the original HIA machine code
change the real 4KiB PTE to a different, already initialized destination
frame (0x602000), preserving the CPU-updated Accessed bit. The explicitly
**non-HIA** handler performs INVLPG and IRETQ to retry the same CPU store.
The independent observer checks both complete 4096-byte physical pages,
virtual readback and the hardware Dirty bit.

PC/32 MiB and Q35/64 MiB run four cases each: true remap; a syntactically
valid but stale expected-old; a compiled malicious HIA no-op; and a
post-HIA test-bridge restoration that must re-fault. These are separate
isolated hardware experiments, not a claim to have implemented Linux
COW. The source/destination physical pages are E820 admitted but still
have no authenticated PMM/refcount owner in this test. Page copying,
allocation, atomic PTE writes, concurrent faults, SMP TLB shootdown,
signal delivery and user-mode Linux execution are not covered.
