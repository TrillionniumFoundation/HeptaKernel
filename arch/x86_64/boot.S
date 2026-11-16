/* SPDX-License-Identifier: GPL-2.0-only
 * Non-HIA bootstrap and independent bare-metal test observer.
 * This bridge is deliberately GNU assembly: the pinned HIA profile does not
 * encode privilege transitions, control registers, port I/O or interrupt gates.
 * The allocator under test is the separately compiled HIA symbol f0.
 */
.set MB_HEADER_MAGIC, 0x1badb002
.set MB_HEADER_FLAGS, 0x00000003
.set MB_BOOT_MAGIC,   0x2badb002
.set PAGE_BYTES,      4096
.set STATE_BYTES,     8192
.set ARENA_MIN,       0x400000
.set ARENA_MAX,       0x800000
.set COM1,            0x3f8
.set DEBUG_EXIT,      0xf4

.section .multiboot,"a",@progbits
.balign 4
.long MB_HEADER_MAGIC
.long MB_HEADER_FLAGS
.long -(MB_HEADER_MAGIC + MB_HEADER_FLAGS)

.section .text.boot,"ax",@progbits
.code32
.global _start
.type _start,@function
_start:
    cli
    cld
    movl %eax, %esi                 /* preserve the Multiboot handoff */
    movl %ebx, %ebp
    lgdt gdt_descriptor
    ljmp $0x18, $protected_entry
protected_entry:
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    movw %ax, %fs
    movw %ax, %gs
    movl $stack_top, %esp
    xorl %eax, %eax
    movl $__bss_start, %edi
    movl $__bss_end, %ecx
    subl %edi, %ecx
    shrl $2, %ecx
    rep stosl
    movl %esi, boot_magic
    movl %ebp, boot_info
    call serial_init32

    /* Every precondition failure exits through the failure path. */
    cmpl $MB_BOOT_MAGIC, boot_magic
    jne fail32
    movl boot_info, %ebx
    testl %ebx, %ebx
    jz fail32
    cmpl $0x3ffff000, %ebx
    jae fail32
    testl $1, (%ebx)                /* mem_lower/mem_upper are present */
    jz fail32
    cmpl $7168, 8(%ebx)             /* only a preliminary lower bound */
    jb fail32
    cmpl $ARENA_MIN, %ebx           /* handoff info outside our probe arena */
    jae fail32
    testl $8, (%ebx)                /* no Multiboot modules in this fixture */
    jz no_modules32
    cmpl $0, 20(%ebx)
    jne fail32
no_modules32:
    call import_multiboot_map32
    movl $0x80000000, %eax
    cpuid
    cmpl $0x80000001, %eax
    jb fail32
    movl $0x80000001, %eax
    cpuid
    testl $0x20000000, %edx          /* long mode */
    jz fail32

    /* Mask both PICs; this fixture does not enable asynchronous interrupts. */
    movb $0xff, %al
    outb %al, $0x21
    outb %al, $0xa1

    /* Supervisor-only identity mapping of the first GiB, using 2 MiB pages. */
    movl $pdpt, %eax
    orl $3, %eax
    movl %eax, pml4
    movl $page_directory, %eax
    orl $3, %eax
    movl %eax, pdpt
    movl $page_directory, %edi
    movl $0x83, %eax                /* present, writable, huge page */
    movl $512, %ecx
1:
    movl %eax, (%edi)
    movl $0, 4(%edi)
    addl $0x200000, %eax
    addl $8, %edi
    loop 1b
    movl %cr4, %eax
    orl $0x620, %eax                /* PAE, OSFXSR, OSXMMEXCPT */
    movl %eax, %cr4
    movl $pml4, %eax
    movl %eax, %cr3
    movl $0xc0000080, %ecx          /* EFER */
    rdmsr
    orl $0x100, %eax                /* LME */
    wrmsr
    movl %cr0, %eax
    andl $0xfffffffb, %eax          /* clear EM */
    orl $0x80010003, %eax           /* PG, WP, PE, MP */
    movl %eax, %cr0
    ljmp $0x08, $long_entry

