# Native HIA binding between one live PMM arena and a COW PTE

`src/cow_frame_binding.hepta` compiles through the **locked** genuine HIA
Core v8 selfhost ELF compiler. The function is read-only and accepts a
48-byte request containing source physical page, target physical page,
frozen expected-old PTE, arena base, arena page count and reserved prefix.
Its eight-byte PTE input must be a trusted alias of the actual live
page-table entry. The PMM input must be the current HIA-initialized arena
state, not an untrusted snapshot.

Before allowing a private-page split, native HIA checks the exact
PMM header identity, alignment, 52-bit bounded arena range, distinct
aligned source/target, non-reserved page indices, both allocation bits,
and a matching Present/User/RO/NX/non-Global 4 KiB PTE physically pointing
at the source frame. It does **not** write the PTE, PMM or page data.

An independent Python byte oracle evaluates valid and deliberately
invalid requests, bitmap mutations, forged PTEs, metadata disagreements,
truncation and reproducible random mutations. A dishonest HIA
always-accept source is separately compiled and must be rejected by
the oracle. `make test-cow-frame-binding` checks empty-PATH original
HIA object byte identity. The Foundation CI binds source, verification
and native execution; no change to the HIA toolchain lock is made.

A read-only capability check is not a proof of exclusive ownership.
In particular this primitive does **not** verify the CR3 walk or provenance
of input pointers, validate all PMM bitmap bits/free-count consistency,
perform a COW transaction, make a PTE update atomic, invalidate any TLB,
prevent concurrent mutation, or supply HIA privilege/exception backends.
Passing this narrow test does not close Linux memory management. The
17 complete gates and all 422 syscall rows remain HOLD.
