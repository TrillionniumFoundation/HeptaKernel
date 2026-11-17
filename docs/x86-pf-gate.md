# Native HIA x86-64 page-fault record admission (isolated stage)

`src/x86_pf_gate.hepta` is HIA Core v8 `selfhost_elf` source, compiled by
the pinned upstream native compiler directly to ELF64 x86-64 machine code.
It validates a *captured* x86 page-fault record; it neither installs an IDT
nor executes privileged control-register or exception-return instructions.

## Wire format

`f0(request:readbuf, reply:mutbuf, unused:mutbuf) -> u32` requires exactly
72 request bytes, nine little-endian u64 words:

| Offset | Word |
| --- | --- |
| 0 | kind: 1=supervisor NX instruction fetch, 2=supervisor write-protect |
| 8 | hardware #PF error code |
| 16 | actual CR2 faulting linear address |
| 24 | hardware-saved RIP |
| 32 | caller-selected expected fault address |
| 40 | caller-selected expected fault RIP |
| 48 | observed leaf PTE (A/D bits may be set) |
| 56 | sampled CR0 |
| 64 | sampled EFER |

The address must be 4KiB aligned, equal to CR2 and to the PTE's physical
frame in this **identity-mapped fixture**. Expected RIP must be nonzero
and equal the actual saved RIP. The PTE must be present and supervisor-only.

For NX, the native program requires error=0x11, PTE.NX=1, EFER.NXE=1.
For WP, it requires error=0x3, PTE.RW=0 and CR0.WP=1.
It deliberately does not require any particular A/D bits.

The reply requires at least 16 bytes, status and value as little-endian
u64; success writes (0,kind). Refusal writes (status,0), with status 1
for too-short reply (no reply writes), 2 for malformed request, 6 for
invalid kind, 7 for mismatched captured facts, 8 for inactive CPU control
bits. The request and unused buffer must not be modified.

## Evidence and limitations

`make test-x86-pf-gate` compares genuine native HIA execution against an
independent Python oracle over deterministic adversarial, random and boundary
cases; guard bytes surround the request and reply. A deliberately dishonest
native HIA program must fail the same oracle. `make record-build` replays
empty-PATH native compilation and verifies the exact ELF object and loaded
shared-library .text bytes.

This initial stage is a standalone HIA gate, **not yet installed in the QEMU
#PF execution path**. Until that integration is separately tested, the
original assembly observer remains responsible for checking hardware faults.
Even after such integration, the exception stub and hardware register
sampling are still non-HIA and untrusted outside the test fixture. Upstream
HIA CRx, MSR, privilege, atomic, memory-order, exception entry and IRET
backend semantics are separate open requirements.

All 17 full Linux gates remain HOLD, the 422 syscall obligations unchanged.
