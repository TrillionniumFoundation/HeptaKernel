# Native HIA physical arena / PMM state binding

`src/owner_binding.hepta` is a genuine HIA Core v8 `selfhost_elf` component built by the exact pinned upstream native self-hosting compiler and exported as a separate `f0`. The test-only linker renames that symbol to `owner_f0` without rewriting its machine instructions.

The caller supplies a **24-byte little-endian descriptor** `(physical_base, page_count, reserved_prefix_pages)`, a minimum **16-byte reply**, and an initialized mutable PMM state view. The function returns one `u32` matching the first reply word; its second reply word is the current free-frame count if status is zero, otherwise zero. A reply shorter than 16 bytes returns 1 with no output writes. A non-24-byte descriptor returns BAD_REQUEST=2. Invalid geometry returns INVALID=6; an absent, inconsistent or mismatched state header returns BAD_STATE=4.

The binding check requires a page-aligned base below 2^52, nonzero page count no larger than 65,536, reserved prefix not exceeding the number of pages, and a physical extent fully below 2^52. The state must hold at least 64+ceil(page_count/8) bytes. Its PMM magic, base, page count, and reserved prefix must equal the descriptor exactly; its free count must not exceed page_count-reserved_prefix. All 24 header padding bytes at offsets 40..63 must be zero. Successful matching leaves the entire PMM state unchanged.

An independent test initializes real PMM states via `src/kernel.hepta` before passing them to this separate native HIA module. It checks valid and invalid descriptors, first/last physical geometry, explicit zone identity mismatch, corrupted headers and padding bytes, short capabilities and state byte preservation. A deliberately dishonest separately compiled native HIA E820 object is used as a negative comparison, not as production code. `make test-owner-binding` runs this suite; `make test` requires it.

The QEMU PC/Q35 test-only handoff invokes this new HIA component on both initialized E820-admitted PMM states before allocating/reading their physical pages. The existing `arch/x86_64/boot.S` remains a non-HIA **test bridge** and the still-verified HIA E820/arena/PMM components are linked separately. Build evidence recompiles the HIA source under empty PATH and compares source object, shared-library text, renamed object text and all boot images, including negative images.

## Deliberate and critical boundaries

**Header binding is not complete state validation.** It does **not** recompute bitmap/free-count consistency, validate reserved bits in the bitmap, authenticate pointers, attest E820 provenance, or prevent two state views from aliasing the same physical memory. After binding, the existing PMM `state_valid()` remains mandatory for every mutable PMM operation. It does not atomically lock an arena, implement cross-zone transaction semantics or establish SMP safety. Firmware, virtual memory, interrupt entry, atomics, drivers, syscalls, and Linux compatibility are still open.

All 17 full-Linux acceptance gates and 422 x86-64 syscall obligations remain unchanged in `compatibility/coverage.json`. `make full-acceptance` must continue to exit 2 HOLD.