/* Multiboot v1 mmap variable records: size:u32 + base:u64 +
 * length:u64 + type:u32 + optional ext_attrs:u32. This explicit non-HIA
 * transport rejects unknown widths, overflow and omission. The native HIA
 * function, not this converter, decides whether the arena is usable.
 */
import_multiboot_map32:
    movl boot_info, %ebx
    testl $0x40, (%ebx)
    jz fail32
    movl 44(%ebx), %ecx
    testl %ecx, %ecx
    jz fail32
    movl 48(%ebx), %esi
    testl %esi, %esi
    jz fail32
    cmpl $0x3ffff000, %esi
    jae fail32
    movl %esi, %eax
    addl %ecx, %eax
    jc fail32
    cmpl $0x40000000, %eax
    jae fail32
    /* Source firmware records may not occupy the arena we intend to test. */
    cmpl $ARENA_MIN, %esi
    jae map_above_arena32
    cmpl $ARENA_MIN, %eax
    ja fail32
    jmp map_location_ok32
map_above_arena32:
    cmpl $ARENA_MAX, %esi
    jb fail32
map_location_ok32:
    movl %eax, mmap_end32
    movl $ARENA_MIN, e820_request
    movl $0, e820_request+4
    movl $1024, e820_request+8
    movl $0, e820_request+12
    movl $0, e820_request+20
    movl $e820_request+24, %edi
    xorl %edx, %edx
mmap_loop32:
    cmpl mmap_end32, %esi
    je mmap_done32
    ja fail32
    movl mmap_end32, %eax
    subl %esi, %eax
    cmpl $24, %eax
    jb fail32
    movl (%esi), %ecx
    cmpl $20, %ecx
    je mmap_size_ok32
    cmpl $24, %ecx
    jne fail32
mmap_size_ok32:
    subl $4, %eax
    cmpl %ecx, %eax
    jb fail32
    cmpl $128, %edx
    jae fail32
    movl 4(%esi), %eax
    movl %eax, 0(%edi)
    movl 8(%esi), %eax
    movl %eax, 4(%edi)
    movl 12(%esi), %eax
    movl %eax, 8(%edi)
    movl 16(%esi), %eax
    movl %eax, 12(%edi)
    movl 20(%esi), %eax
    movl %eax, 16(%edi)
    cmpl $24, %ecx
    jne legacy_attrs32
    movl 24(%esi), %eax
    jmp attrs_stored32
legacy_attrs32:
    movl $1, %eax
attrs_stored32:
    movl %eax, 20(%edi)
    leal 4(%esi,%ecx,1), %esi
    addl $24, %edi
    incl %edx
    jmp mmap_loop32
mmap_done32:
    testl %edx, %edx
    jz fail32
#if defined(HEPTAKERNEL_TEST_INJECT_RESERVED) || defined(HEPTAKERNEL_TEST_INJECT_NONVOLATILE)
    /* NEGATIVE CONTROLS ONLY. Preserve all real loader records, then
     * inject an enabled exclusion overlapping the first physical page.
     * ACPI extended attr bit 1 indicates nonvolatile memory even if
     * the E820 type is 1 (RAM); neither case may be used as scratch RAM.
     */
    cmpl $128, %edx
    jae fail32
    movl $ARENA_MIN, 0(%edi)
    movl $0, 4(%edi)
    movl $PAGE_BYTES, 8(%edi)
    movl $0, 12(%edi)
#ifdef HEPTAKERNEL_TEST_INJECT_NONVOLATILE
    movl $1, 16(%edi)
    movl $3, 20(%edi)
#else
    movl $2, 16(%edi)
    movl $1, 20(%edi)
#endif
    incl %edx
#endif
    movl %edx, e820_request+16
    ret

fail32:
    movl $message_fail32, %esi
    call puts32
    movl $0x11, %eax
    movw $DEBUG_EXIT, %dx
    outl %eax, %dx
2:
    cli
    hlt
    jmp 2b

