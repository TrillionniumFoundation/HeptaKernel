# Native HIA ELF64 initial stack suffix — isolated 2026-11-22 result

The genuine locked HIA Core v8 `selfhost_elf` compiler directly compiles
`src/elf64_start_stack.hepta` into x86-64 machine code. The implementation
only writes a 128-byte, 16-byte-aligned suffix into a caller-owned 4096-byte
page. Its initial x86-64 user stack has argc=0, argv=NULL, envp=NULL,
AT_PHDR, AT_PHENT=56, AT_PHNUM, AT_PAGESZ=4096, AT_ENTRY, AT_NULL, and
trailing alignment padding. The 40-byte immutable request contains the
page-base virtual address, entry, PHDR address, phentsize and phnum.
The 16-byte receipt is (initial user RSP,128), emitted last.

Status 1 rejects malformed request size, 2 rejects destination and receipt
sizes, 3 rejects low-canonical/address alignment, PHDR bound or ELF-header
geometry. All refusal paths leave both outputs byte-identical. User stack
bytes outside [3968,4096) remain untouched on success. Exact object/source
binding, two independent empty-PATH native builds, an independent Python
byte oracle, guard canaries, and a separately compiled dishonest HIA
always-success control are required in Foundation CI.

This does not authenticate ELF bytes or page ownership and does not
implement Linux execve, argv/envp strings, AT_RANDOM/AT_PLATFORM,
PT_INTERP, dynamic loader, real user address spaces, credentials, TLS,
ASLR, CPU execution or full auxiliary vector. `boot.S` remains non-HIA,
all 17 acceptance gates are HOLD, and the fixed 422 syscall source rows
are unchanged.
