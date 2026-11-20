# Full PMM bitmap integrity in genuine native HIA

The isolated `src/pmm_bitmap_integrity.hepta` checker performs a **complete**
scan of a caller-supplied 64-byte PMM header and all bitmap bits. The
24-byte request contains frozen little-endian base/count/reserved-prefix
metadata. The HIA Core v8 selfhost_elf backend generates its actual machine
code. It validates the header magic and frozen identity, physical geometry,
complete bitmap length, zero padding in header offsets 40–63, reserved-page
allocation, tail padding and the exact popcount-derived free count.

This stage is separate from `cow_frame_binding.hepta` because previous
attempts to combine the bitmap scan into that already-large function failed
on the pinned compiler. A passing, independent native component does **not**
mean the combined admission or COW transaction is already implemented.

The seeded Python oracle enumerates bits without using any HIA result, checks
input memory and canaries, and requires a separately compiled dishonest HIA
always-success control to disagree. The build repeats the native compilation
twice with an empty PATH and compares the object bytes. The Foundation job
retains the report alongside native objects.

Run `make test-pmm-bitmap-integrity` or `make test` with the pinned compiler.
No kernel privileges, firmware authentication, concurrency ordering, TLB
shootdown or complete Linux feature gate is claimed. This is a single-owner,
quiescent state consistency test only. The baseline and all 17 gates / 422
x86-64 syscalls remain unchanged.