serial_init32:
    movw $(COM1 + 1), %dx
    xorb %al, %al
    outb %al, %dx
    movw $(COM1 + 3), %dx
    movb $0x80, %al
    outb %al, %dx
    movw $COM1, %dx
    movb $1, %al
    outb %al, %dx
    movw $(COM1 + 1), %dx
    xorb %al, %al
    outb %al, %dx
    movw $(COM1 + 3), %dx
    movb $3, %al
    outb %al, %dx
    movw $(COM1 + 2), %dx
    movb $0xc7, %al
    outb %al, %dx
    movw $(COM1 + 4), %dx
    movb $0x0b, %al
    outb %al, %dx
    ret

puts32:
    pushal
3:
    lodsb
    testb %al, %al
    jz 6f
    pushl %eax
    movl $1000000, %ecx
    movw $(COM1 + 5), %dx
4:
    inb %dx, %al
    testb $0x20, %al
    jnz 5f
    loop 4b
    popl %eax
    jmp 6f                        /* bounded observer even if UART is absent */
5:
    popl %eax
    movw $COM1, %dx
    outb %al, %dx
    jmp 3b
6:
    popal
    ret

.code64
long_entry:
    movw $0x10, %ax
    movw %ax, %ds
    movw %ax, %es
    movw %ax, %ss
    xorw %ax, %ax
    movw %ax, %fs
    movw %ax, %gs
    leaq stack_top(%rip), %rsp
    xorq %rbp, %rbp
    cld

    /* Catch HIA bounds traps (#UD), #GP, #PF and other exception vectors.
     * No handler returns, so error-code and no-error-code frames share a stub.
     * There is no TSS/IST: this is a single-CPU fixture, not a general ISR layer.
     */
    leaq idt64(%rip), %rdi
    leaq exception64(%rip), %rax
    movl $256, %ecx
7:
    movw %ax, (%rdi)
    movw $0x08, 2(%rdi)
    movb $0, 4(%rdi)
    movb $0x8e, 5(%rdi)
    movq %rax, %rdx
    shrq $16, %rdx
    movw %dx, 6(%rdi)
    shrq $16, %rdx
    movl %edx, 8(%rdi)
    movl $0, 12(%rdi)
    addq $16, %rdi
    loop 7b
    lidt idt64_descriptor(%rip)

    /* Real Multiboot loader map, passed to the actual HIA-generated
     * E820 checker before any test physical frame is touched.
     */
    movq $-1, e820_reply(%rip)
    movq $-1, e820_reply+8(%rip)
    leaq e820_request(%rip), %rdi
    movq e820_request+16(%rip), %rsi
    imulq $24, %rsi, %rsi
    addq $24, %rsi
    leaq e820_reply(%rip), %rdx
    movl $16, %ecx
    leaq e820_unused(%rip), %r8
    movl $16, %r9d
    call e820_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, e820_reply(%rip)
    jne fail64
    cmpq $1024, e820_reply+8(%rip)
    jne fail64
    leaq message_map_pass(%rip), %rsi
    call puts64

    movabsq $0xa55aa55a5aa55aa5, %rax
    movq %rax, state_guard_before(%rip)
    movq %rax, state_guard_after(%rip)
    movq %rax, reply_guard_before(%rip)
    movq %rax, reply_guard_after(%rip)
    movq %rax, stack_guard(%rip)
    leaq boot_cases(%rip), %rax
    movq %rax, case_cursor(%rip)

