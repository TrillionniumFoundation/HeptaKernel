# Native HIA ELF64 initial-stack suffix on physical QEMU PMM pages

The *unchanged* locked HIA Core v8 `selfhost_elf` machine-code object
`src/elf64_start_stack.hepta` is symbol-renamed and linked into an isolated
PC 32MiB / Q35 64MiB QEMU image. A deliberately non-HIA `boot.S`
observer first invokes the genuine HIA physical allocator and E820 gate,
retains the identity of a 4096-byte allocated page at 0x601000 and a
separate allocated canary at 0x602000, and fills the page with a known
full-word sentinel. HIA then receives exactly the original
`(40-byte request, 4096-byte page, 16-byte receipt)` ABI. A separate
physical-byte oracle compares 496 untouched prefix words, all 16 emitted
stack suffix words, both receipt fields, and the adjacent allocation canary.

Independent PC/Q35 negative experiments require malformed PHENT=64 to
return refusal 3 with **all 4096 physical bytes** and both receipt words
unchanged; a separately **native-HIA-compiled dishonest no-op** must fail
the physical-byte/receipt oracle despite returning success; and a
post-HIA physical output modification must defeat the exact-byte oracle.
Expected per-run markers, exit codes, original object and image hashes,
source hashes, command lines and full stdout/stderr are retained in
`build/elf64-stack-physical-qemu-report.json`. The original 8,501-case
host byte oracle, malicious controls and compiler byte identity remain
mandatory in `make test`/Foundation CI. The separate QEMU observer verifies
the original native bytes, not simulated HIA or assembler-embedded code.

This does **not** map the resulting stack in a user address space, execute
the entry in CPL3, authenticate the ELF file or physical ownership, implement
Linux `execve`, argv/envp, dynamic linking, credentials, stack guard pages,
ASLR, AT_RANDOM, SMP, UEFI or privileged HIA effects. The non-HIA
`boot.S` remains the only hardware bootstrap/observer and all 17 gates,
422 x86-64 syscall source rows and `inventory_complete=false` remain HOLD.