case_loop:
    movq case_cursor(%rip), %rax
    leaq boot_cases_end(%rip), %rdx
    cmpq %rdx, %rax
    je cases_done
    ja fail64
    movq $-1, reply(%rip)
    movq $-1, reply+8(%rip)
    movq %rax, %rdi                /* request readbuf(ptr, 32) */
    movl $32, %esi
    leaq reply(%rip), %rdx         /* reply mutbuf(ptr, 16) */
    movl $16, %ecx
    leaq allocator_state(%rip), %r8
    movl $STATE_BYTES, %r9d        /* state mutbuf(ptr, 8192) */
    call f0                       /* actual upstream HIA-generated machine code */

    /* Observer reads the immutable fixture expectations, not a success flag
     * manufactured by the allocator. Both reply words and the ABI return count.
     */
    movq case_cursor(%rip), %r12
    movl %eax, %eax
    cmpq 32(%r12), %rax
    jne fail64
    movq reply(%rip), %rax
    cmpq 32(%r12), %rax
    jne fail64
    movq reply+8(%rip), %rax
    cmpq 40(%r12), %rax
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, state_guard_before(%rip)
    jne fail64
    cmpq %rax, state_guard_after(%rip)
    jne fail64
    cmpq %rax, reply_guard_before(%rip)
    jne fail64
    cmpq %rax, reply_guard_after(%rip)
    jne fail64
    cmpq %rax, stack_guard(%rip)
    jne fail64

    cmpq $0, reply(%rip)
    jne case_next
    cmpq $0, (%r12)               /* successful INIT establishes probe bounds */
    jne maybe_probe
    movq 8(%r12), %rax            /* page count */
    testq %rax, %rax
    jz fail64
    cmpq $1024, %rax
    ja fail64
    movq 16(%r12), %rdx           /* base physical address */
    testq $4095, %rdx
    jnz fail64
    cmpq $ARENA_MIN, %rdx
    jb fail64
    movq 24(%r12), %rcx           /* reserved prefix pages */
    cmpq %rax, %rcx
    ja fail64
    shlq $12, %rax
    addq %rdx, %rax
    jc fail64
    cmpq $ARENA_MAX, %rax
    ja fail64
    movq %rax, arena_end(%rip)
    shlq $12, %rcx
    addq %rdx, %rcx
    jc fail64
    movq %rcx, arena_first(%rip)
    movq $1, arena_ready(%rip)
    jmp case_next

maybe_probe:
    cmpq $1, (%r12)               /* ALLOC: one real physical page */
    je probe_single
    cmpq $4, (%r12)               /* ALLOC_RUN: every physical page */
    je probe_run
    cmpq $6, (%r12)               /* CLAIM_RUN: every exact physical page */
    jne case_next
    movq 16(%r12), %r14           /* exact-claim length is argument b */
    jmp probe_length
probe_run:
    movq 8(%r12), %r14            /* ALLOC_RUN length is argument a */
probe_length:
    testq %r14, %r14
    jz fail64
    cmpq $1024, %r14             /* bounded by fixture arena, before shifting */
    ja fail64
    jmp probe_bounds

probe_single:
    movq $1, %r14

probe_bounds:
    cmpq $1, arena_ready(%rip)
    jne fail64
    movq reply+8(%rip), %rax
    cmpq $6, (%r12)
    jne probe_address_ready
    movq 8(%r12), %rax            /* CLAIM_RUN uses explicit physical address */
probe_address_ready:
    testq $4095, %rax
    jnz fail64
    cmpq arena_first(%rip), %rax
    jb fail64
    movq arena_end(%rip), %rdx
    movq %r14, %rcx
    shlq $12, %rcx
    subq %rcx, %rdx
    jc fail64
    cmpq %rdx, %rax
    ja fail64
    movq %rax, %r13
probe_each_page:
    movabsq $0x4849414b45524e4c, %rdx
    movq %rdx, (%r13)
    notq %rdx
    movq %rdx, (PAGE_BYTES - 8)(%r13)
    cmpq %rdx, (PAGE_BYTES - 8)(%r13)
    jne fail64
    notq %rdx
    cmpq %rdx, (%r13)
    jne fail64
    movq $0, (%r13)
    movq $0, (PAGE_BYTES - 8)(%r13)
    incq physical_probes(%rip)
    addq $PAGE_BYTES, %r13
    decq %r14
    jnz probe_each_page

case_next:
    addq $48, case_cursor(%rip)
    incq case_index(%rip)
    jmp case_loop

cases_done:
    cmpq $0, case_index(%rip)
    je fail64
    cmpq $0, physical_probes(%rip)
    je fail64
    leaq message_pass(%rip), %rsi
    call puts64
    movl $0x10, %eax              /* QEMU exit code 33 */
    jmp debug_exit64

fail64:
    leaq emergency_stack_top(%rip), %rsp
    leaq message_fail64(%rip), %rsi
    call puts64
    movq case_index(%rip), %rax
    call hex64
    leaq message_newline(%rip), %rsi
    call puts64
    movl $0x11, %eax              /* QEMU exit code 35 */
    jmp debug_exit64

exception64:
    cli
    leaq emergency_stack_top(%rip), %rsp
    leaq message_exception(%rip), %rsi
    call puts64
    movl $0x11, %eax

debug_exit64:
    movw $DEBUG_EXIT, %dx
    outl %eax, %dx
8:
    cli
    hlt
    jmp 8b

/* COM1 output with bounded transmitter polling. */
puts64:
    pushq %rax
    pushq %rcx
    pushq %rdx
    pushq %rsi
9:
    lodsb
    testb %al, %al
    jz 12f
    pushq %rax
    movl $1000000, %ecx
    movw $(COM1 + 5), %dx
10:
    inb %dx, %al
    testb $0x20, %al
    jnz 11f
    loop 10b
    popq %rax
    jmp 12f
11:
    popq %rax
    movw $COM1, %dx
    outb %al, %dx
    jmp 9b
12:
    popq %rsi
    popq %rdx
    popq %rcx
    popq %rax
    ret

hex64:
    leaq hex_buffer+16(%rip), %rdi
    movb $0, (%rdi)
    movl $16, %ecx
    leaq hex_digits(%rip), %rsi
13:
    movq %rax, %rdx
    andl $15, %edx
    movb (%rsi,%rdx,1), %dl
    decq %rdi
    movb %dl, (%rdi)
    shrq $4, %rax
    loop 13b
    movq %rdi, %rsi
    jmp puts64

.section .rodata.boot,"a",@progbits
.balign 8
gdt:
    .quad 0
    .quad 0x00af9a000000ffff       /* selector 0x08: 64-bit supervisor code */
    .quad 0x00cf92000000ffff       /* selector 0x10: supervisor data */
    .quad 0x00cf9a000000ffff       /* selector 0x18: 32-bit supervisor code */
gdt_end:
gdt_descriptor:
    .word gdt_end - gdt - 1
    .long gdt
idt64_descriptor:
    .word 4095
    .quad idt64
message_map_pass:
    .asciz "HEPTAKERNEL HIA E820 VERIFIED\r\n"
message_pass:
    .asciz "HEPTAKERNEL HIA PMM PASS\r\n"
message_fail32:
    .asciz "HEPTAKERNEL BOOT FAIL: multiboot/cpu/memory\r\n"
message_fail64:
    .asciz "HEPTAKERNEL BOOT FAIL case=0x"
message_exception:
    .asciz "HEPTAKERNEL BOOT FAIL: exception\r\n"
message_newline:
    .asciz "\r\n"
hex_digits:
    .ascii "0123456789abcdef"
.balign 8
boot_cases:
    .incbin "build/boot-cases.bin"
boot_cases_end:
.if (boot_cases_end - boot_cases) == 0
.error "boot fixture table must not be empty"
.endif
.if ((boot_cases_end - boot_cases) % 48) != 0
.error "boot fixture table must consist of exact 48-byte records"
.endif

.section .bss.boot,"aw",@nobits
.balign 4096
pml4:             .skip 4096
pdpt:             .skip 4096
page_directory:   .skip 4096
idt64:            .skip 4096
.balign 16
state_guard_before: .skip 8
allocator_state:    .skip STATE_BYTES
state_guard_after:  .skip 8
reply_guard_before: .skip 8
reply:              .skip 16
reply_guard_after:  .skip 8
.balign 8
boot_magic:       .skip 4
boot_info:        .skip 4
mmap_end32:       .skip 4
.balign 8
e820_request:     .skip (24 + 128 * 24)
e820_reply:       .skip 16
e820_unused:      .skip 16
case_cursor:      .skip 8
case_index:       .skip 8
physical_probes:  .skip 8
arena_first:      .skip 8
arena_end:        .skip 8
arena_ready:      .skip 8
hex_buffer:       .skip 17
.balign 16
stack_guard:      .skip 16
stack_bottom:     .skip 262144
stack_top:
.balign 16
emergency_stack:  .skip 4096
emergency_stack_top:

.section .note.GNU-stack,"",@progbits
