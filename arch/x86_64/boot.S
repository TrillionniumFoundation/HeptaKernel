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
    testl $0x00100000, %edx          /* CPUID NX */
    jz fail32
    movl $0x80000000, %eax
    cpuid
    cmpl $0x80000008, %eax
    jb fail32
    movl $0x80000008, %eax
    cpuid
    andl $0xff, %eax                /* MAXPHYADDR */
    cmpl $32, %eax
    jb fail32
    cmpl $52, %eax
    ja fail32
    orl $0x100, %eax               /* observed width with active NXE */
    movl %eax, pte_caps

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
    orl $0x900, %eax                /* LME + NXE, after CPUID NX admission */
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
#if defined(HEPTAKERNEL_TEST_CR3_LIVE) || defined(HEPTAKERNEL_TEST_CR3_UNSAFE)
    /* Non-HIA isolated observer using original native HIA CR3 gate bytes. */
    jmp cr3_live_probe64
#endif
#if defined(HEPTAKERNEL_ROOT_LIVE) || defined(HEPTAKERNEL_ROOT_UNSAFE) || defined(HEPTAKERNEL_ROOT_SPOOF)
    jmp root_probe64
#endif

    /* Catch HIA bounds traps (#UD), #GP, #PF and other exception vectors.
     * No handler returns. Only the isolated #PF vector uses a hardware IST1.
     * Privileged TSS/LTR setup remains a temporary non-HIA bridge.
     */
    /* The temporary privileged bridge configures a real 64-bit TSS IST1.
     * GDT data is in identity-mapped RAM; all interrupts stay masked.
     * The live IDT gate itself, including IST bits, is generated by HIA.
     */
    /* Native HIA transaction provisions future CPL3 RSP0 and IST1
     * before the privileged LTR bridge; all old fields must match. */
    leaq stack_top(%rip), %rax
    movq %rax, tss_state_request(%rip)
    leaq ist_stack_top(%rip), %rax
    movq %rax, tss_state_request+8(%rip)
    movq tss64+4(%rip), %rax
    movq %rax, tss_state_request+16(%rip)
    movq tss64+36(%rip), %rax
    movq %rax, tss_state_request+24(%rip)
    movzwq tss64+102(%rip), %rax
    movq %rax, tss_state_request+32(%rip)
#ifdef HEPTAKERNEL_TEST_TSS_STATE_CONFLICT
    movq $1, tss_state_request+24(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_TSS_RSP0_CONFLICT
    movq $1, tss_state_request+16(%rip)
#endif
    movq $-1, tss_state_reply(%rip)
    movq $-1, tss_state_reply+8(%rip)
    leaq tss_state_request(%rip), %rdi
    movl $40, %esi
    leaq tss_state_reply(%rip), %rdx
    movl $16, %ecx
    leaq tss64(%rip), %r8
    movl $104, %r9d
    call tss_state_f0
#if defined(HEPTAKERNEL_TEST_TSS_STATE_CONFLICT) || defined(HEPTAKERNEL_TEST_TSS_RSP0_CONFLICT)
    cmpl $9, %eax
    jne fail64
    cmpq $9, tss_state_reply(%rip)
    jne fail64
    cmpq $0, tss64+4(%rip)
    jne fail64
    cmpq $0, tss64+36(%rip)
    jne fail64
    cmpw $0, tss64+102(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_TSS_RSP0_CONFLICT
    leaq message_tss_rsp0_stale(%rip), %rsi
#else
    leaq message_tss_state_stale(%rip), %rsi
#endif
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, tss_state_reply(%rip)
    jne fail64
    leaq stack_top(%rip), %rax
    cmpq %rax, tss64+4(%rip)
    jne fail64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, tss64+36(%rip)
    jne fail64
    cmpq %rax, tss_state_reply+8(%rip)
    jne fail64
    cmpw $104, tss64+102(%rip)
    jne fail64
    leaq message_tss_state_pass(%rip), %rsi
    call puts64
#endif
    /* Genuine HIA installs both CPL3 selectors on the active GDT before
     * any ring transition. LTR/LIDT/IRETQ are still non-HIA bridge code. */
    movq gdt+48(%rip), %rax
    movq %rax, user_gdt_request(%rip)
    movq gdt+56(%rip), %rax
    movq %rax, user_gdt_request+8(%rip)
#ifdef HEPTAKERNEL_TEST_USER_GDT_CONFLICT
    movq $1, user_gdt_request(%rip)
#endif
    movq $-1, user_gdt_reply(%rip)
    movq $-1, user_gdt_reply+8(%rip)
    leaq user_gdt_request(%rip), %rdi
    movl $16, %esi
    leaq user_gdt_reply(%rip), %rdx
    movl $16, %ecx
    leaq gdt(%rip), %r8
    movl $64, %r9d
    call user_gdt_f0
#ifdef HEPTAKERNEL_TEST_USER_GDT_CONFLICT
    cmpl $9, %eax
    jne fail64
    cmpq $9, user_gdt_reply(%rip)
    jne fail64
    cmpq $0, gdt+48(%rip)
    jne fail64
    cmpq $0, gdt+56(%rip)
    jne fail64
    leaq message_user_gdt_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, user_gdt_reply(%rip)
    jne fail64
    movabsq $0x00affa000000ffff, %rax
    cmpq %rax, gdt+48(%rip)
    jne fail64
    cmpq %rax, user_gdt_reply+8(%rip)
    jne fail64
    movabsq $0x00cff2000000ffff, %rax
    cmpq %rax, gdt+56(%rip)
    jne fail64
    leaq message_user_gdt_pass(%rip), %rsi
    call puts64
#endif
    /* Genuine native HIA also builds the system GDT TSS descriptor. */
    leaq tss64(%rip), %rax
    movq %rax, tss_gdt_request(%rip)
    movq $103, tss_gdt_request+8(%rip)
    movq gdt+32(%rip), %rax
    movq %rax, tss_gdt_request+16(%rip)
    movq gdt+40(%rip), %rax
    movq %rax, tss_gdt_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_TSS_GDT_CONFLICT
    movq $1, tss_gdt_request+16(%rip)
#endif
    movq $-1, tss_gdt_reply(%rip)
    movq $-1, tss_gdt_reply+8(%rip)
    leaq tss_gdt_request(%rip), %rdi
    movl $32, %esi
    leaq tss_gdt_reply(%rip), %rdx
    movl $16, %ecx
    leaq gdt(%rip), %r8
    movl $48, %r9d
    call tss_gdt_f0
#ifdef HEPTAKERNEL_TEST_TSS_GDT_CONFLICT
    cmpl $9, %eax
    jne fail64
    cmpq $9, tss_gdt_reply(%rip)
    jne fail64
    cmpq $0, gdt+32(%rip)
    jne fail64
    cmpq $0, gdt+40(%rip)
    jne fail64
    leaq message_tss_gdt_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, tss_gdt_reply(%rip)
    jne fail64
    movq tss_gdt_reply+8(%rip), %rax
    cmpq %rax, gdt+32(%rip)
    jne fail64
    movq tss_gdt_request(%rip), %rax
    shrq $32, %rax
    cmpq %rax, gdt+40(%rip)
    jne fail64
    cmpw $103, gdt+32(%rip)
    jne fail64
    cmpb $0x89, gdt+37(%rip)
    jne fail64
    leaq message_tss_gdt_pass(%rip), %rsi
    call puts64
#endif
    movw $0x20, %ax
    ltr %ax
    xorw %ax, %ax
    str %ax
    cmpw $0x20, %ax
    jne fail64

    /* HIA native Core builds all 256 IDT gates in the actual 4 KiB table.
     * Single owner with interrupts disabled; LIDT remains the assembly bridge. */
    xorq %r12, %r12
hia_idt_next64:
    movq %r12, idt_gate_request(%rip)
    leaq exception64(%rip), %rax
    movq %rax, idt_gate_request+8(%rip)
    movq $0, idt_gate_request+16(%rip)
    movq $0, idt_gate_request+24(%rip)
    movq $0, idt_gate_request+32(%rip) /* default IST0 */
#ifdef HEPTAKERNEL_TEST_IDT_CONFLICT
    /* The first gate must be refused when expected old bytes are stale. */
    cmpq $0, %r12
    jne fail64
    movq $1, idt_gate_request+16(%rip)
#endif
    movq $-1, idt_gate_reply(%rip)
    movq $-1, idt_gate_reply+8(%rip)
    leaq idt_gate_request(%rip), %rdi
    movl $40, %esi
    leaq idt_gate_reply(%rip), %rdx
    movl $16, %ecx
    leaq idt64(%rip), %r8
    movl $4096, %r9d
    call idt_gate_f0
#ifdef HEPTAKERNEL_TEST_IDT_CONFLICT
    cmpl $9, %eax
    jne fail64
    cmpq $9, idt_gate_reply(%rip)
    jne fail64
    cmpq $0, idt64(%rip)
    jne fail64
    cmpq $0, idt64+8(%rip)
    jne fail64
    leaq message_idt_stale_pass(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, idt_gate_reply(%rip)
    jne fail64
    movq %r12, %r13
    shlq $4, %r13
    leaq idt64(%rip), %r14
    addq %r13, %r14
    movq (%r14), %rax
    cmpq idt_gate_reply+8(%rip), %rax
    jne fail64
    movq idt_gate_request+8(%rip), %rax
    shrq $32, %rax
    cmpq %rax, 8(%r14)
    jne fail64
    cmpw $0x08, 2(%r14)
    jne fail64
    cmpb $0x8e, 5(%r14)
    jne fail64
    incq %r12
    cmpq $256, %r12
    jb hia_idt_next64
#if defined(HEPTAKERNEL_TEST_NX_FETCH) || defined(HEPTAKERNEL_TEST_NX_BYPASS) || defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS) || defined(HEPTAKERNEL_TEST_PT_REVOKE_FAULT) || defined(HEPTAKERNEL_TEST_PT_PROTECT_FAULT) || defined(HEPTAKERNEL_TEST_PT_NX_FAULT) || defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_COW_PTE_HW)
    /* HIA also owns updating the #PF descriptor, conditional on old bytes. */
    movq $14, idt_gate_request(%rip)
#ifdef HEPTAKERNEL_TEST_US_FAULT
    leaq us_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_COW_PTE_HW)
    leaq cow_pte_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_PT_NX_FAULT)
    leaq pt_nx_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_PT_PROTECT_FAULT)
    leaq pt_protect_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_PT_REVOKE_FAULT)
    leaq pt_revoke_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT)
    leaq pdpt_1g_unmap_page_fault64(%rip), %rax
#elif defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT)
    leaq pde_2m_unmap_page_fault64(%rip), %rax
#else
    leaq pte_page_fault64(%rip), %rax
#endif
    movq %rax, idt_gate_request+8(%rip)
    movq idt64+224(%rip), %rax
    movq %rax, idt_gate_request+16(%rip)
    movq idt64+232(%rip), %rax
    movq %rax, idt_gate_request+24(%rip)
    movq $1, idt_gate_request+32(%rip) /* real hardware IST1 for #PF */
    leaq idt_gate_request(%rip), %rdi
    movl $40, %esi
    leaq idt_gate_reply(%rip), %rdx
    movl $16, %ecx
    leaq idt64(%rip), %r8
    movl $4096, %r9d
    call idt_gate_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, idt_gate_reply(%rip)
    jne fail64
    movq idt64+224(%rip), %rax
    cmpq idt_gate_reply+8(%rip), %rax
    jne fail64
    movq idt_gate_request+8(%rip), %rax
    shrq $32, %rax
    cmpq %rax, idt64+232(%rip)
    jne fail64
    cmpb $1, idt64+228(%rip)       /* HIA emitted IST1 */
    jne fail64
#endif
    /* Test-only CPL3 #UD: real HIA builds vector 6 with IST0.
     * IRET/exception entry and ring3 selectors remain NON-HIA test bridge. */
#if defined(HEPTAKERNEL_TEST_RSP0_RING3) || defined(HEPTAKERNEL_TEST_RSP0_DECOY) || defined(HEPTAKERNEL_TEST_RING3_PDE_STALE) || defined(HEPTAKERNEL_TEST_RING3_UPPER_STALE) || defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS) || defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSRET_GDT_STALE) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    movq $6, idt_gate_request(%rip)
#if defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS)
    leaq us_ring3_fault64(%rip), %rax
#else
    leaq rsp0_ring3_fault64(%rip), %rax
#endif
    movq %rax, idt_gate_request+8(%rip)
    movq idt64+96(%rip), %rax
    movq %rax, idt_gate_request+16(%rip)
    movq idt64+104(%rip), %rax
    movq $0, idt_gate_request+32(%rip)
    leaq idt_gate_request(%rip), %rdi
    movl $40, %esi
    leaq idt_gate_reply(%rip), %rdx
    movl $16, %ecx
    leaq idt64(%rip), %r8
    movl $4096, %r9d
    call idt_gate_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, idt_gate_reply(%rip)
    jne fail64
    movq idt64+96(%rip), %rax
    cmpq idt_gate_reply+8(%rip), %rax
    jne fail64
    cmpb $0, idt64+100(%rip)
    jne fail64
    cmpb $0x8e, idt64+101(%rip)
    jne fail64
#endif
    /* Privileged LIDT is not yet expressible in the pinned HIA backend. */
    lidt idt64_descriptor(%rip)
    leaq message_idt_pass(%rip), %rsi
    call puts64
#endif

#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
    call discovery_choose64
#endif

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
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
    cmpq $DISCOVERY_PAGES, e820_reply+8(%rip)
#else
    cmpq $1024, e820_reply+8(%rip)
#endif
    jne fail64
    leaq message_map_pass(%rip), %rsi
    call puts64

    /* Check physical boot reservations with actual native HIA machine
     * code before routing or touching any frame in the test arena. */
    call reservation_admit64
    leaq message_reservation_pass(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
    jmp discovery_probe64
#endif
#if defined(HEPTAKERNEL_TEST_PMM_DUAL_HW)
    /* Isolated QEMU physical-RAM observation of the genuine HIA one-call
     * two-zone claim. The firmware observer and serial/port I/O are NON-HIA. */
    call dual_claim_hardware_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_HW) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_LIAR) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_RECHECK) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
    /* Terminal isolated experiment: genuine HIA PMM allocation, HIA offline
     * leaf construction, HIA frame admission, then NON-HIA PDE/CR3 observer. */
    call shadow_owner_hardware_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_PT_SHADOW_HW) || defined(HEPTAKERNEL_TEST_PT_SHADOW_STALE) || defined(HEPTAKERNEL_TEST_PT_SHADOW_LIAR) || defined(HEPTAKERNEL_TEST_PT_SHADOW_TAMPER)
    /* Isolated real MMU publication of a HIA-built, unpublished PTE page.
     * Parent PDE and CR3 remain explicitly NON-HIA observer instructions. */
    call pt_shadow_hardware_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_PT_PAIR_HW) || defined(HEPTAKERNEL_TEST_PT_PAIR_STALE) || defined(HEPTAKERNEL_TEST_PT_PAIR_LIAR)
    /* Terminal CPU-MMU experiment: actual HIA two-PTE writer. */
    call pt_pair_hardware_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_PDPT_1G_HW) || defined(HEPTAKERNEL_TEST_PDPT_1G_STALE) || defined(HEPTAKERNEL_TEST_PDPT_1G_DECOY) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS)
    /* Terminal single-owner HIA 1GiB PDPTE hardware experiment. */
    call pdpt_1g_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_STALE) || defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_BYPASS)
    /* A terminal real-MMU fixture, with native HIA removing PD[2]. */
    call pde_2m_unmap_exercise64
    jmp fail64
#endif
#if defined(HEPTAKERNEL_TEST_RSP0_RING3) || defined(HEPTAKERNEL_TEST_RSP0_DECOY) || defined(HEPTAKERNEL_TEST_RING3_PDE_STALE) || defined(HEPTAKERNEL_TEST_RING3_UPPER_STALE) || defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS) || defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSRET_GDT_STALE) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    /* ELF-stack CPL3 test must first materialize a native HIA PMM page. */
#ifndef HEPTAKERNEL_TEST_ELF_STACK_RING3
    call rsp0_ring3_exercise64
    jmp fail64
#endif
#endif
    call pte_live_exercise64
    leaq message_pte_pass(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_COW_PTE_HW
    /* Terminal CPU fault/IRET test of the ORIGINAL native HIA PTE switch. */
    call cow_pte_hardware_exercise64
    jmp fail64
#endif

    /* Genuine HIA multi-arena router, after the E820 admission gate.
     * Each read-only fixture includes independent expected return fields.
     * The non-HIA observer never trusts the HIA status by itself.
     */
    movabsq $0xa55aa55a5aa55aa5, %rax
    movq %rax, arena_guard_before(%rip)
    movq %rax, arena_guard_after(%rip)
    movq %rax, arena_unused(%rip)
    leaq arena_cases(%rip), %r13
    leaq arena_cases_end(%rip), %r14
arena_case_loop:
    cmpq %r14, %r13
    je arena_cases_done
    ja fail64
    movq $-1, arena_reply(%rip)
    movq $-1, arena_reply+8(%rip)
    movq %r13, %rdi
    movl $80, %esi
    leaq arena_reply(%rip), %rdx
    movl $16, %ecx
    leaq arena_unused(%rip), %r8
    movl $16, %r9d
    call arena_f0
    movl %eax, %eax
    cmpq 80(%r13), %rax
    jne fail64
    movq arena_reply(%rip), %rax
    cmpq 80(%r13), %rax
    jne fail64
    movq arena_reply+8(%rip), %rax
    cmpq 88(%r13), %rax
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, arena_unused(%rip)
    jne fail64
    cmpq %rax, arena_guard_before(%rip)
    jne fail64
    cmpq %rax, arena_guard_after(%rip)
    jne fail64
    addq $96, %r13
    jmp arena_case_loop
arena_cases_done:
    leaq message_router_pass(%rip), %rsi
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
    /* After the original single-zone oracle, exercise TWO independently
     * admitted HIA PMM states with physical ownership and alias probes. */
    call owner_exercise64
    leaq message_pass(%rip), %rsi
    call puts64
    movl $0x10, %eax              /* QEMU exit code 33 */
    jmp debug_exit64


/* The CPL0/CPUID/MSR hardware sampler is an explicit NON-HIA test observer.
 * The actual CR3 admission is the selfhost-compiled HIA cr3_probe_f0. */
#if defined(HEPTAKERNEL_TEST_CR3_LIVE) || defined(HEPTAKERNEL_TEST_CR3_UNSAFE)
cr3_live_probe64:
    movl $0x80000000, %eax
    xorl %ecx, %ecx
    cpuid
    cmpl $0x80000008, %eax
    jb fail64
    movl $0x80000008, %eax
    xorl %ecx, %ecx
    cpuid
    movzbl %al, %ebx                /* MAXPHYADDR from real CPUID */
    movq %cr3, %r12
    movq %cr0, %r13
    movq %cr4, %r14
    movl $0xc0000080, %ecx
    rdmsr
    movq %rdx, %r15
    shlq $32, %r15
    orq %rax, %r15                  /* actual EFER */

    movq %r12, %rdi
    movq %r13, %rsi
    movq %r14, %rdx
    movq %r15, %rcx
    movq %rbx, %r8
    call cr3_probe_f0
    testl %eax, %eax
    jne fail64
    movq %cr3, %rax
    cmpq %r12, %rax
    jne fail64

    /* Corrupt a COPY of sampled CR0.WP; do not modify live CR0. */
    movq %r12, %rdi
    movq %r13, %rsi
    btrq $16, %rsi
    movq %r14, %rdx
    movq %r15, %rcx
    movq %rbx, %r8
    call cr3_probe_f0
#ifdef HEPTAKERNEL_TEST_CR3_UNSAFE
    /* An unconditional-admission native HIA control must expose bypass. */
    testl %eax, %eax
    jne fail64
    leaq message_cr3_unsafe(%rip), %rsi
    call puts64
    movl $0x11, %eax                /* debug-exit 35 */
    jmp debug_exit64
#else
    cmpl $2, %eax
    jne fail64

    /* Corrupt a COPY of EFER.NXE, not the hardware MSR. */
    movq %r12, %rdi
    movq %r13, %rsi
    movq %r14, %rdx
    movq %r15, %rcx
    btrq $11, %rcx
    movq %rbx, %r8
    call cr3_probe_f0
    cmpl $2, %eax
    jne fail64

    /* Reserved CR3 bit 0 must be refused despite valid mode. */
    movq %r12, %rdi
    orq $1, %rdi
    movq %r13, %rsi
    movq %r14, %rdx
    movq %r15, %rcx
    movq %rbx, %r8
    call cr3_probe_f0
    cmpl $4, %eax
    jne fail64
    movq %cr3, %rax
    cmpq %r12, %rax
    jne fail64
    leaq message_cr3_live(%rip), %rsi
    call puts64
    movl $0x30, %eax                /* debug-exit 97 */
    jmp debug_exit64
#endif
#endif

/* CR3 and CPUID are read by a NON-HIA bootstrap observer. HIA scans RAM. */
#if defined(HEPTAKERNEL_ROOT_LIVE) || defined(HEPTAKERNEL_ROOT_UNSAFE) || defined(HEPTAKERNEL_ROOT_SPOOF)
root_probe64:
    movq %cr3, %r12
    leaq pml4(%rip), %r13
    cmpq %r13, %r12
    jne fail64                 /* binding to actual CPU root, not an address claim */
    movl $0x80000000, %eax
    xorl %ecx, %ecx
    cpuid
    cmpl $0x80000008, %eax
    jb fail64
    movl $0x80000008, %eax
    xorl %ecx, %ecx
    cpuid
    movzbl %al, %eax
    movq %r12, root_request(%rip)
    movq %rax, root_request+8(%rip)
    movq $0, root_request+16(%rip)
#ifndef HEPTAKERNEL_ROOT_UNSAFE
    movq $-1, root_reply(%rip)
    movq $-1, root_reply+8(%rip)
    leaq root_request(%rip), %rdi
    movl $24, %esi
    leaq root_reply(%rip), %rdx
    movl $16, %ecx
    movq %r12, %r8
    movl $4096, %r9d
    call root_native_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, root_reply(%rip)
    jne fail64
    cmpq $1, root_reply+8(%rip)
    jne fail64
#endif
    movq %cr3, %rax
    cmpq %r12, %rax
    jne fail64
    leaq pml4(%rip), %rsi
    leaq root_copy(%rip), %rdi
    movl $512, %ecx
    cld
    rep movsq
    movq (%r13), %rax
    cmpq %rax, root_copy(%rip)
    jne fail64
#ifdef HEPTAKERNEL_ROOT_SPOOF
    /* Valid substituted table is accepted by HIA byte policy only.
     * The non-HIA observer must notice it is NOT the CR3-rooted page. */
    xorq $0x1000, root_copy(%rip)
    movq $-1, root_reply(%rip)
    movq $-1, root_reply+8(%rip)
    leaq root_request(%rip), %rdi
    movl $24, %esi
    leaq root_reply(%rip), %rdx
    movl $16, %ecx
    leaq root_copy(%rip), %r8
    movl $4096, %r9d
    call root_native_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, root_reply(%rip)
    jne fail64
    cmpq $1, root_reply+8(%rip)
    jne fail64
    leaq root_copy(%rip), %rax
    cmpq %r12, %rax
    je fail64
    leaq root_spoof_message(%rip), %rsi
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#else
    orq $128, root_copy(%rip) /* reserved PML4 bit */
    movq $-1, root_reply(%rip)
    movq $-1, root_reply+8(%rip)
    leaq root_request(%rip), %rdi
    movl $24, %esi
    leaq root_reply(%rip), %rdx
    movl $16, %ecx
    leaq root_copy(%rip), %r8
    movl $4096, %r9d
    call root_native_f0
#ifdef HEPTAKERNEL_ROOT_UNSAFE
    testl %eax, %eax
    jne fail64
    leaq root_unsafe_message(%rip), %rsi
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#else
    cmpl $7, %eax
    jne fail64
    cmpq $7, root_reply(%rip)
    jne fail64
    cmpq $0, root_reply+8(%rip)
    jne fail64
    movq (%r13), %rax
    movq %rax, root_copy(%rip)
    andq $-2, root_copy(%rip) /* required slot absent in COPY */
    leaq root_request(%rip), %rdi
    movl $24, %esi
    leaq root_reply(%rip), %rdx
    movl $16, %ecx
    leaq root_copy(%rip), %r8
    movl $4096, %r9d
    call root_native_f0
    cmpl $5, %eax
    jne fail64
    cmpq $5, root_reply(%rip)
    jne fail64
    cmpq $0, root_reply+8(%rip)
    jne fail64
    movq %cr3, %rax
    cmpq %r12, %rax
    jne fail64
    testq $1, (%r13)
    jz fail64
    leaq root_live_message(%rip), %rsi
    call puts64
    movl $0x30, %eax
    jmp debug_exit64
#endif
#endif
#endif

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

/* Isolated hardware instruction-fetch #PF after authentic HIA RX->NX update. */
#ifdef HEPTAKERNEL_TEST_PT_NX_FAULT
pt_nx_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $0x4e585052, pt_nx_armed(%rip)
    jne exception64
    cmpq $0x11, (%rsp)             /* #PF P=1 W=0 U=0 I/D=1 */
    jne exception64
    cmpq $ARENA_MIN, 8(%rsp)       /* exact faulting fetch RIP */
    jne exception64
    cmpq $0x08, 16(%rsp)
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax
    jne exception64
    movq pt_nx_request+16(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne exception64
    cmpq $0, pt_nx_reply(%rip)
    jne exception64
    cmpq %rax, pt_nx_reply+8(%rip)
    jne exception64
    movl $0xc0000080, %ecx       /* real CPU EFER.NXE */
    rdmsr
    testl $0x800, %eax
    jz exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pt_nx_fault(%rip), %rsi
    call puts64
    movl $0x1d, %eax             /* QEMU debug exit 59 */
    jmp debug_exit64
#endif


/* Isolated real supervisor write-protection fault. HIA performs the exact-old
 * COW PTE remap INSIDE the hardware fault path. IDT, CR2, INVLPG and IRETQ
 * belong exclusively to this non-HIA test bridge. This is not a Linux VM. */
#ifdef HEPTAKERNEL_TEST_COW_PTE_HW
cow_pte_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $3, (%rsp)                 /* hardware #PF P=1, W=1, U=0 */
    jne exception64
    leaq cow_pte_store_insn(%rip), %rax
    cmpq %rax, 8(%rsp)              /* retry EXACT faulting store */
    jne exception64
    cmpq $0x08, 16(%rsp)
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax
    jne exception64
    cmpq $1, cow_pte_stage(%rip)
    je cow_pte_second_fault64
    cmpq $0, cow_pte_stage(%rip)
    jne exception64
    movq %rdi, cow_pte_saved_rdi(%rip)
    movq %r10, cow_pte_saved_r10(%rip)
    movq %rsp, cow_pte_fault_rsp(%rip)
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_cow_pte_fault_observed(%rip), %rsi
    call puts64
    /* A legitimate read-only fault must leave the original frame pristine. */
    movabsq $0x1122334455667788, %rax
    cmpq %rax, 0x601000
    jne fail64
    movabsq $0x8899aabbccddeeff, %rax
    cmpq %rax, 0x602000
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED
    /* Exact unmodified HIA cow_split native code runs INSIDE the first real
     * #PF before the independent HIA PTE swap. The physical allocation,
     * emergency stack, interrupt mask and subsequent INVLPG remain NON-HIA. */
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_STALE
    /* The caller's expected count is 2, but actual source count is 1. */
    movb $1, cow_integrated_state+18(%rip)
#endif
    movq $0x601000, %rdi
    movl $4096, %esi
    movq $0x602000, %rdx
    movl $4096, %ecx
    leaq cow_integrated_state(%rip), %r8
    movl $4096, %r9d
    call cow_split_f0
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_STALE
    cmpl $6, %eax
    jne fail64
#else
    testl %eax, %eax
    jne cow_integrated_reject64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_DECOY
    /* Test bridge changes ONE destination byte after genuine HIA copied. */
    xorq $8, 0x602008
#endif
#endif
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, cow_integrated_guard_before(%rip)
    jne cow_integrated_reject64
    cmpq %rax, cow_integrated_guard_after(%rip)
    jne cow_integrated_reject64
    movq $0x601000, %r8
    movq $0x602000, %r9
    movabsq $0x1122334455667788, %r10
    xorq %rcx, %rcx
cow_integrated_page_scan64:
    cmpq %r10, (%r8,%rcx,8)
    jne cow_integrated_reject64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_STALE
    movabsq $0x8899aabbccddeeff, %rax
#else
    movq %r10, %rax
#endif
    cmpq %rax, (%r9,%rcx,8)
    jne cow_integrated_reject64
    incq %rcx
    cmpq $512, %rcx
    jb cow_integrated_page_scan64
    /* Examine ALL 4096 state bytes, not the two returned counters alone. */
    leaq cow_integrated_state(%rip), %r8
    xorq %rcx, %rcx
cow_integrated_state_scan64:
    xorl %edx, %edx
    cmpq $0, %rcx
    je cow_integrated_expect_two64
    cmpq $2, %rcx
    je cow_integrated_expect_seventeen64
    cmpq $4, %rcx
    je cow_integrated_expect_two64
    cmpq $18, %rcx
    je cow_integrated_expect_one64
    cmpq $33, %rcx
    je cow_integrated_expect_dest64
    jmp cow_integrated_compare_byte64
cow_integrated_expect_two64:
    movb $2, %dl
    jmp cow_integrated_compare_byte64
cow_integrated_expect_seventeen64:
    movb $17, %dl
    jmp cow_integrated_compare_byte64
cow_integrated_expect_one64:
    movb $1, %dl
    jmp cow_integrated_compare_byte64
cow_integrated_expect_dest64:
#ifndef HEPTAKERNEL_TEST_COW_INTEGRATED_STALE
    movb $1, %dl
#endif
cow_integrated_compare_byte64:
    cmpb %dl, (%r8,%rcx,1)
    jne cow_integrated_reject64
    incq %rcx
    cmpq $4096, %rcx
    jb cow_integrated_state_scan64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_STALE
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_cow_integrated_stale(%rip), %rsi
    call puts64
    jmp fail64                 /* exact status-6, no-write rejection */
#else
    leaq message_cow_integrated_prepared(%rip), %rsi
    call puts64
#endif
#endif
    movq $-1, cow_pte_reply(%rip)
    movq $-1, cow_pte_reply+8(%rip)
#ifdef HEPTAKERNEL_TEST_COW_PTE_STALE
    /* Both fields remain a VALID transition, but expected-old is stale. */
    xorq $8, cow_pte_request+8(%rip)
    xorq $8, cow_pte_request+16(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT
    /* Late failure injection: mutate only the request's cache flag, preserving
     * a valid requested COW transformation but making expected-old stale.
     * The real PTE and original source frame remain untouched. */
    xorq $8, cow_pte_request+8(%rip)
    xorq $8, cow_pte_request+16(%rip)
#endif
    leaq cow_pte_request(%rip), %rdi
    movl $32, %esi
    leaq cow_pte_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call cow_pte_f0                 /* ORIGINAL selfhost-compiled HIA .text */
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT
    /* Real native HIA PTE switch must refuse late stale expected-old after
     * the earlier native HIA split already copied 4096 bytes and changed
     * counts. The bridge is responsible for recognizing this failure. */
    cmpl $9, %eax
    jne fail64
    cmpq $9, cow_pte_reply(%rip)
    jne fail64
    cmpq $0, cow_pte_reply+8(%rip)
    jne fail64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64

    /* Adapt the caller-owned header from pre-split to post-split counts:
     * source count 1, destination count 1. Nothing is published by the PTE. */
    movb $1, cow_integrated_state+4(%rip)
    movb $1, cow_integrated_state+5(%rip)
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED
    /* The readbuf points at the actual live CPU PTE, not a copied fixture.
     * The frozen original PTE is kept separately in the HIA state header. */
    movq cow_pte_old(%rip), %rax
    movq %rax, cow_integrated_state+8(%rip)
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_STALE
    /* A different but still well-formed frozen expected PTE must refuse. */
    xorq $8, cow_integrated_state+8(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_PUBLISHED
    /* Simulate a later publisher by changing the LIVE PTE cache attribute.
     * The actual CPU mapping is not accessed again before terminating. */
    xorq $8, page_table_4m(%rip)
#endif
#if defined(HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_STALE) || defined(HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_PUBLISHED)
    /* Independent full-byte state snapshot before an expected refusal. */
    leaq cow_integrated_state(%rip), %rsi
    leaq cow_integrated_guard_snapshot(%rip), %rdi
    movl $512, %ecx
    rep movsq
#endif
    leaq page_table_4m(%rip), %rdi  /* 8 bytes of real active page-table RAM */
    movl $8, %esi
#else
    leaq cow_integrated_state(%rip), %rdi  /* legacy empty request */
    xorq %rsi, %rsi
#endif
    movq $0x602000, %rdx
    movl $4096, %ecx
    leaq cow_integrated_state(%rip), %r8
    movl $4096, %r9d
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED
    call cow_abort_pte_guarded_f0        /* genuine original HIA Core v8 */
#else
    call cow_abort_f0                    /* original legacy HIA cleanup */
#endif
#if defined(HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_STALE) || defined(HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_PUBLISHED)
    cmpl $8, %eax                       /* exact PTE mismatch refusal */
    jne cow_integrated_abort_reject64
    leaq cow_integrated_state(%rip), %rsi
    leaq cow_integrated_guard_snapshot(%rip), %rdi
    movl $512, %ecx
    repe cmpsq                          /* all 4096 state bytes untouched */
    jne cow_integrated_abort_reject64
    movq $0x601000, %rsi
    movq $0x602000, %rdi
    movl $512, %ecx
    repe cmpsq                          /* copied page NOT cleared on refusal */
    jne cow_integrated_abort_reject64
    movq cow_pte_old(%rip), %rax
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_PUBLISHED
    xorq $8, %rax
#endif
    cmpq %rax, page_table_4m(%rip)      /* verify real PTE was not rewritten */
    jne cow_integrated_abort_reject64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, cow_integrated_guard_before(%rip)
    jne cow_integrated_abort_reject64
    cmpq %rax, cow_integrated_guard_after(%rip)
    jne cow_integrated_abort_reject64
    leaq message_cow_integrated_guard_refused(%rip), %rsi
    call puts64
    jmp fail64                           /* required negative control exit 35 */
#else
    testl %eax, %eax
    jne cow_integrated_abort_reject64
#endif
    movabsq $0x1122334455667788, %r10
    movq $0x601000, %r8
    movq $0x602000, %r9
    xorq %rcx, %rcx
cow_integrated_abort_pages64:
    cmpq %r10, (%r8,%rcx,8)
    jne cow_integrated_abort_reject64
    cmpq $0, (%r9,%rcx,8)               /* all private frame bytes zero */
    jne cow_integrated_abort_reject64
    incq %rcx
    cmpq $512, %rcx
    jb cow_integrated_abort_pages64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, cow_integrated_guard_before(%rip)
    jne cow_integrated_abort_reject64
    cmpq %rax, cow_integrated_guard_after(%rip)
    jne cow_integrated_abort_reject64
    leaq cow_integrated_state(%rip), %r8
    xorq %rcx, %rcx
cow_integrated_abort_table64:
    xorl %edx, %edx
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED
    cmpq $8, %rcx
    jb cow_integrated_abort_header_checked
    cmpq $16, %rcx
    jae cow_integrated_abort_header_checked
    /* A genuine HIA abort must preserve every byte of the frozen PTE. */
    leaq cow_pte_old(%rip), %r11
    movb -8(%r11,%rcx,1), %dl
    jmp cow_integrated_abort_compare
cow_integrated_abort_header_checked:
#endif
    cmpq $0, %rcx
    je cow_integrated_abort_slot2
    cmpq $2, %rcx
    je cow_integrated_abort_slot17
    cmpq $4, %rcx
    je cow_integrated_abort_one
    cmpq $5, %rcx
    je cow_integrated_abort_one
    cmpq $18, %rcx
    je cow_integrated_abort_slot2
    jmp cow_integrated_abort_compare
cow_integrated_abort_slot2:
    movb $2, %dl
    jmp cow_integrated_abort_compare
cow_integrated_abort_slot17:
    movb $17, %dl
    jmp cow_integrated_abort_compare
cow_integrated_abort_one:
    movb $1, %dl
cow_integrated_abort_compare:
    cmpb %dl, (%r8,%rcx,1)             /* entire 4096-byte table oracle */
    jne cow_integrated_abort_reject64
    incq %rcx
    cmpq $4096, %rcx
    jb cow_integrated_abort_table64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne cow_integrated_abort_reject64

#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_RECYCLE
    /* Actual HIA PMM owns both E820-admitted frames; a successful guarded
     * abort must precede physical release. Privilege and quiescent ownership
     * remain NON-HIA test-bridge assumptions, not kernel implementation. */
    cmpq $14, owner_b_state+32(%rip)
    jne cow_integrated_abort_reject64
    cmpb $7, owner_b_state+64(%rip)
    jne cow_integrated_abort_reject64
    movq $-1, owner_alloc_reply(%rip)
    movq $-1, owner_alloc_reply+8(%rip)
    leaq owner_cow_free_target(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0                          /* locked native HIA PMM free_page */
    testl %eax, %eax
    jne cow_integrated_abort_reject64
    cmpq $0, owner_alloc_reply(%rip)
    jne cow_integrated_abort_reject64
    cmpq $0, owner_alloc_reply+8(%rip)
    jne cow_integrated_abort_reject64
    cmpq $15, owner_b_state+32(%rip)
    jne cow_integrated_abort_reject64
    cmpb $3, owner_b_state+64(%rip)
    jne cow_integrated_abort_reject64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne cow_integrated_abort_reject64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED_RECYCLE_DOUBLE
    /* Native HIA must reject double free, preserving all PMM bytes. */
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    rep movsq
    movq $-1, owner_alloc_reply(%rip)
    movq $-1, owner_alloc_reply+8(%rip)
    leaq owner_cow_free_target(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0
    cmpl $7, %eax
    jne cow_integrated_abort_reject64
    cmpq $7, owner_alloc_reply(%rip)
    jne cow_integrated_abort_reject64
    cmpq $0, owner_alloc_reply+8(%rip)
    jne cow_integrated_abort_reject64
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
    jne cow_integrated_abort_reject64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne cow_integrated_abort_reject64
    /* Verify the actual physical contents again AFTER native HIA PMM
     * processing; a successful allocator reply cannot certify memory. */
    movq $0x601000, %rdi
    movabsq $0x1122334455667788, %rax
    movl $512, %ecx
    repe scasq
    jne cow_integrated_abort_reject64
    movq $0x602000, %rdi
    xorq %rax, %rax
    movl $512, %ecx
    repe scasq
    jne cow_integrated_abort_reject64
    leaq message_cow_pmm_double_free(%rip), %rsi
    call puts64
    jmp fail64
#else
    /* Exact physical frame is reissued; all PMM bytes match the saved
     * post-initial-allocation image, which is independent of return codes. */
    movq $-1, owner_alloc_reply(%rip)
    movq $-1, owner_alloc_reply+8(%rip)
    leaq owner_cow_reallocate(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0                          /* locked native HIA PMM allocate_page */
    testl %eax, %eax
    jne cow_integrated_abort_reject64
    cmpq $0, owner_alloc_reply(%rip)
    jne cow_integrated_abort_reject64
    cmpq $0x602000, owner_alloc_reply+8(%rip)
    jne cow_integrated_abort_reject64
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
    jne cow_integrated_abort_reject64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne cow_integrated_abort_reject64
    /* Verify the actual physical contents again AFTER native HIA PMM
     * processing; a successful allocator reply cannot certify memory. */
    movq $0x601000, %rdi
    movabsq $0x1122334455667788, %rax
    movl $512, %ecx
    repe scasq
    jne cow_integrated_abort_reject64
    movq $0x602000, %rdi
    xorq %rax, %rax
    movl $512, %ecx
    repe scasq
    jne cow_integrated_abort_reject64
    leaq message_cow_pmm_reissued(%rip), %rsi
    call puts64
#endif
#endif
    leaq message_cow_integrated_aborted(%rip), %rsi
    call puts64
    jmp fail64                           /* expected status 35 after abort */
cow_integrated_abort_reject64:
    leaq message_cow_integrated_abort_rejected(%rip), %rsi
    call puts64
    jmp fail64
#else
#ifdef HEPTAKERNEL_TEST_COW_PTE_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, cow_pte_reply(%rip)
    jne fail64
    cmpq $0, cow_pte_reply+8(%rip)
    jne fail64
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    movabsq $0x1122334455667788, %rax
    cmpq %rax, 0x601000
    jne fail64
    movabsq $0x8899aabbccddeeff, %rax
    cmpq %rax, 0x602000
    jne fail64
    leaq message_cow_pte_stale(%rip), %rsi
    call puts64
    jmp fail64                    /* expected rejection, exit 35 */
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, cow_pte_reply(%rip)
    jne cow_pte_dishonest64
    movq cow_pte_request+16(%rip), %rax
    cmpq %rax, cow_pte_reply+8(%rip)
    jne cow_pte_dishonest64
    cmpq %rax, page_table_4m(%rip)
    jne cow_pte_dishonest64
    movq $1, cow_pte_stage(%rip)
#ifdef HEPTAKERNEL_TEST_COW_PTE_BYPASS
    /* Test-only adversarial restoration after HIA's successful commit. */
    movq cow_pte_old(%rip), %rax
    movq %rax, page_table_4m(%rip)
#endif
    movq $ARENA_MIN, %rax
    invlpg (%rax)                 /* explicitly NON-HIA privileged bridge */
    movq cow_pte_saved_rdi(%rip), %rdi
    movq cow_pte_saved_r10(%rip), %r10
    movq cow_pte_fault_rsp(%rip), %rsp
    addq $8, %rsp                 /* skip CPU #PF error code */
    iretq                         /* retry identical store with new mapping */
    jmp fail64
#endif
#endif /* HEPTAKERNEL_TEST_COW_INTEGRATED_ABORT */
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED
cow_integrated_reject64:
    leaq message_cow_integrated_rejected(%rip), %rsi
    call puts64
    jmp fail64
#endif
cow_pte_dishonest64:
    leaq message_cow_pte_dishonest(%rip), %rsi
    call puts64
    jmp fail64
cow_pte_second_fault64:
#ifdef HEPTAKERNEL_TEST_COW_PTE_BYPASS
    movq cow_pte_old(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_cow_pte_bypass(%rip), %rsi
    call puts64
    movl $0x2f, %eax              /* QEMU exit 95, retry fault enforced */
    jmp debug_exit64
#else
    jmp exception64
#endif
#endif

/* Independent MMU observer for a real native HIA RW->RO downgrade.
 * CPU exception entry, CR2 and INVLPG remain non-HIA boot bridge. */
#ifdef HEPTAKERNEL_TEST_US_FAULT
/* CPL3 fetch must hardware-fault on supervisor PTE after genuine HIA U/S
 * revocation. IST1 and CR2/IRET remain independently observed in assembly. */
us_page_fault64:
    cli
    cmpq $1, us_stage(%rip)
    jne exception64
    leaq ist_stack_top(%rip), %rdx
    leaq -48(%rdx), %rax           /* error code and CPL3 five-word frame */
    cmpq %rax, %rsp
    jne exception64
    cmpq $0x15, (%rsp)            /* P=1,U=1,I/D=1, W=0 */
    jne exception64
    cmpq $ARENA_MIN, 8(%rsp)
    jne exception64
    cmpq $0x33, 16(%rsp)
    jne exception64
    cmpq $0x602000, 32(%rsp)
    jne exception64
    cmpq $0x3b, 40(%rsp)
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax
    jne exception64
    movq us_request+16(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne exception64
    cmpq $0, us_reply(%rip)
    jne exception64
    cmpq %rax, us_reply+8(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_us_fault(%rip), %rsi
    call puts64
    movl $0x21, %eax              /* QEMU exit 67 */
    jmp debug_exit64
#endif

#ifdef HEPTAKERNEL_TEST_PT_PROTECT_FAULT
pt_protect_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $0x50524f54, pt_protect_armed(%rip)
    jne exception64
    cmpq $3, (%rsp)              /* #PF: P=1, W=1, U=0 */
    jne exception64
    leaq pt_protect_store_insn(%rip), %rax
    cmpq %rax, 8(%rsp)            /* exact faulting RIP */
    jne exception64
    cmpq $0x08, 16(%rsp)          /* CPL0 CS */
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax
    jne exception64
    movq pt_protect_request+16(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne exception64
    cmpq $0, pt_protect_reply(%rip)
    jne exception64
    cmpq %rax, pt_protect_reply+8(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pt_protect_fault(%rip), %rsi
    call puts64
    movl $0x1b, %eax             /* QEMU exit 55 */
    jmp debug_exit64
#endif

/* The x86 CPU faults after native HIA clears the actual 4MiB huge PDE.
 * IDT/IST1, CR2, and INVLPG remain non-HIA observation bridges. */
#ifdef HEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT
pde_2m_unmap_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $0x324d554e, pde_2m_unmap_armed(%rip)
    jne exception64
    cmpq $0, (%rsp)                 /* #PF P=0 W=0 U=0 */
    jne exception64
    leaq pde_2m_unmap_fault_load64(%rip), %rax
    cmpq %rax, 8(%rsp)              /* precise faulting RIP */
    jne exception64
    cmpq $0x08, 16(%rsp)            /* CPL0 selector */
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax          /* exact removed 2MiB identity leaf */
    jne exception64
    cmpq $0, page_directory+16(%rip)
    jne exception64
    cmpq $0, pde_2m_reply(%rip)
    jne exception64
    cmpq $0, pde_2m_reply+8(%rip)
    jne exception64
    movq pde_2m_unmap_old(%rip), %rax
    testq $0x20, %rax              /* CPU A-bit captured before unmap */
    jz exception64
    cmpq %rax, pde_2m_request+8(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pde_2m_unmap_fault(%rip), %rsi
    call puts64
    movl $0x2d, %eax              /* debug-exit 91 */
    jmp debug_exit64
#endif

/* Genuine HIA writes zero to a live 1GiB PDPTE. The non-HIA IDT,
 * CR2, IST1 and INVLPG observer checks the resulting real CPU #PF. */
#ifdef HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT
pdpt_1g_unmap_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $0x3147554e, pdpt_1g_unmap_armed(%rip)
    jne exception64
    cmpq $0, (%rsp)                 /* #PF P=0 W=0 U=0 (read) */
    jne exception64
    leaq pdpt_1g_unmap_fault_load64(%rip), %rax
    cmpq %rax, 8(%rsp)              /* exact faulting instruction */
    jne exception64
    cmpq $0x08, 16(%rsp)            /* supervisor code selector */
    jne exception64
    movq %cr2, %rax
    leaq message_idt_pass(%rip), %rdx
    leaq 0x40000000(%rdx), %r8
    cmpq %r8, %rax                 /* exact 1GiB alias fault address */
    jne exception64
    cmpq $0, pdpt+8(%rip)          /* HIA removed precisely the live leaf */
    jne exception64
    cmpq $0, pdpt_1g_reply(%rip)
    jne exception64
    cmpq $0, pdpt_1g_reply+8(%rip)
    jne exception64
    movq pdpt_1g_unmap_old(%rip), %rax
    testq $0x20, %rax              /* hardware set Accessed before removal */
    jz exception64
    cmpq %rax, pdpt_1g_request+8(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pdpt_1g_unmap_fault(%rip), %rsi
    call puts64
    movl $0x2a, %eax               /* debug-exit 85 */
    jmp debug_exit64
#endif

/* Isolated hardware observation after genuine native HIA clears live PTE.
 * INVLPG/CR2/exception entry remain expressly non-HIA boot bridge. */
#ifdef HEPTAKERNEL_TEST_PT_REVOKE_FAULT
pt_revoke_page_fault64:
    cli
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
    cmpq $0x52564f4b, pt_revoke_armed(%rip)
    jne exception64
    cmpq $0, (%rsp)                  /* #PF P=0, W/R=0, U/S=0 */
    jne exception64
    leaq pt_revoke_load_insn(%rip), %rax
    cmpq %rax, 8(%rsp)               /* exact faulting RIP */
    jne exception64
    cmpq $0x08, 16(%rsp)             /* CPL0 CS */
    jne exception64
    movq %cr2, %rax
    cmpq $ARENA_MIN, %rax
    jne exception64
    cmpq $0, page_table_4m(%rip)
    jne exception64
    cmpq $0, pt_revoke_reply(%rip)
    jne exception64
    cmpq $0, pt_revoke_reply+8(%rip)
    jne exception64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pt_revoke_fault(%rip), %rsi
    call puts64
    movl $0x19, %eax                 /* debug exit 51 */
    jmp debug_exit64
#endif

#if defined(HEPTAKERNEL_TEST_NX_FETCH) || defined(HEPTAKERNEL_TEST_NX_BYPASS) || defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS)
pte_page_fault64:
    cli
    /* CPU must have switched to TSS.IST1 before entering this handler.
     * The saved error/RIP frame is still at the current IST stack pointer. */
    leaq ist_stack_base(%rip), %rax
    cmpq %rax, %rsp
    jbe exception64
    leaq ist_stack_top(%rip), %rax
    cmpq %rax, %rsp
    jae exception64
#ifdef HEPTAKERNEL_TEST_NX_FETCH
    /* The bridge remains the CPU exception entry; policy is native HIA.
     * Only an armed test is admitted to this isolated terminal path. */
    cmpq $0x4e584650, pte_nx_armed(%rip)
    jne exception64
    movq $1, pf_request(%rip)       /* kind 1: supervisor NX fetch */
    movq $ARENA_MIN, pf_request+32(%rip)
    movq $ARENA_MIN, pf_request+40(%rip)
#elif defined(HEPTAKERNEL_TEST_WP_STORE)
    cmpq $0x5750524f, pte_wp_armed(%rip)
    jne exception64
    movq $2, pf_request(%rip)       /* kind 2: supervisor CR0.WP */
    movq $ARENA_MIN, pf_request+32(%rip)
    leaq wp_store_insn(%rip), %rax
    movq %rax, pf_request+40(%rip)
#else
    /* Bypass images must execute; generic fault is never a success. */
    jmp exception64
#endif
    /* Capture the genuine #PF error, CR2, RIP, active PTE, CR0 and EFER.
     * Native HIA compares them against distinct expected values. */
    movq (%rsp), %rax
    movq %rax, pf_request+8(%rip)
    movq %cr2, %rax
    movq %rax, pf_request+16(%rip)
    movq 8(%rsp), %rax
    movq %rax, pf_request+24(%rip)
    movq page_table_4m(%rip), %rax
    movq %rax, pf_request+48(%rip)
    movq %cr0, %rax
    movq %rax, pf_request+56(%rip)
    movl $0xc0000080, %ecx        /* IA32_EFER */
    rdmsr
    shlq $32, %rdx
    orq %rdx, %rax
    movq %rax, pf_request+64(%rip)
#ifdef HEPTAKERNEL_TEST_PF_RECORD_CORRUPT
    /* Hardware fault stays genuine; the bridge injects one false error bit
     * to demonstrate the independent HIA classifier refuses a bad record. */
    xorq $1, pf_request+8(%rip)
#endif
    movabsq $0xa55aa55a5aa55aa5, %r10
    movq %r10, pf_guard_before(%rip)
    movq %r10, pf_guard_after(%rip)
    movq %r10, pf_unused(%rip)
    movq %r10, pf_unused+8(%rip)
    movq $-1, pf_reply(%rip)
    movq $-1, pf_reply+8(%rip)
    /* We do not return to a faulting context. Use an aligned isolated
     * emergency stack for the SysV HIA native call. */
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq pf_request(%rip), %rdi
    movl $72, %esi
    leaq pf_reply(%rip), %rdx
    movl $16, %ecx
    leaq pf_unused(%rip), %r8
    movl $16, %r9d
    call pf_gate_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, pf_reply(%rip)
    jne fail64
    movq pf_request(%rip), %rax
    cmpq %rax, pf_reply+8(%rip)
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, pf_guard_before(%rip)
    jne fail64
    cmpq %rax, pf_guard_after(%rip)
    jne fail64
    cmpq %rax, pf_unused(%rip)
    jne fail64
    cmpq %rax, pf_unused+8(%rip)
    jne fail64
    leaq message_ist_verified(%rip), %rsi
    call puts64
    leaq message_pf_admission_pass(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_NX_FETCH
    leaq message_nx_fault_pass(%rip), %rsi
    call puts64
    movl $0x12, %eax              /* QEMU exit 37 */
#else
    leaq message_wp_fault_pass(%rip), %rsi
    call puts64
    movl $0x14, %eax              /* QEMU exit 41 */
#endif
    jmp debug_exit64
#endif


#if defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_STALE) || defined(HEPTAKERNEL_TEST_PDE_2M_UNMAP_BYPASS)
/* The boot bridge made PD[2] present as the 4..6MiB identity huge page.
 * The memory map/reservation verifier ran before this fixture touched RAM.
 * Only the HIA Core v8 native pde_2m_f0 may clear this entry. */
pde_2m_unmap_exercise64:
    cmpq $0x400083, page_directory+16(%rip)
    jne fail64
    movq $ARENA_MIN, %r8
    movabsq $0x486961324d506167, %r10
    movq %r10, (%r8)               /* admitted test-only physical sentinel */
    cmpq %r10, (%r8)               /* warm actual hardware mapping and A/D */
    jne fail64
    movq page_directory+16(%rip), %rax
    testq $0x20, %rax
    jz fail64
    movq %rax, pde_2m_unmap_old(%rip)
    movq $2, pde_2m_request(%rip)
    movq %rax, pde_2m_request+8(%rip)
    movq $0, pde_2m_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pde_2m_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_PDE_2M_UNMAP_STALE
    xorq $8, pde_2m_request+8(%rip) /* valid PWT bit; wrong expected old */
#endif
    leaq message_pde_2m_unmap_warmed(%rip), %rsi
    call puts64
    movq $-1, pde_2m_reply(%rip)
    movq $-1, pde_2m_reply+8(%rip)
    leaq pde_2m_request(%rip), %rdi
    movl $32, %esi
    leaq pde_2m_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_directory(%rip), %r8
    movl $4096, %r9d
    call pde_2m_f0                /* genuine selfhost HIA machine code */
#ifdef HEPTAKERNEL_TEST_PDE_2M_UNMAP_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pde_2m_reply(%rip)
    jne fail64
    cmpq $0, pde_2m_reply+8(%rip)
    jne fail64
    movq pde_2m_unmap_old(%rip), %rax
    cmpq %rax, page_directory+16(%rip)
    jne fail64
    movq $ARENA_MIN, %r8
    movabsq $0x486961324d506167, %r10
    cmpq %r10, (%r8)             /* unchanged hardware mapping is still live */
    jne fail64
    leaq message_pde_2m_unmap_stale(%rip), %rsi
    call puts64
    movl $0x2e, %eax             /* debug-exit 93 */
    jmp debug_exit64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pde_2m_reply(%rip)
    jne fail64
    cmpq $0, pde_2m_reply+8(%rip)
    jne fail64
    cmpq $0, page_directory+16(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PDE_2M_UNMAP_BYPASS
    movq pde_2m_unmap_old(%rip), %rax
    movq %rax, page_directory+16(%rip) /* malicious NON-HIA regrant */
#endif
    movq $ARENA_MIN, %r8
    invlpg (%r8)                 /* explicitly NON-HIA hardware TLB bridge */
#ifdef HEPTAKERNEL_TEST_PDE_2M_UNMAP_BYPASS
    movabsq $0x486961324d506167, %r10
    cmpq %r10, (%r8)
    jne fail64
    leaq message_pde_2m_unmap_bypass(%rip), %rsi
    call puts64
    movl $0x2f, %eax             /* debug-exit 95 */
    jmp debug_exit64
#else
    movq $0x324d554e, pde_2m_unmap_armed(%rip)
pde_2m_unmap_fault_load64:
    movq (%r8), %rax             /* precise non-present read #PF required */
    jmp fail64
#endif
#endif
#endif

#if defined(HEPTAKERNEL_TEST_PDPT_1G_HW) || defined(HEPTAKERNEL_TEST_PDPT_1G_STALE) || defined(HEPTAKERNEL_TEST_PDPT_1G_DECOY) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS)
/* Non-HIA CPL0 observer for a real HIA Core v8 1GiB PDPTE writer.
 * HIA writes pdpt[1]; CPUID, CR3 flush and MMU alias load remain explicit
 * assembler test bridges. VA [1GiB, 2GiB) aliases physical [0, 1GiB).
 * Only a known low-RAM code/data word is read, never unadmitted RAM. */
pdpt_1g_exercise64:
    cmpq $0, pdpt+8(%rip)
    jne fail64
    movl $0x80000000, %eax
    cpuid
    cmpl $0x80000001, %eax
    jb fail64
    movl $0x80000001, %eax
    cpuid
    testl $0x04000000, %edx         /* architectural PDPE1GB */
    jz fail64
    movq $1, pdpt_1g_request(%rip)   /* slot 1: 1GiB virtual alias */
    movq $0, pdpt_1g_request+8(%rip)
    movq $0x81, pdpt_1g_request+16(%rip) /* 1GiB RX, phys=0, P|PS */
    movl pte_caps(%rip), %eax        /* observed MAXPHYADDR and active NXE */
    orl $0x400, %eax                /* CPUID PDPE1GB observed above */
    movq %rax, pdpt_1g_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_PDPT_1G_STALE
    movq $1, pdpt_1g_request+8(%rip) /* wrong expected-old; not a live bit */
#endif
    movq $-1, pdpt_1g_reply(%rip)
    movq $-1, pdpt_1g_reply+8(%rip)
    leaq pdpt_1g_request(%rip), %rdi
    movl $32, %esi
    leaq pdpt_1g_reply(%rip), %rdx
    movl $16, %ecx
    leaq pdpt(%rip), %r8
    movl $4096, %r9d
    call pdpt_1g_f0
#ifdef HEPTAKERNEL_TEST_PDPT_1G_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pdpt_1g_reply(%rip)
    jne fail64
    cmpq $0, pdpt_1g_reply+8(%rip)
    jne fail64
    cmpq $0, pdpt+8(%rip)          /* no write on stale-old refusal */
    jne fail64
    leaq message_pdpt_1g_stale(%rip), %rsi
    call puts64
    movl $0x29, %eax               /* debug-exit 83 */
    jmp debug_exit64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pdpt_1g_reply(%rip)
    jne fail64
    cmpq $0x81, pdpt_1g_reply+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PDPT_1G_DECOY
    btrq $0, pdpt+8(%rip)          /* deliberate non-HIA post-write decoy */
#endif
    cmpq $0x81, pdpt+8(%rip)
    je pdpt_1g_readback_ok64
#ifdef HEPTAKERNEL_TEST_PDPT_1G_DECOY
    leaq message_pdpt_1g_decoy(%rip), %rsi
    call puts64
#endif
    jmp fail64
pdpt_1g_readback_ok64:
    movq %cr3, %rax               /* explicit NON-HIA TLB invalidation */
    movq %rax, %cr3
    leaq message_idt_pass(%rip), %rdx
    leaq 0x40000000(%rdx), %r8    /* hardware 1GiB virtual alias */
    movq (%rdx), %rax
    cmpq (%r8), %rax              /* compare two independently addressed words */
    jne fail64
    movq 8(%rdx), %rax
    cmpq 8(%r8), %rax
    jne fail64
    testq $0x20, pdpt+8(%rip)      /* CPU set Accessed during actual MMU walk */
    jz fail64
#if defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE) || defined(HEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS)
    leaq message_pdpt_1g_warmed(%rip), %rsi
    call puts64
    /* Reuse the same native HIA object to remove the hardware-accessed leaf.
     * A fresh expected-old is essential: CPU A-bit updates are real writes. */
    movq pdpt+8(%rip), %rax
    movq %rax, pdpt_1g_unmap_old(%rip)
    movq %rax, pdpt_1g_request+8(%rip)
    movq $0, pdpt_1g_request+16(%rip)
#ifdef HEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE
    xorq $8, pdpt_1g_request+8(%rip) /* legal but stale PWT value */
#endif
    movq $-1, pdpt_1g_reply(%rip)
    movq $-1, pdpt_1g_reply+8(%rip)
    leaq pdpt_1g_request(%rip), %rdi
    movl $32, %esi
    leaq pdpt_1g_reply(%rip), %rdx
    movl $16, %ecx
    leaq pdpt(%rip), %r8
    movl $4096, %r9d
    call pdpt_1g_f0
#ifdef HEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pdpt_1g_reply(%rip)
    jne fail64
    cmpq $0, pdpt_1g_reply+8(%rip)
    jne fail64
    movq pdpt_1g_unmap_old(%rip), %rax
    cmpq %rax, pdpt+8(%rip)
    jne fail64
    /* Refusal must preserve the actual warmed hardware alias. */
    leaq message_idt_pass(%rip), %rdx
    leaq 0x40000000(%rdx), %r8
    movq (%rdx), %rax
    cmpq (%r8), %rax
    jne fail64
    leaq message_pdpt_1g_unmap_stale(%rip), %rsi
    call puts64
    movl $0x2b, %eax               /* debug-exit 87 */
    jmp debug_exit64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pdpt_1g_reply(%rip)
    jne fail64
    cmpq $0, pdpt_1g_reply+8(%rip)
    jne fail64
    cmpq $0, pdpt+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS
    /* Hostile bridge restores the mapping after genuine HIA removal. */
    movq pdpt_1g_unmap_old(%rip), %rax
    movq %rax, pdpt+8(%rip)
#endif
    leaq message_idt_pass(%rip), %rdx
    leaq 0x40000000(%rdx), %r8
    invlpg (%r8)                   /* explicitly NON-HIA TLB invalidation */
#ifdef HEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS
    movq (%rdx), %rax
    cmpq (%r8), %rax               /* bypass must still execute, no false #PF */
    jne fail64
    leaq message_pdpt_1g_unmap_bypass(%rip), %rsi
    call puts64
    movl $0x2c, %eax               /* debug-exit 89 */
    jmp debug_exit64
#else
    movq $0x3147554e, pdpt_1g_unmap_armed(%rip)
pdpt_1g_unmap_fault_load64:
    movq (%r8), %rax               /* CPU must report a non-present #PF */
    jmp fail64
#endif
#endif
#else
    leaq message_pdpt_1g_hw(%rip), %rsi
    call puts64
    movl $0x28, %eax              /* debug-exit 81 */
    jmp debug_exit64
#endif
#endif
#endif

#if defined(HEPTAKERNEL_TEST_RSP0_RING3) || defined(HEPTAKERNEL_TEST_RSP0_DECOY) || defined(HEPTAKERNEL_TEST_RING3_PDE_STALE) || defined(HEPTAKERNEL_TEST_RING3_UPPER_STALE) || defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS) || defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSRET_GDT_STALE) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
/* Test-only NON-HIA CPL3 harness for native HIA-configured TSS and IDT.
 * E820/reservation already admitted both physical test regions. The 4MiB
 * huge page is user RX; 6MiB is user RW/NX. Kernel pages remain U/S=0.
 * Nothing here is a purported HIA privilege/backend implementation. */
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
/* Clearly non-HIA, position-independent fixture code copied to actual
 * native HIA AT_ENTRY. The CPU reads HIA-populated CPL3 stack memory. */
elf_stack_ring3_user_bytes:
    movq 0(%rsp), %rax
    movq 32(%rsp), %rdx
    movq 96(%rsp), %r8
elf_stack_ring3_user_trap:
    ud2
elf_stack_ring3_user_end:
#endif
rsp0_ring3_exercise64:
#if defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSRET_GDT_STALE) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    /* Only genuine native HIA installs 0x40 user code. The previously
     * HIA-installed 0x38 data and 0x30 IRET code remain unchanged.
     * MSR and SYSRET instructions are expressly NON-HIA test bridge. */
    movq gdt+64(%rip), %rax
    movq %rax, sysret_gdt_request(%rip)
    movq gdt+56(%rip), %rax
    movq %rax, sysret_gdt_request+8(%rip)
#ifdef HEPTAKERNEL_TEST_SYSRET_GDT_STALE
    movq $1, sysret_gdt_request(%rip)
#endif
    movq $-1, sysret_gdt_reply(%rip)
    movq $-1, sysret_gdt_reply+8(%rip)
    leaq sysret_gdt_request(%rip), %rdi
    movl $16, %esi
    leaq sysret_gdt_reply(%rip), %rdx
    movl $16, %ecx
    leaq gdt(%rip), %r8
    movl $72, %r9d
    call sysret_gdt_f0
#ifdef HEPTAKERNEL_TEST_SYSRET_GDT_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, sysret_gdt_reply(%rip)
    jne fail64
    cmpq $0, sysret_gdt_reply+8(%rip)
    jne fail64
    cmpq $0, gdt+64(%rip)
    jne fail64
    movabsq $0x00cff2000000ffff, %rax
    cmpq %rax, gdt+56(%rip)
    jne fail64
    leaq message_sysret_gdt_stale(%rip), %rsi
    call puts64
    jmp fail64                 /* refused BEFORE SYSRETQ */
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, sysret_gdt_reply(%rip)
    jne fail64
    movabsq $0x00affa000000ffff, %rax
    cmpq %rax, sysret_gdt_reply+8(%rip)
    jne fail64
    cmpq %rax, gdt+64(%rip)
    jne fail64
    cmpq %rax, gdt+48(%rip)
    jne fail64
    movabsq $0x00cff2000000ffff, %rax
    cmpq %rax, gdt+56(%rip)
    jne fail64
    leaq message_sysret_gdt(%rip), %rsi
    call puts64
#endif
#endif
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
    leaq elf_stack_ring3_user_bytes(%rip), %rsi
    movq $0x401000, %rdi
    movl $(elf_stack_ring3_user_end-elf_stack_ring3_user_bytes), %ecx
    rep movsb
#else
    movq $ARENA_MIN, %rax
#if defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    movl $0x0b0f050f, (%rax)         /* real SYSCALL then deliberate UD2 */
#else
    movw $0x0b0f, (%rax)             /* fixture: UD2 at 0x400000 */
#endif
#endif
    /* Native HIA owns parent U/S and 2 MiB leaf PDE updates.
     * CR3, hardware exception entry and IRETQ remain NON-HIA.
     * 0x400000 is user RX; 0x600000 is user RW/NX, with PS=1. */
    /* Quiescent exclusive-owner HIA upper-table grant and physical readback. */
    movq $0, upper_user_request(%rip)
    movq pml4(%rip), %rax
    movq %rax, upper_user_request+8(%rip)
    movl pte_caps(%rip), %eax
    andl $255, %eax
    movq %rax, upper_user_request+16(%rip)
#ifdef HEPTAKERNEL_TEST_RING3_UPPER_STALE
    xorq $32, upper_user_request+8(%rip) /* legal Accessed bit but stale old */
#endif
    leaq upper_user_request(%rip), %rdi
    movl $24, %esi
    leaq upper_user_reply(%rip), %rdx
    movl $16, %ecx
    leaq pml4(%rip), %r8
    movl $4096, %r9d
    call upper_user_f0
#ifdef HEPTAKERNEL_TEST_RING3_UPPER_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, upper_user_reply(%rip)
    jne fail64
    cmpq $0, upper_user_reply+8(%rip)
    jne fail64
    movq upper_user_request+8(%rip), %rax
    xorq $32, %rax
    cmpq %rax, pml4(%rip)
    jne fail64
    testq $4, pml4(%rip)
    jnz fail64
    testq $4, pdpt(%rip)
    jnz fail64
    leaq message_upper_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, upper_user_reply(%rip)
    jne fail64
    movq upper_user_reply+8(%rip), %rax
    cmpq %rax, pml4(%rip)
    jne fail64
    testq $4, %rax
    jz fail64
    movq $0, upper_user_request(%rip)
    movq pdpt(%rip), %rax
    movq %rax, upper_user_request+8(%rip)
    leaq upper_user_request(%rip), %rdi
    movl $24, %esi
    leaq upper_user_reply(%rip), %rdx
    movl $16, %ecx
    leaq pdpt(%rip), %r8
    movl $4096, %r9d
    call upper_user_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, upper_user_reply(%rip)
    jne fail64
    movq upper_user_reply+8(%rip), %rax
    cmpq %rax, pdpt(%rip)
    jne fail64
    testq $4, %rax
    jz fail64
    leaq message_upper_pass(%rip), %rsi
    call puts64
#endif
    movq $2, pde_2m_request(%rip)
    movq page_directory+16(%rip), %rax
    movq %rax, pde_2m_request+8(%rip)
    movq $0x400085, pde_2m_request+16(%rip)
    movl pte_caps(%rip), %eax        /* 32-bit cap field: zero-extend before 64-bit HIA request */
    movq %rax, pde_2m_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_RING3_PDE_STALE
    xorq $1, pde_2m_request+8(%rip)
#endif
    leaq pde_2m_request(%rip), %rdi
    movl $32, %esi
    leaq pde_2m_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_directory(%rip), %r8
    movl $4096, %r9d
    call pde_2m_f0
#ifdef HEPTAKERNEL_TEST_RING3_PDE_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pde_2m_reply(%rip)
    jne fail64
    cmpq $0, pde_2m_reply+8(%rip)
    jne fail64
    movq pde_2m_request+8(%rip), %rax
    xorq $1, %rax                  /* reconstruct original PDE; A bit may be set */
    cmpq %rax, page_directory+16(%rip)
    jne fail64
    cmpq $0x600083, page_directory+24(%rip)
    jne fail64
    leaq message_pde_2m_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pde_2m_reply(%rip)
    jne fail64
    cmpq $0x400085, pde_2m_reply+8(%rip)
    jne fail64
    cmpq $0x400085, page_directory+16(%rip)
    jne fail64
    movq $3, pde_2m_request(%rip)
    movq page_directory+24(%rip), %rax
    movq %rax, pde_2m_request+8(%rip)
    movabsq $0x8000000000600087, %rax
    movq %rax, pde_2m_request+16(%rip)
    leaq pde_2m_request(%rip), %rdi
    movl $32, %esi
    leaq pde_2m_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_directory(%rip), %r8
    movl $4096, %r9d
    call pde_2m_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, pde_2m_reply(%rip)
    jne fail64
    movabsq $0x8000000000600087, %rax
    cmpq %rax, pde_2m_reply+8(%rip)
    jne fail64
    cmpq %rax, page_directory+24(%rip)
    jne fail64
    leaq message_pde_2m_pass(%rip), %rsi
    call puts64
#if defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS)
    /* Native HIA installs a user/RX 4KiB leaf; the parent pointer,
     * CR3 and privilege state remain the non-HIA test-only bridge. */
    movq $0, pt_commit_request(%rip)
    movq $0, pt_commit_request+8(%rip)
    movq $0x400005, pt_commit_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_commit_request+24(%rip)
    leaq pt_commit_request(%rip), %rdi
    movl $32, %esi
    leaq pt_commit_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_commit_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_commit_reply(%rip)
    jne fail64
    cmpq $0x400005, pt_commit_reply+8(%rip)
    jne fail64
    cmpq $0x400005, page_table_4m(%rip)
    jne fail64
    leaq page_table_4m(%rip), %rax
    orq $7, %rax                    /* present/RW/user upper entry */
    movq %rax, page_directory+16(%rip)
    leaq message_pt_commit_pass(%rip), %rsi
    call puts64
#endif
#if defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    /* NON-HIA high-half supervisor-only alias of pinned low 1 GiB. */
    cmpq $0, pml4+2048(%rip)
    jne fail64
    leaq pdpt(%rip), %rax
    orq $3, %rax
    movq %rax, pml4+2048(%rip)
#endif
    movq %cr3, %rax
    movq %rax, %cr3
    leaq stack_top(%rip), %rax
    cmpq %rax, tss64+4(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_RSP0_DECOY
    /* Mutation after native HIA validation: separate real hardware stack. */
    leaq rsp0_decoy_stack_top(%rip), %rax
    movq %rax, tss64+4(%rip)
#endif
#if defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    /* Real HIA native preflight, then NON-HIA MSR and ring-transition bridge.
     * This is not a Linux syscall handler or an HIA privileged backend. */
    movq $ARENA_MIN, %rdi
    movq $0x602000, %rsi
#ifdef HEPTAKERNEL_TEST_SYSRET_RFLAGS_BIT3
    movq $0x20a, %rdx      /* genuine reserved RFLAGS bit 3 */
#else
    movq $0x202, %rdx
#endif
    call sysret_admit_f0
#ifdef HEPTAKERNEL_TEST_SYSRET_RFLAGS_BIT3
    cmpl $3, %eax
    jne fail64
    leaq message_sysret_rflags_bit3(%rip), %rsi
    call puts64
    jmp fail64             /* refuse before WRMSR or SYSRETQ */
#else
    testl %eax, %eax
    jne fail64
#endif
    movl $0xc0000081, %ecx       /* IA32_STAR */
    xorl %eax, %eax
    movl $0x00300008, %edx      /* upper32: user base 0x30, kernel CS 0x08 */
    wrmsr
    movl $0xc0000080, %ecx       /* IA32_EFER */
    rdmsr
    orl $1, %eax                /* SCE */
    wrmsr
    movl $0xc0000084, %ecx       /* IA32_FMASK */
#if defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    movl $0x47700, %eax
#else
    movl $0x200, %eax
#endif
    xorl %edx, %edx
    wrmsr
#if defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
    /* Hardware RDMSR readback admitted by genuine pinned native HIA.
     * LSTAR mapping and privilege operations are still NON-HIA. */
    leaq syscall_kernel_entry64(%rip), %rdi
    movabsq $0xffff800000000000, %r8
    addq %r8, %rdi
    movq %rdi, syscall_expected_lstar(%rip)
    movl $0xc0000082, %ecx
    movq %rdi, %rax
    movq %rdi, %rdx
    shrq $32, %rdx
    wrmsr
    movl $0xc0000082, %ecx
    rdmsr
    shlq $32, %rdx
    orq %rdx, %rax
    cmpq syscall_expected_lstar(%rip), %rax
    jne fail64
    movq %rax, %rdi
    movl $0xc0000081, %ecx
    rdmsr
    shlq $32, %rdx
    orq %rdx, %rax
    movabsq $0x0030000800000000, %r8
    cmpq %r8, %rax
    jne fail64
    movq %rax, %rsi
    movl $0xc0000084, %ecx
    rdmsr
    shlq $32, %rdx
    orq %rdx, %rax
    cmpq $0x47700, %rax
    jne fail64
    movq %rax, %r8
    movl $0xc0000080, %ecx
    rdmsr
    shlq $32, %rdx
    orq %rdx, %rax
    movq %rax, %rcx
    movq %r8, %rdx
#ifdef HEPTAKERNEL_TEST_SYSCALL_MSR_STALE
    xorq $1, %rsi                 /* false supplied STAR */
#endif
    call syscall_msr_admit_f0
#ifdef HEPTAKERNEL_TEST_SYSCALL_MSR_STALE
    cmpl $2, %eax
    jne fail64
    leaq message_syscall_msr_stale(%rip), %rsi
    call puts64
    jmp fail64                    /* must refuse before SYSCALL */
#else
    testl %eax, %eax
    jne fail64
    leaq message_syscall_msr_pass(%rip), %rsi
    call puts64
#endif
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP
    /* Detect any CPL0 push to the user stack before the switch. */
    movabsq $0x735441434b475541, %rax
    movq %rax, 0x601ff8
#endif
    movq $0x602000, %rsp        /* fixture user stack, never a kernel stack */
    movq $ARENA_MIN, %rcx       /* HIA-admitted RIP */
    movq $0x202, %r11           /* HIA-admitted RFLAGS */
#ifdef HEPTAKERNEL_TEST_SYSCALL_ONE_TASK
#ifdef HEPTAKERNEL_TEST_SYSCALL_NR_UNKNOWN
    movl $1024, %eax           /* unsupported syscall -> -ENOSYS */
#else
    movl $39, %eax             /* x86-64 getpid syscall, NOT fixture magic */
#endif
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW
    movl $186, %eax            /* actual Linux x86-64 gettid, worker record */
#endif
    sysretq                     /* NON-HIA, actual hardware CPL0 -> CPL3 */
    jmp fail64
#else
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
    /* Genuine HIA scalar policy, not an IRETQ instruction backend.
     * A rejected writable-stack RIP must never reach privileged IRETQ. */
#ifdef HEPTAKERNEL_TEST_ELF_STACK_IRET_STALE
    movq $0x601000, %rdi
#else
    movq $0x401000, %rdi
#endif
    movq $0x601f80, %rsi
#ifdef HEPTAKERNEL_TEST_ELF_STACK_IRET_RFLAGS_BIT3
    movq $0xa, %rdx          /* genuine reserved RFLAGS bit 3 set */
#else
    movq $0x2, %rdx
#endif
    movq $0x33, %rcx
    movq $0x3b, %r8
    call iret_user_admit
#ifdef HEPTAKERNEL_TEST_ELF_STACK_IRET_STALE
    cmpl $5, %eax
    jne fail64
    leaq message_elf_stack_iret_stale(%rip), %rsi
    call puts64
    jmp fail64                 /* explicit negative, no hardware IRETQ */
#elif defined(HEPTAKERNEL_TEST_ELF_STACK_IRET_RFLAGS_BIT3)
    cmpl $4, %eax
    jne fail64
    leaq message_elf_stack_iret_reserved_bit3(%rip), %rsi
    call puts64
    jmp fail64                 /* reserved flag refused before NON-HIA IRETQ */
#else
    testl %eax, %eax
    jne fail64
#endif
    pushq $0x3b
    pushq $0x601f80                 /* native HIA stack receipt -> user RSP */
    pushq $0x2
    pushq $0x33
    pushq $0x401000                 /* equals actual HIA AT_ENTRY */
#else
    pushq $0x3b                     /* CPL3 SS */
    pushq $0x602000                 /* CPL3 NX stack */
    pushq $0x2                      /* IF masked */
    pushq $0x33                     /* CPL3 64-bit CS */
    pushq $ARENA_MIN                /* user-mode #UD */
#endif
    iretq                           /* test-only NON-HIA transition */
    jmp fail64
#endif
#endif /* not the deliberately stale HIA huge PDE refusal */

rsp0_ring3_fault64:
    cli
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
    /* Compare actual ring3 GPR results before the observer clobbers them. */
    cmpq $0, %rax
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3_DECOY
    cmpq $0x400041, %rdx      /* post-HIA mutation must reach CPL3 CPU */
#else
    cmpq $0x400040, %rdx
#endif
    jne fail64
    cmpq $0x401000, %r8
    jne fail64
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_ONE_TASK
    /* CPU preserved user RAX across SYSRETQ and UD2; verify BEFORE %ax
     * segment read destroys its low half. No stored-only check can pass. */
#ifdef HEPTAKERNEL_TEST_SYSCALL_NR_UNKNOWN
    movq $-38, %rdx
#else
    movq $4242, %rdx
#endif
    cmpq %rdx, %rax
    jne fail64
    cmpq %rdx, syscall_result(%rip)
    jne fail64
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW
#if defined(HEPTAKERNEL_TEST_SYSCALL_TASK_BAD_LEADER) || defined(HEPTAKERNEL_TEST_SYSCALL_LIFE_RETIRE)
    movq $-3, %rdx            /* missing task -> -ESRCH */
#else
    movq $4243, %rdx          /* worker TID differs from thread-group ID */
#endif
    cmpq %rdx, %rax          /* actual CPL3 RAX before any segment probe */
    jne fail64
    cmpq %rdx, syscall_result(%rip)
    jne fail64
#endif
    /* Hardware CPL3->CPL0 #UD must save 5 qwords on TSS.RSP0, no IST. */
    movw %cs, %ax
    cmpw $0x08, %ax
    jne fail64
#ifdef HEPTAKERNEL_TEST_RSP0_DECOY
    leaq rsp0_decoy_stack_top(%rip), %rdx
#else
    leaq stack_top(%rip), %rdx
#endif
    cmpq %rdx, tss64+4(%rip)
    jne fail64
    leaq -40(%rdx), %rax
    cmpq %rax, %rsp
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
    cmpq $(0x401000+elf_stack_ring3_user_trap-elf_stack_ring3_user_bytes), 0(%rsp)
#elif defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP)
    cmpq $(ARENA_MIN+2), 0(%rsp)
    movabsq $0x735441434b475541, %rax
    cmpq %rax, 0x601ff8
    jne fail64
#else
    cmpq $ARENA_MIN, 0(%rsp)
#endif
    jne fail64
#if defined(HEPTAKERNEL_TEST_SYSRET_RING3) || defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP)
    cmpq $0x43, 8(%rsp)          /* actual hardware SYSRET64 CS */
    jne fail64
    movq 16(%rsp), %rax
    andq $0x202, %rax
    cmpq $0x202, %rax           /* R11 fixed bit/IF in saved RFLAGS */
    jne fail64
#else
    cmpq $0x33, 8(%rsp)
    jne fail64
#endif
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
    cmpq $0x601f80, 24(%rsp)
#else
    cmpq $0x602000, 24(%rsp)
#endif
    jne fail64
    cmpq $0x3b, 32(%rsp)
    jne fail64
    leaq emergency_stack_top(%rip), %rsp
#ifdef HEPTAKERNEL_TEST_RSP0_DECOY
    leaq message_rsp0_decoy(%rip), %rsi
    call puts64
    jmp fail64
#else
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3_DECOY
    leaq message_elf_stack_ring3_decoy(%rip), %rsi
    call puts64
    jmp fail64
#else
    leaq message_elf_stack_ring3(%rip), %rsi
#endif
#elif defined(HEPTAKERNEL_TEST_SYSRET_RING3)
    leaq message_sysret_ring3(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SYSCALL_ONE_TASK)
#ifdef HEPTAKERNEL_TEST_SYSCALL_NR_UNKNOWN
    leaq message_syscall_one_task_enosys(%rip), %rsi
#else
    leaq message_syscall_one_task_getpid(%rip), %rsi
#endif
#elif defined(HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW)
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_LIFECYCLE
#ifdef HEPTAKERNEL_TEST_SYSCALL_LIFE_RETIRE
    leaq message_syscall_life_retired(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SYSCALL_LIFE_STALE)
    leaq message_syscall_life_stale(%rip), %rsi
#else
    leaq message_syscall_life_spawned(%rip), %rsi
#endif
#elif defined(HEPTAKERNEL_TEST_SYSCALL_TASK_BAD_LEADER)
    leaq message_syscall_task_leader_stale(%rip), %rsi
#else
    leaq message_syscall_task_tid(%rip), %rsi
#endif
#elif defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP)
    leaq message_syscall_roundtrip(%rip), %rsi
#else
    leaq message_rsp0_switch(%rip), %rsi
#endif
    call puts64
    movl $0x16, %eax                 /* QEMU exit 45 */
    jmp debug_exit64
#endif

#if defined(HEPTAKERNEL_TEST_SYSCALL_ROUNDTRIP) || defined(HEPTAKERNEL_TEST_SYSCALL_MSR_STALE)
/* NON-HIA isolated CPL0 entry: capture user RSP without touching it, then
 * switch to a supervisor stack before any push, call or memory-return. */
syscall_kernel_entry64:
    movq %rsp, syscall_user_rsp(%rip)
#ifdef HEPTAKERNEL_TEST_SYSCALL_STACK_BYPASS
    pushfq                  /* deliberately corrupt the user stack */
    popq %rax
#endif
    movabsq $stack_top, %rsp
#if defined(HEPTAKERNEL_TEST_SYSCALL_ONE_TASK) || defined(HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW)
    /* Actual ring3 RAX survives SYSCALL; retain before other HIA calls. */
    movq %rax, syscall_number(%rip)
#endif
    movq %rcx, syscall_saved_rcx(%rip)
    movq %r11, syscall_saved_r11(%rip)
    movw %cs, %ax
    cmpw $0x08, %ax
    jne fail64
    movw %ss, %ax
    cmpw $0x10, %ax
    jne fail64
    cmpq $(ARENA_MIN+2), %rcx
    jne fail64
    cmpq $0x602000, syscall_user_rsp(%rip)
    jne fail64
    movq %r11, %rax
    andq $0x202, %rax
    cmpq $0x202, %rax
    jne fail64
    pushfq
    popq %rax
    testq $0x200, %rax
    jne fail64                     /* FMASK actually cleared IF */
    leaq syscall_kernel_entry64(%rip), %rax
    cmpq syscall_expected_lstar(%rip), %rax
    jne fail64                     /* running high alias, not low */
    /* Genuine native HIA preflight. RSP saved before first stack access;
     * live TSS was populated by original HIA TSS installer. */
    movq syscall_user_rsp(%rip), %rdi
    movabsq $stack_top, %rsi
    movq tss64+4(%rip), %rdx
#ifdef HEPTAKERNEL_TEST_SYSCALL_STACK_STALE
    xorq $16, %rdx          /* falsely supplied but aligned TSS snapshot */
#endif
    call syscall_stack_admit_f0
#ifdef HEPTAKERNEL_TEST_SYSCALL_STACK_STALE
    cmpl $3, %eax
    jne fail64
    leaq message_syscall_stack_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    movabsq $stack_top, %rax
    cmpq %rax, %rsp
    jne fail64
    movabsq $0x735441434b475541, %rax
    cmpq %rax, 0x601ff8
    jne syscall_stack_corrupt64
    leaq message_syscall_stack_pass(%rip), %rsi
    call puts64
    /* The saved values came from real SYSCALL hardware. This original
     * native HIA verifies each captured return field before the NON-HIA
     * bridge restores RCX, R11 and RSP. No authority over the snapshots
     * or immunity to interrupts/re-entry is claimed. */
#ifdef HEPTAKERNEL_TEST_SYSCALL_FRAME_RCX_STALE
    xorq $1, syscall_saved_rcx(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_FRAME_R11_STALE
    xorq $1, syscall_saved_r11(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_FRAME_RSP_STALE
    xorq $16, syscall_user_rsp(%rip)
#endif
    movq $(ARENA_MIN+2), %rdi
    movq syscall_saved_rcx(%rip), %rsi
    movq $0x202, %rdx
    movq syscall_saved_r11(%rip), %rcx
    movq $0x602000, %r8
    movq syscall_user_rsp(%rip), %r9
    call syscall_return_frame_admit_f0
#ifdef HEPTAKERNEL_TEST_SYSCALL_FRAME_RCX_STALE
    cmpl $4, %eax
    jne fail64
    leaq message_syscall_frame_rcx_stale(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_SYSCALL_FRAME_R11_STALE)
    cmpl $5, %eax
    jne fail64
    leaq message_syscall_frame_r11_stale(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_SYSCALL_FRAME_RSP_STALE)
    cmpl $6, %eax
    jne fail64
    leaq message_syscall_frame_rsp_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    leaq message_syscall_frame_pass(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_SYSCALL_ONE_TASK
    /* Genuine HIA native one-task dispatcher; ONLY fixture TGID 4242.
     * Nothing here authenticates task identity or handles other syscalls. */
    movq syscall_number(%rip), %rdi
    movl $4242, %esi
    call syscall_one_task_f0
    movq %rax, syscall_result(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW
    /* The two records are test-fixture bytes, NEVER kernel-authenticated tasks.
     * The original HIA native function does the bounded reads and checks. */
    leaq syscall_task_snapshot(%rip), %r8
    movq $4242, 0(%r8)
    movq $4242, 8(%r8)
    movq $1, 16(%r8)
    movq $1, 24(%r8)
    movq $4243, 32(%r8)
    movq $4242, 40(%r8)
    movq $1, 48(%r8)
    movq $1, 56(%r8)
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_BAD_LEADER
    movq $9000, 8(%r8)         /* adversarial incorrect leader group */
#endif
#ifdef HEPTAKERNEL_TEST_SYSCALL_TASK_LIFECYCLE
    /* The two records are still NON-HIA fixture identities. The worker
     * begins empty and genuine Core v8 HIA activates it before the real
     * SYSCALL return. No Linux clone/exit or SMP task ownership is implied. */
    movq $0, syscall_task_snapshot+32(%rip)
    movq $0, syscall_task_snapshot+40(%rip)
    movq $0, syscall_task_snapshot+48(%rip)
    movq $0, syscall_task_snapshot+56(%rip)
    movq $0, syscall_task_life_request(%rip)       /* activate */
    movq $4242, syscall_task_life_request+8(%rip)
    movq $0, syscall_task_life_request+16(%rip)
    movq $4243, syscall_task_life_request+24(%rip)
    leaq syscall_task_life_request(%rip), %rdi
    movl $32, %esi
    leaq syscall_task_life_reply(%rip), %rdx
    movl $8, %ecx
    leaq syscall_task_snapshot(%rip), %r8
    movl $64, %r9d
    call syscall_task_lifecycle_f0
    testl %eax, %eax
    jne fail64
    cmpq $4243, syscall_task_life_reply(%rip)
    jne fail64
    cmpq $4243, syscall_task_snapshot+32(%rip)
    jne fail64
    cmpq $4242, syscall_task_snapshot+40(%rip)
    jne fail64
    cmpq $1, syscall_task_snapshot+48(%rip)
    jne fail64
    cmpq $1, syscall_task_snapshot+56(%rip)
    jne fail64
#if defined(HEPTAKERNEL_TEST_SYSCALL_LIFE_RETIRE) || defined(HEPTAKERNEL_TEST_SYSCALL_LIFE_STALE)
    movq $1, syscall_task_life_request(%rip)       /* retire */
    movq $0, syscall_task_life_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_SYSCALL_LIFE_STALE
    movq $4244, syscall_task_life_request+16(%rip) /* stale expected worker */
    movq $-17, syscall_task_life_reply(%rip)       /* rejection must not write */
#else
    movq $4243, syscall_task_life_request+16(%rip)
#endif
    leaq syscall_task_life_request(%rip), %rdi
    movl $32, %esi
    leaq syscall_task_life_reply(%rip), %rdx
    movl $8, %ecx
    leaq syscall_task_snapshot(%rip), %r8
    movl $64, %r9d
    call syscall_task_lifecycle_f0
#ifdef HEPTAKERNEL_TEST_SYSCALL_LIFE_STALE
    cmpl $6, %eax
    jne fail64
    cmpq $-17, syscall_task_life_reply(%rip)
    jne fail64
    cmpq $4243, syscall_task_snapshot+32(%rip)
    jne fail64
    cmpq $4242, syscall_task_snapshot+40(%rip)
    jne fail64
    cmpq $1, syscall_task_snapshot+48(%rip)
    jne fail64
    cmpq $1, syscall_task_snapshot+56(%rip)
    jne fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, syscall_task_life_reply(%rip)
    jne fail64
    cmpq $0, syscall_task_snapshot+32(%rip)
    jne fail64
    cmpq $0, syscall_task_snapshot+40(%rip)
    jne fail64
    cmpq $0, syscall_task_snapshot+48(%rip)
    jne fail64
    cmpq $0, syscall_task_snapshot+56(%rip)
    jne fail64
#endif
#endif
#endif /* HIA task lifecycle */
    movq syscall_number(%rip), %rax
    movq %rax, syscall_task_request(%rip)
    movq $1, syscall_task_request+8(%rip)  /* slot 1: worker */
    leaq syscall_task_request(%rip), %rdi
    movl $16, %esi                    /* exact request buffer */
    leaq syscall_task_reply(%rip), %rdx
    movl $8, %ecx                     /* exact result buffer */
    leaq syscall_task_snapshot(%rip), %r8
    movl $64, %r9d                    /* exact read-only records */
    call syscall_task_view_f0         /* status u32, HIA writes u64 result */
    testl %eax, %eax
    jne fail64
    movq syscall_task_reply(%rip), %rax
    movq %rax, syscall_result(%rip)
#endif
    movq syscall_saved_rcx(%rip), %rcx
    movq syscall_saved_r11(%rip), %r11
    movq syscall_user_rsp(%rip), %rsp
#if defined(HEPTAKERNEL_TEST_SYSCALL_ONE_TASK) || defined(HEPTAKERNEL_TEST_SYSCALL_TASK_VIEW)
    movq syscall_result(%rip), %rax  /* returned by real SYSRETQ to CPL3 */
#endif
    sysretq                  /* actual NON-HIA privileged return */
#endif
    jmp fail64
#endif
syscall_stack_corrupt64:
    leaq message_syscall_stack_corrupt(%rip), %rsi
    call puts64
    jmp fail64
#endif

#if defined(HEPTAKERNEL_TEST_US_FAULT) || defined(HEPTAKERNEL_TEST_US_STALE) || defined(HEPTAKERNEL_TEST_US_BYPASS)
/* Hardware CPL3 UD2 proves executable user mapping before the HIA downgrade. */
us_ring3_fault64:
    cli
    movw %cs, %ax
    cmpw $0x08, %ax
    jne fail64
    leaq stack_top(%rip), %rdx
    leaq -40(%rdx), %rax
    cmpq %rax, %rsp
    jne fail64
    cmpq $ARENA_MIN, 0(%rsp)
    jne fail64
    cmpq $0x33, 8(%rsp)
    jne fail64
    cmpq $0x602000, 24(%rsp)
    jne fail64
    cmpq $0x3b, 32(%rsp)
    jne fail64
    cmpq $0, us_stage(%rip)
    jne us_second_ud64
    /* The CPU sets PTE.Accessed: capture exact old bytes after CPL3 fetch. */
    movq $0, us_request(%rip)
    movq page_table_4m(%rip), %rax
    testq $4, %rax
    jz fail64
    movq %rax, us_request+8(%rip)
    btrq $2, %rax
    movq %rax, us_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, us_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_US_STALE
    /* A well-formed stale expected-old, not an invalid candidate. */
    xorq $8, us_request+8(%rip)
    xorq $8, us_request+16(%rip)
#endif
    movq $-1, us_reply(%rip)
    movq $-1, us_reply+8(%rip)
    leaq us_request(%rip), %rdi
    movl $32, %esi
    leaq us_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    /* The IRET frame remains on the RSP0 stack; align the HIA call. */
    subq $8, %rsp
    call pt_us_f0
    addq $8, %rsp
#ifdef HEPTAKERNEL_TEST_US_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, us_reply(%rip)
    jne fail64
    cmpq $0, us_reply+8(%rip)
    jne fail64
    movq us_request+8(%rip), %rax
    xorq $8, %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_us_initial(%rip), %rsi
    call puts64
    leaq message_us_stale(%rip), %rsi
    call puts64
    movl $0x24, %eax                /* QEMU exit 73 */
    jmp debug_exit64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, us_reply(%rip)
    jne fail64
    movq us_request+16(%rip), %rax
    cmpq %rax, us_reply+8(%rip)
    jne fail64
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    testq $4, %rax
    jnz fail64
    movq $1, us_stage(%rip)
    leaq message_us_initial(%rip), %rsi
    call puts64
    leaq message_us_live(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_US_BYPASS
    /* Deliberately restore permission after successful native HIA revoke. */
    btsq $2, page_table_4m(%rip)
    movq us_request+8(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
#endif
    movq $ARENA_MIN, %rax
    invlpg (%rax)                  /* NON-HIA privilege bridge */
    iretq                          /* return to exact original user RIP */
    jmp fail64
#endif

us_second_ud64:
#ifdef HEPTAKERNEL_TEST_US_BYPASS
    cmpq $1, us_stage(%rip)
    jne fail64
    movq us_request+8(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq emergency_stack_top(%rip), %rsp
    andq $-16, %rsp
    leaq message_us_bypass(%rip), %rsi
    call puts64
    movl $0x22, %eax                /* QEMU exit 69 */
    jmp debug_exit64
#else
    jmp fail64
#endif
#endif
#endif

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




#ifdef HEPTAKERNEL_TEST_COW_PTE_HW
/* Genuine HIA page-table data operation; non-HIA hardware observer only.
 * Two physically separate E820-admitted 4KiB frames live in 6–8MiB RAM.
 * Source and target page contents are initialized by the test fixture, not
 * claimed to have been allocated/copied by HIA in this experiment. */
cow_pte_hardware_exercise64:
    movq $0x601000, %rdi
    movq $1, %rsi
    call owner_admit64
    movq $0x602000, %rdi
    movq $1, %rsi
    call owner_admit64
    movq $0x601000, %rdi
    movabsq $0x1122334455667788, %rax
    movl $512, %ecx
    rep stosq
    movq $0x602000, %rdi
    movabsq $0x8899aabbccddeeff, %rax
    movl $512, %ecx
    rep stosq
    /* The initial 4MiB leaf was already installed by native HIA.
     * Native HIA now installs the shared user/RO/NX source mapping. */
    movq $0, pt_commit_request(%rip)
    movq page_table_4m(%rip), %rax
    movq %rax, pt_commit_request+8(%rip)
    movabsq $0x8000000000601005, %rax
    movq %rax, pt_commit_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_commit_request+24(%rip)
    movq $-1, pt_commit_reply(%rip)
    movq $-1, pt_commit_reply+8(%rip)
    leaq pt_commit_request(%rip), %rdi
    movl $32, %esi
    leaq pt_commit_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_commit_f0               /* pre-fault PTE installed by native HIA */
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_commit_reply(%rip)
    jne fail64
    movabsq $0x8000000000601005, %rax
    cmpq %rax, pt_commit_reply+8(%rip)
    jne fail64
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    movq %cr3, %rax
    movq %rax, %cr3               /* NON-HIA test-only TLB invalidation */
    movq $ARENA_MIN, %rdi
    movabsq $0x1122334455667788, %rax
    cmpq %rax, (%rdi)              /* warm original physical mapping */
    jne fail64
    movq page_table_4m(%rip), %rax /* CPU may set Accessed bit */
    testq $1, %rax
    jz fail64
    testq $4, %rax
    jz fail64
    testq $2, %rax
    jnz fail64
    movq %rax, cow_pte_old(%rip)
    movq $0, cow_pte_request(%rip)
    movq %rax, cow_pte_request+8(%rip)
    movabsq $0x000ffffffffff000, %rdx
    notq %rdx
    andq %rax, %rdx
    movabsq $0x602000, %rax
    orq %rdx, %rax
    orq $2, %rax
    movq %rax, cow_pte_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, cow_pte_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED
    /* The NON-HIA fixture declares table slots. HIA alone will detach,
     * clone the physical bytes, and later replace the PTE. */
    leaq cow_integrated_state(%rip), %rdi
    xorq %rax, %rax
    movl $512, %ecx
    rep stosq
    movabsq $0xa55aa55a5aa55aa5, %rax
    movq %rax, cow_integrated_guard_before(%rip)
    movq %rax, cow_integrated_guard_after(%rip)
    movw $2, cow_integrated_state(%rip)
    movw $17, cow_integrated_state+2(%rip)
    movb $2, cow_integrated_state+4(%rip)
    movb $2, cow_integrated_state+18(%rip)
#endif

#ifdef HEPTAKERNEL_TEST_COW_FRAME_BINDING_HW
    /* Real HIA PMM owns two E820-admitted pages. Native HIA checks its
     * live bitmap AND the actual hardware-active PTE before COW #PF.
     * The bridge supplies pointers, but cannot fabricate a green receipt. */
    leaq owner_init_b(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0                         /* unchanged locked HIA PMM */
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_alloc_reply(%rip)
    jne fail64
    cmpq $16, owner_alloc_reply+8(%rip)
    jne fail64
    leaq owner_alloc_two(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0                         /* HIA claims 0x601000 and 0x602000 */
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_alloc_reply(%rip)
    jne fail64
    cmpq $0x601000, owner_alloc_reply+8(%rip)
    jne fail64
    movabsq $0x314d4d504b484941, %rax
    cmpq %rax, owner_b_state(%rip)
    jne fail64
    cmpq $17, owner_b_state+8(%rip)
    jne fail64
    cmpq $0x600000, owner_b_state+16(%rip)
    jne fail64
    cmpq $1, owner_b_state+24(%rip)
    jne fail64
    cmpq $14, owner_b_state+32(%rip)
    jne fail64
    cmpb $7, owner_b_state+64(%rip)
    jne fail64

#ifdef HEPTAKERNEL_TEST_PMM_BITMAP_COW_HW
    /* Actual HIA PMM bitmap, not a synthetic copy; NON-HIA observer only. */
    movq $0x600000, pmm_bitmap_live_request(%rip)
    movq $17, pmm_bitmap_live_request+8(%rip)
    movq $1, pmm_bitmap_live_request+16(%rip)
#ifdef HEPTAKERNEL_TEST_PMM_BITMAP_FREE_STALE
    movq $13, owner_b_state+32(%rip) /* true free count remains 14 */
#endif
#ifdef HEPTAKERNEL_TEST_PMM_BITMAP_RESERVED_MISSING
    xorb $1, owner_b_state+64(%rip) /* forbidden missing reserved page */
#endif
#ifdef HEPTAKERNEL_TEST_PMM_BITMAP_TAIL_DIRTY
    orb $0x80, owner_b_state+66(%rip) /* bit 23 past page count 17 */
#endif
    /* Full-byte snapshot AFTER injection proves scanner never mutates PMM. */
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    rep movsq
    movq page_table_4m(%rip), %r12
    leaq pmm_bitmap_live_request(%rip), %rdi
    movl $24, %esi
    leaq owner_b_state(%rip), %rdx
    movl $STATE_BYTES, %ecx
    leaq pmm_bitmap_live_unused(%rip), %r8
    movl $8, %r9d
    call pmm_bitmap_integrity_f0 /* unchanged HIA selfhost native object */
    movl %eax, %r14d
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
    jne fail64
    cmpq %r12, page_table_4m(%rip)
    jne fail64
    cmpq $0x600000, pmm_bitmap_live_request(%rip)
    jne fail64
    cmpq $17, pmm_bitmap_live_request+8(%rip)
    jne fail64
    cmpq $1, pmm_bitmap_live_request+16(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PMM_BITMAP_NOOP
    cmpl $0, %r14d
    jne fail64
    leaq message_pmm_bitmap_noop(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_PMM_BITMAP_FREE_STALE)
    cmpl $5, %r14d
    jne fail64
    leaq message_pmm_bitmap_free_stale(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_PMM_BITMAP_RESERVED_MISSING)
    cmpl $4, %r14d
    jne fail64
    leaq message_pmm_bitmap_reserved_missing(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_PMM_BITMAP_TAIL_DIRTY)
    cmpl $4, %r14d
    jne fail64
    leaq message_pmm_bitmap_tail_dirty(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %r14d, %r14d
    jne fail64
    leaq message_pmm_bitmap_live(%rip), %rsi
    call puts64
#endif
#endif /* HEPTAKERNEL_TEST_PMM_BITMAP_COW_HW */

    movq $0x601000, cow_frame_binding_request(%rip)
    movq $0x602000, cow_frame_binding_request+8(%rip)
    movq cow_pte_old(%rip), %rax
    movq %rax, cow_frame_binding_request+16(%rip)
    movq $0x600000, cow_frame_binding_request+24(%rip)
    movq $17, cow_frame_binding_request+32(%rip)
    movq $1, cow_frame_binding_request+40(%rip)
#ifdef HEPTAKERNEL_TEST_COW_FRAME_BINDING_PTE_STALE
    /* Plausible but stale expected PTE: must give exact status 5. */
    xorq $8, cow_frame_binding_request+16(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_COW_FRAME_BINDING_BITMAP
    /* Adversarial PMM state: target looks free, despite a HIA claim. */
    xorb $4, owner_b_state+64(%rip)
#endif
    /* Frozen independent complete owner-state oracle, taken AFTER injection.
     * Real native binding is read-only, including every reserved byte. */
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    rep movsq
    movq page_table_4m(%rip), %r12
    leaq cow_frame_binding_request(%rip), %rdi
    movl $48, %esi
    leaq page_table_4m(%rip), %rdx  /* actual active PTE, not a copied word */
    movl $8, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call cow_frame_binding_f0       /* genuine selfhost HIA native .text */
    movl %eax, %r14d
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
    jne fail64
    cmpq %r12, page_table_4m(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_FRAME_BINDING_NOOP
    /* Hostile HIA always returns success on an invalid allocation bitmap;
     * this observer must DETECT that status, never pass COW. */
    cmpl $0, %r14d
    jne fail64
    leaq message_cow_frame_binding_noop(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_COW_FRAME_BINDING_BITMAP)
    cmpl $6, %r14d
    jne fail64
    leaq message_cow_frame_binding_bitmap(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_COW_FRAME_BINDING_PTE_STALE)
    cmpl $5, %r14d
    jne fail64
    leaq message_cow_frame_binding_pte_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %r14d, %r14d
    jne fail64
    leaq message_cow_frame_binding_live(%rip), %rsi
    call puts64
#endif
#endif /* HEPTAKERNEL_TEST_COW_FRAME_BINDING_HW */
    movq $0, cow_pte_stage(%rip)
    leaq message_cow_pte_mapped(%rip), %rsi
    call puts64
    movq $ARENA_MIN, %rdi
    movabsq $0xd4c3b2a1908f7e6d, %r10
cow_pte_store_insn:
    movq %r10, (%rdi)             /* MUST first #PF at CPL0, P=1,W=1 */
    cmpq $1, cow_pte_stage(%rip)
    jne fail64
    movabsq $0xd4c3b2a1908f7e6d, %rax
    cmpq %rax, (%rdi)             /* actual VA now targets private frame */
    jne fail64
    movq cow_pte_request+16(%rip), %rax
    orq $64, %rax                 /* actual CPU sets PTE.Dirty on retry */
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    movq $0x601000, %r8
    movq $0x602000, %r9
    movabsq $0x1122334455667788, %r11
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED
    movabsq $0x1122334455667788, %r12 /* copied, then first qword dirtied */
#else
    movabsq $0x8899aabbccddeeff, %r12
#endif
    movabsq $0xd4c3b2a1908f7e6d, %r13
    xorq %rcx, %rcx
cow_pte_bytes_oracle_loop:
    cmpq %r11, (%r8,%rcx,8)       /* source page ALL 4096 bytes intact */
    jne fail64
    testq %rcx, %rcx
    jnz cow_pte_oracle_unwritten
    cmpq %r13, (%r9,%rcx,8)
    jne fail64
    jmp cow_pte_oracle_next
cow_pte_oracle_unwritten:
    cmpq %r12, (%r9,%rcx,8)       /* destination's remaining 4088 bytes */
    jne fail64
cow_pte_oracle_next:
    incq %rcx
    cmpq $512, %rcx
    jb cow_pte_bytes_oracle_loop
    leaq message_cow_pte_remap_success(%rip), %rsi
    call puts64
#ifdef HEPTAKERNEL_TEST_COW_INTEGRATED
    /* Split/refcount and PTE were both performed by two HIA native calls;
     * only the non-HIA bridge supplied fault/IRET/TLB hardware effects. */
    cmpb $1, cow_integrated_state+18(%rip)
    jne fail64
    cmpb $1, cow_integrated_state+33(%rip)
    jne fail64
    leaq message_cow_integrated_verified(%rip), %rsi
    call puts64
#endif
    movl $0x25, %eax              /* QEMU exit 75 */
    jmp debug_exit64
#endif



/* Isolated QEMU proof point for original HIA Core v8 off-line shadow table:
 * read-only 4160-byte request contains a 4096-byte snapshot; HIA constructs
 * the distinct real aligned physical page before the sole parent PDE switch.
 * All CR3/parent PDE operations below are NON-HIA test bridge. No SMP,
 * atomic page-table publish, allocator-authority, or Linux VMM claim. */
#if defined(HEPTAKERNEL_TEST_PT_SHADOW_HW) || defined(HEPTAKERNEL_TEST_PT_SHADOW_STALE) || defined(HEPTAKERNEL_TEST_PT_SHADOW_LIAR) || defined(HEPTAKERNEL_TEST_PT_SHADOW_TAMPER)
pt_shadow_hardware_exercise64:
    movq $ARENA_MIN, %rdi
    movq $2, %rsi
    call owner_admit64
    /* Capture and independently verify an unlinked, all-zero original table
     * into the HIA read-only snapshot. The live PDE is still a 2 MiB leaf. */
    leaq page_table_4m(%rip), %rsi
    leaq pt_shadow_hw_request+64(%rip), %rdi
    movl $512, %ecx
pt_shadow_capture:
    cmpq $0, (%rsi)
    jne fail64
    movq (%rsi), %rax
    movq %rax, (%rdi)
    addq $8, %rsi
    addq $8, %rdi
    loop pt_shadow_capture
    /* Make no-op output impossible to confuse with BSS initialized output. */
    cld
    leaq pt_shadow_hw_table(%rip), %rdi
    movabsq $0xa5a5a5a5a5a5a5a5, %rax
    movl $512, %ecx
    rep stosq
    movq $ARENA_MIN, %rdi
    movabsq $0x123456789abcdef0, %rax
    movq %rax, (%rdi)
    movabsq $0x0fedcba987654321, %rax
    movq %rax, PAGE_BYTES(%rdi)
    /* Header: slot, old, new, slot, old, new, caps, reserved. */
    movq $0, pt_shadow_hw_request(%rip)
    movq $0, pt_shadow_hw_request+8(%rip)
    movabsq $0x8000000000401003, %rax
    movq %rax, pt_shadow_hw_request+16(%rip)
    movq $1, pt_shadow_hw_request+24(%rip)
    movq $0, pt_shadow_hw_request+32(%rip)
    movabsq $0x8000000000400003, %rax
    movq %rax, pt_shadow_hw_request+40(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_shadow_hw_request+48(%rip)
    movq $0, pt_shadow_hw_request+56(%rip)
#ifdef HEPTAKERNEL_TEST_PT_SHADOW_STALE
    movq $1, pt_shadow_hw_request+32(%rip)
#endif
    movabsq $0xcafebabecafebabe, %rax
    movq %rax, pt_shadow_hw_receipt(%rip)
    movq %rax, pt_shadow_hw_receipt+8(%rip)
    leaq pt_shadow_hw_request(%rip), %rdi
    movl $4160, %esi
    leaq pt_shadow_hw_table(%rip), %rdx
    movl $4096, %ecx
    leaq pt_shadow_hw_receipt(%rip), %r8
    movl $16, %r9d
    call pt_shadow_f0
#if defined(HEPTAKERNEL_TEST_PT_SHADOW_STALE)
    cmpl $7, %eax
    jne fail64
#elif defined(HEPTAKERNEL_TEST_PT_SHADOW_LIAR)
    testl %eax, %eax
    jne fail64
#else
    testl %eax, %eax
    jne fail64
#endif
    /* Independent observer: HIA must never touch its input snapshot or
     * the original PTE page. Two unchanged physical data frames also matter. */
    leaq page_table_4m(%rip), %rsi
    leaq pt_shadow_hw_request+64(%rip), %rdi
    movl $512, %ecx
pt_shadow_original_scan:
    cmpq $0, (%rsi)
    jne fail64
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rsi
    addq $8, %rdi
    loop pt_shadow_original_scan
    movq page_directory+16(%rip), %rax
    andq $-97, %rax
    cmpq $0x400083, %rax
    jne fail64
    movq $ARENA_MIN, %rdi
    movabsq $0x123456789abcdef0, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x0fedcba987654321, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
#if defined(HEPTAKERNEL_TEST_PT_SHADOW_STALE) || defined(HEPTAKERNEL_TEST_PT_SHADOW_LIAR)
    /* Rejection must leave all 4096 shadow bytes AND receipt untouched. */
    leaq pt_shadow_hw_table(%rip), %rdi
    movabsq $0xa5a5a5a5a5a5a5a5, %rax
    movl $512, %ecx
pt_shadow_rejected_scan:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop pt_shadow_rejected_scan
    movabsq $0xcafebabecafebabe, %rax
    cmpq %rax, pt_shadow_hw_receipt(%rip)
    jne fail64
    cmpq %rax, pt_shadow_hw_receipt+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PT_SHADOW_STALE
    leaq message_pt_shadow_stale(%rip), %rsi
#else
    leaq message_pt_shadow_liar(%rip), %rsi
#endif
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#else
    /* Independently compare all 512 HIA output words and the full receipt,
     * before any privileged parent publish. */
    movabsq $0x8000000000401003, %rax
    cmpq %rax, pt_shadow_hw_table(%rip)
    jne fail64
    cmpq %rax, pt_shadow_hw_receipt(%rip)
    jne fail64
    movabsq $0x8000000000400003, %rax
    cmpq %rax, pt_shadow_hw_table+8(%rip)
    jne fail64
    cmpq %rax, pt_shadow_hw_receipt+8(%rip)
    jne fail64
    leaq pt_shadow_hw_table+16(%rip), %rdi
    movl $510, %ecx
pt_shadow_tail_scan:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    loop pt_shadow_tail_scan
#ifdef HEPTAKERNEL_TEST_PT_SHADOW_TAMPER
    /* Adversarial post-build modification. Never publish the corrupt page. */
    xorq $2, pt_shadow_hw_table(%rip)
    movabsq $0x8000000000401001, %rax
    cmpq %rax, pt_shadow_hw_table(%rip)
    jne fail64
    movabsq $0x8000000000401003, %rax
    cmpq %rax, pt_shadow_hw_receipt(%rip)
    jne fail64
    movq page_directory+16(%rip), %rax
    andq $-97, %rax
    cmpq $0x400083, %rax
    jne fail64
    leaq message_pt_shadow_tamper(%rip), %rsi
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#else
    /* EXACTLY ONE parent pointer switched after a full-byte shadow check.
     * The PDE store / CR3 reload and exclusive ownership are test fixtures. */
    leaq pt_shadow_hw_table(%rip), %rax
    orq $3, %rax
    movq %rax, page_directory+16(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
    movq $ARENA_MIN, %rdi
    movabsq $0x0fedcba987654321, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x123456789abcdef0, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
    /* Hardware may set Accessed bits in the published entries. */
    movq pt_shadow_hw_table(%rip), %rax
    andq $-33, %rax
    movabsq $0x8000000000401003, %rdx
    cmpq %rdx, %rax
    jne fail64
    movq pt_shadow_hw_table+8(%rip), %rax
    andq $-33, %rax
    movabsq $0x8000000000400003, %rdx
    cmpq %rdx, %rax
    jne fail64
    leaq message_pt_shadow_live(%rip), %rsi
    call puts64
    movl $0x10, %eax
    jmp debug_exit64
#endif
#endif
#endif


/* Single-CPU QEMU PMM-owned shadow publication experiment.
 * All allocator, offline table, and frame-admit functions are untouched
 * selfhost_elf HIA native objects. Parent PDE/CR3 and observation remain
 * explicitly NON-HIA. The old table and new shadow are actual frames
 * allocated from the E820-admitted 0x600000 HIA PMM state. No Linux VMM,
 * verified exclusive ownership, concurrent publication or SMP claim. */
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_HW) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_LIAR) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_RECHECK) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
shadow_owner_hardware_exercise64:
    movq $0x100, case_index(%rip)
    movq $ARENA_MIN, %rdi
    movq $2, %rsi
    call owner_admit64
    movq $0x101, case_index(%rip)
    movq $0x600000, %rdi
    movq $17, %rsi
    call owner_admit64
    movq $0x102, case_index(%rip)

    /* Actual Core v8 PMM INIT and ALLOC_RUN(2): 0x601000, 0x602000. */
    leaq owner_init_b(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0
    movq $0x103, case_index(%rip)
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_alloc_reply(%rip)
    jne fail64
    cmpq $16, owner_alloc_reply+8(%rip)  /* usable pages after one reserved */
    jne fail64
    leaq owner_alloc_two(%rip), %rdi
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0
    movq $0x104, case_index(%rip)
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_alloc_reply(%rip)
    jne fail64
    cmpq $0x601000, owner_alloc_reply+8(%rip)
    jne fail64
    movabsq $0x314d4d504b484941, %rax
    cmpq %rax, owner_b_state(%rip)
    jne fail64
    cmpq $17, owner_b_state+8(%rip)
    jne fail64
    cmpq $0x600000, owner_b_state+16(%rip)
    jne fail64
    cmpq $1, owner_b_state+24(%rip)
    jne fail64
    cmpq $14, owner_b_state+32(%rip)
    jne fail64
    cmpb $7, owner_b_state+64(%rip)
    jne fail64
    movq $0x105, case_index(%rip)

    /* Both physical pages are mapped in the 6MiB identity huge leaf.
     * Old table begins all-zero; shadow destination starts with canaries.
     * The HIA table builder must produce every byte of the latter. */
    cld
    movq $0x602000, %rdi
    xorq %rax, %rax
    movl $512, %ecx
    rep stosq
    movq $0x601000, %rdi
    movabsq $0xa5a5a5a5a5a5a5a5, %rax
    movl $512, %ecx
    rep stosq
    leaq pt_shadow_hw_request+64(%rip), %rdi
    xorq %rax, %rax
    movl $512, %ecx
    rep stosq
    movq $ARENA_MIN, %rdi
    movabsq $0x123456789abcdef0, %rax
    movq %rax, (%rdi)
    movabsq $0x0fedcba987654321, %rax
    movq %rax, PAGE_BYTES(%rdi)
    movq $0, pt_shadow_hw_request(%rip)
    movq $0, pt_shadow_hw_request+8(%rip)
    movabsq $0x8000000000401003, %rax
    movq %rax, pt_shadow_hw_request+16(%rip)
    movq $1, pt_shadow_hw_request+24(%rip)
    movq $0, pt_shadow_hw_request+32(%rip)
    movabsq $0x8000000000400003, %rax
    movq %rax, pt_shadow_hw_request+40(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_shadow_hw_request+48(%rip)
    movq $0, pt_shadow_hw_request+56(%rip)
    movabsq $0xcafebabecafebabe, %rax
    movq %rax, pt_shadow_hw_receipt(%rip)
    movq %rax, pt_shadow_hw_receipt+8(%rip)

    /* NON-HIA bridge switches the 4MiB parent from 2MiB identity leaf
     * to the PMM-owned old zero leaf table, before HIA admission. */
    movq page_directory+16(%rip), %rax
    andq $-97, %rax
    cmpq $0x400083, %rax
    jne fail64
    movq $0x602003, page_directory+16(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
    movq $0x106, case_index(%rip)

    leaq pt_shadow_hw_request(%rip), %rdi
    movl $4160, %esi
    movq $0x601000, %rdx
    movl $4096, %ecx
    leaq pt_shadow_hw_receipt(%rip), %r8
    movl $16, %r9d
    call pt_shadow_f0               /* genuine, unchanged HIA table builder */
    movq $0x107, case_index(%rip)
    testl %eax, %eax
    jne fail64

    /* Byte-oracle independently checks all 512 words and builder receipt.
     * Active old physical page and immutable input snapshot remain zero. */
    movabsq $0x8000000000401003, %rax
    cmpq %rax, 0x601000
    jne fail64
    cmpq %rax, pt_shadow_hw_receipt(%rip)
    jne fail64
    movabsq $0x8000000000400003, %rax
    cmpq %rax, 0x601008
    jne fail64
    cmpq %rax, pt_shadow_hw_receipt+8(%rip)
    jne fail64
    leaq pt_shadow_hw_request+64(%rip), %rsi
    movq $0x602000, %rdx
    movq $0x601010, %rdi
    movl $510, %ecx
shadow_owner_full_scan:
    cmpq $0, (%rsi)
    jne fail64
    cmpq $0, (%rdx)
    jne fail64
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rsi
    addq $8, %rdx
    addq $8, %rdi
    loop shadow_owner_full_scan
    cmpq $0, pt_shadow_hw_request+64(%rip)
    jne fail64
    cmpq $0, 0x602000
    jne fail64
    cmpq $0x602003, page_directory+16(%rip)
    jne fail64
    movq $0x108, case_index(%rip)

    /* Request: new/old PMM frames, exact old/new nonleaf PDE, PMM
     * arena geometry and hardware-observed MAXPHYADDR width. */
    movq $0x601000, shadow_owner_request(%rip)
    movq $0x602000, shadow_owner_request+8(%rip)
    movq $0x602003, shadow_owner_request+16(%rip)
    movq $0x601003, shadow_owner_request+24(%rip)
    movq $0x600000, shadow_owner_request+32(%rip)
    movq $17, shadow_owner_request+40(%rip)
    movq $1, shadow_owner_request+48(%rip)
    movl pte_caps(%rip), %eax
    andl $255, %eax
    movq %rax, shadow_owner_request+56(%rip)
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_STALE
    movq $0x602007, shadow_owner_request+16(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP
    andb $0xfd, owner_b_state+64(%rip)
#endif
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    leaq shadow_owner_request(%rip), %rdi
    movl $64, %esi
    leaq shadow_owner_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $67, %r9d       /* exact HIA PMM header + ceil(17/8) bitmap */
    call shadow_admit_f0  /* genuine HIA read-only snapshot preflight */
    movq $0x109, case_index(%rip)
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_STALE)
    cmpl $5, %eax
    jne fail64
    jmp shadow_owner_refused
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP)
    cmpl $7, %eax
    jne fail64
    jmp shadow_owner_refused
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_LIAR)
    /* Malicious HIA always-success leaves the receipt at its canary.
     * Do not accept a status 0 without both independent receipt words. */
    testl %eax, %eax
    jne fail64
    jmp shadow_owner_refused
#else
    testl %eax, %eax
    jne fail64
    cmpq $0x601003, shadow_owner_reply(%rip)
    jne fail64
    cmpq $0x601000, shadow_owner_reply+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_RECHECK
    /* The first HIA admission passed. Mutate LIVE PMM state after it
     * to demonstrate a second HIA read denies post-admission reuse. */
    andb $0xfd, owner_b_state+64(%rip)
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    leaq shadow_owner_request(%rip), %rdi
    movl $64, %esi
    leaq shadow_owner_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_b_state(%rip), %r8
    movl $67, %r9d
    call shadow_admit_f0
    cmpl $7, %eax
    jne fail64
    jmp shadow_owner_refused
#else
    /* Genuine HIA full PMM bitmap/free-count admission after narrow
     * frame admission, before any NON-HIA parent PDE publication. */
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR)
    /* Post-admission fault: selected PMM bits are still correctly claimed,
     * but the free counter is now 13 rather than 14. */
    movq $13, owner_b_state+32(%rip)
#endif
    movq $0x600000, pmm_bitmap_live_request(%rip)
    movq $17, pmm_bitmap_live_request+8(%rip)
    movq $1, pmm_bitmap_live_request+16(%rip)
    movabsq $0xd76e35c1d76e35c1, %rax
    movq %rax, pmm_bitmap_live_unused(%rip)
    /* The full 8KiB PMM state is immutable across native HIA admission. */
    cld
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    rep movsq
    leaq pmm_bitmap_live_request(%rip), %rdi
    movl $24, %esi
    leaq owner_b_state(%rip), %rdx
    movl $STATE_BYTES, %ecx
    leaq pmm_bitmap_live_unused(%rip), %r8
    movl $8, %r9d
    call pmm_bitmap_integrity_f0
    movl %eax, %r12d
    cld
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
    jne fail64
    movabsq $0xd76e35c1d76e35c1, %rax
    cmpq %rax, pmm_bitmap_live_unused(%rip)
    jne fail64
    cmpq $0x600000, pmm_bitmap_live_request(%rip)
    jne fail64
    cmpq $17, pmm_bitmap_live_request+8(%rip)
    jne fail64
    cmpq $1, pmm_bitmap_live_request+16(%rip)
    jne fail64
    movq $0x10a, case_index(%rip)
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE
    cmpl $5, %r12d             /* True HIA detects inconsistent free count. */
    jne fail64
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    jmp shadow_owner_refused
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR)
    /* Separately HIA-compiled dishonest bitmap returns 0 on malformed
     * state. Independent observer checks all three occupancy bytes. */
    testl %r12d, %r12d
    jne fail64
    cmpb $7, owner_b_state+64(%rip)
    jne fail64
    cmpb $0, owner_b_state+65(%rip)
    jne fail64
    cmpb $0, owner_b_state+66(%rip)
    jne fail64
    cmpq $13, owner_b_state+32(%rip)
    jne fail64
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    jmp shadow_owner_refused
#else
    testl %r12d, %r12d
    jne fail64
    cmpq $14, owner_b_state+32(%rip)
    jne fail64
#endif
    /* Revalidate the complete LIVE PMM state close to publication, not only
     * the two selected frame bits. This is another genuine native HIA
     * scanner call, not a claimed lock/atomic transaction. */
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL
    /* Post-scan corruption at unused bit 23. The first scan passed. */
    orb $0x80, owner_b_state+66(%rip)
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
    /* A balanced but unauthorized fourth claim: bitmap and free count
     * remain internally consistent; a mere second scan is insufficient. */
    orb $0x08, owner_b_state+64(%rip)
    movq $13, owner_b_state+32(%rip)
#endif
    movabsq $0xd76e35c1d76e35c1, %rax
    movq %rax, pmm_bitmap_live_unused(%rip)
    leaq pmm_bitmap_live_request(%rip), %rdi
    movl $24, %esi
    leaq owner_b_state(%rip), %rdx
    movl $STATE_BYTES, %ecx
    leaq pmm_bitmap_live_unused(%rip), %r8
    movl $8, %r9d
    call pmm_bitmap_integrity_f0
    movl %eax, %r12d
    movq $0x10b, case_index(%rip)
    movabsq $0xd76e35c1d76e35c1, %rax
    cmpq %rax, pmm_bitmap_live_unused(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL
    cmpl $4, %r12d       /* genuine HIA rejects invalid tail bit */
    jne fail64
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    jmp shadow_owner_refused
#else
    testl %r12d, %r12d
    jne fail64
    /* The original 8KiB state is frozen before the first HIA full scan.
     * An internally consistent, unauthorized new allocation is rejected
     * by a separate full byte-for-byte epoch comparison. */
    cld
    leaq owner_b_state(%rip), %rsi
    leaq cow_frame_binding_snapshot(%rip), %rdi
    movl $(STATE_BYTES / 8), %ecx
    repe cmpsq
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED
    je fail64            /* independent state mismatch MUST be observed */
    cmpq $13, owner_b_state+32(%rip)
    jne fail64
    cmpb $15, owner_b_state+64(%rip)
    jne fail64
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    movq %rax, shadow_owner_reply(%rip)
    movq %rax, shadow_owner_reply+8(%rip)
    jmp shadow_owner_refused
#else
    jne fail64
#endif
#endif
    /* PRE-publish recheck of actual live parent and claimed PMM slots.
     * This is not an atomic CAS or concurrency-safe ownership proof. */
    cmpq $0x602003, page_directory+16(%rip)
    jne fail64
    cmpb $7, owner_b_state+64(%rip)
    jne fail64
    movabsq $0x8000000000401003, %rax
    cmpq %rax, 0x601000
    jne fail64
    movabsq $0x8000000000400003, %rax
    cmpq %rax, 0x601008
    jne fail64
    /* A single parent PDE write and CR3 reload are NON-HIA bridge. */
    movq $0x601003, page_directory+16(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
    movq $ARENA_MIN, %rdi
    movabsq $0x0fedcba987654321, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x123456789abcdef0, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
    /* Hardware accessed bits may become set in real HIA page-table RAM. */
    movq 0x601000, %rax
    andq $-33, %rax
    movabsq $0x8000000000401003, %rdx
    cmpq %rdx, %rax
    jne fail64
    movq 0x601008, %rax
    andq $-33, %rax
    movabsq $0x8000000000400003, %rdx
    cmpq %rdx, %rax
    jne fail64
    /* Hardware page walks set Accessed on the published parent PDE.
     * Check its identity/permissions, not an impossible untouched A bit. */
    movq page_directory+16(%rip), %rax
    andq $-33, %rax
    cmpq $0x601003, %rax
    jne fail64
    cmpb $7, owner_b_state+64(%rip)
    jne fail64
    leaq message_shadow_owner_hw(%rip), %rsi
    call puts64
    movl $0x10, %eax
    jmp debug_exit64
#endif
#endif

shadow_owner_refused:
    /* Negative observer verifies no PMM-owned shadow was published. */
    cmpq $0x602003, page_directory+16(%rip)
    jne fail64
    movabsq $0xa6a6a6a6a6a6a6a6, %rax
    cmpq %rax, shadow_owner_reply(%rip)
    jne fail64
    cmpq %rax, shadow_owner_reply+8(%rip)
    jne fail64
    movabsq $0x8000000000401003, %rax
    cmpq %rax, 0x601000
    jne fail64
    movabsq $0x8000000000400003, %rax
    cmpq %rax, 0x601008
    jne fail64
    cmpq $0, 0x602000
    jne fail64
    cmpq $0, pt_shadow_hw_request+64(%rip)
    jne fail64
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
    cmpq $13, owner_b_state+32(%rip)
#else
    cmpq $14, owner_b_state+32(%rip)
#endif
    jne fail64
#if defined(HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP) || defined(HEPTAKERNEL_TEST_SHADOW_OWNER_RECHECK)
    cmpb $5, owner_b_state+64(%rip)
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
    cmpb $15, owner_b_state+64(%rip)
#else
    cmpb $7, owner_b_state+64(%rip)
#endif
    jne fail64
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL
    cmpb $0x80, owner_b_state+66(%rip)
#else
    cmpb $0, owner_b_state+66(%rip)
#endif
    jne fail64
#ifdef HEPTAKERNEL_TEST_SHADOW_OWNER_STALE
    leaq message_shadow_owner_stale(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_LIAR)
    leaq message_shadow_owner_liar(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP)
    leaq message_shadow_owner_bitmap(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE)
    leaq message_shadow_owner_free_stale(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR)
    leaq message_shadow_owner_free_liar(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL)
    leaq message_shadow_owner_post_tail(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED)
    leaq message_shadow_owner_post_balanced(%rip), %rsi
#else
    leaq message_shadow_owner_recheck(%rip), %rsi
#endif
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#endif

/* Test-only fixture: real Core v8 HIA writes actual 4KiB PTE leaves.
 * E820 admission is HIA; caller owns both frames and table exclusively.
 * Parent PDE, CR3 reload and CPU observations are explicitly NON-HIA. */
#if defined(HEPTAKERNEL_TEST_PT_PAIR_HW) || defined(HEPTAKERNEL_TEST_PT_PAIR_STALE) || defined(HEPTAKERNEL_TEST_PT_PAIR_LIAR)
pt_pair_hardware_exercise64:
    movq $ARENA_MIN, %rdi
    movq $2, %rsi
    call owner_admit64
    leaq page_table_4m(%rip), %rdi
    xorq %rax, %rax
    movl $512, %ecx
pt_pair_zero_before:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop pt_pair_zero_before
    /* Identity-mapped physical data before changing the page table. */
    movq $ARENA_MIN, %rdi
    movabsq $0x123456789abcdef0, %rax
    movq %rax, (%rdi)
    movabsq $0x0fedcba987654321, %rax
    movq %rax, PAGE_BYTES(%rdi)
    movq $0, pt_pair_hw_request(%rip)
    movq $0, pt_pair_hw_request+8(%rip)
    movabsq $0x8000000000401003, %rax
    movq %rax, pt_pair_hw_request+16(%rip)
    movq $1, pt_pair_hw_request+24(%rip)
    movq $0, pt_pair_hw_request+32(%rip)
    movabsq $0x8000000000400003, %rax
    movq %rax, pt_pair_hw_request+40(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_pair_hw_request+48(%rip)
    movq $0, pt_pair_hw_request+56(%rip)
#ifdef HEPTAKERNEL_TEST_PT_PAIR_STALE
    /* Intentional second-slot stale-old error; first must remain zero. */
    movq $1, pt_pair_hw_request+32(%rip)
#endif
    movabsq $0xcafebabecafebabe, %rax
    movq %rax, pt_pair_hw_receipt(%rip)
    movq %rax, pt_pair_hw_receipt+8(%rip)
    leaq pt_pair_hw_request(%rip), %rdi
    movl $64, %esi
    leaq page_table_4m(%rip), %rdx
    movl $4096, %ecx
    leaq pt_pair_hw_receipt(%rip), %r8
    movl $16, %r9d
    call pt_pair_f0
#ifdef HEPTAKERNEL_TEST_PT_PAIR_STALE
    cmpl $7, %eax
    jne fail64
    movabsq $0xcafebabecafebabe, %rax
    cmpq %rax, pt_pair_hw_receipt(%rip)
    jne fail64
    cmpq %rax, pt_pair_hw_receipt+8(%rip)
    jne fail64
    leaq page_table_4m(%rip), %rdi
    xorq %rax, %rax
    movl $512, %ecx
pt_pair_refused_scan:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop pt_pair_refused_scan
    /* Accessed/Dirty may change on the original 2MiB hardware PDE. */
    movq page_directory+16(%rip), %rax
    andq $-97, %rax
    cmpq $0x400083, %rax
    jne fail64
    movq $ARENA_MIN, %rdi
    movabsq $0x123456789abcdef0, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x0fedcba987654321, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
    leaq message_pt_pair_stale(%rip), %rsi
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#elif defined(HEPTAKERNEL_TEST_PT_PAIR_LIAR)
    /* A real HIA-compiled always-success no-op is detected by readback. */
    testl %eax, %eax
    jne fail64
    cmpq $0, page_table_4m(%rip)
    jne fail64
    cmpq $0, page_table_4m+8(%rip)
    jne fail64
    movabsq $0xcafebabecafebabe, %rax
    cmpq %rax, pt_pair_hw_receipt(%rip)
    jne fail64
    cmpq %rax, pt_pair_hw_receipt+8(%rip)
    jne fail64
    movq page_directory+16(%rip), %rax
    andq $-97, %rax
    cmpq $0x400083, %rax
    jne fail64
    leaq message_pt_pair_liar(%rip), %rsi
    call puts64
    movl $0x11, %eax
    jmp debug_exit64
#else
    testl %eax, %eax
    jne fail64
    movabsq $0x8000000000401003, %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    cmpq %rax, pt_pair_hw_receipt(%rip)
    jne fail64
    movabsq $0x8000000000400003, %rax
    cmpq %rax, page_table_4m+8(%rip)
    jne fail64
    cmpq %rax, pt_pair_hw_receipt+8(%rip)
    jne fail64
    leaq page_table_4m+16(%rip), %rdi
    xorq %rax, %rax
    movl $510, %ecx
pt_pair_tail_scan:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop pt_pair_tail_scan
    /* Publication and invalidation remain non-HIA privileged test code. */
    leaq page_table_4m(%rip), %rax
    orq $3, %rax
    movq %rax, page_directory+16(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
    /* Hardware must now read the opposite frame from each virtual page. */
    movq $ARENA_MIN, %rdi
    movabsq $0x0fedcba987654321, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x123456789abcdef0, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
    /* A may change on CPU read; verify preserved PA and permission bits. */
    movq page_table_4m(%rip), %rax
    andq $-33, %rax
    movabsq $0x8000000000401003, %rdx
    cmpq %rdx, %rax
    jne fail64
    movq page_table_4m+8(%rip), %rax
    andq $-33, %rax
    movabsq $0x8000000000400003, %rdx
    cmpq %rdx, %rax
    jne fail64
    leaq message_pt_pair_live(%rip), %rsi
    call puts64
    movl $0x10, %eax
    jmp debug_exit64
#endif
#endif

/* One active 4KiB PTE is native HIA generated. The parent PDE and other
 * leaves remain in the explicitly non-HIA test bridge. */
pte_live_exercise64:
#if defined(HEPTAKERNEL_TEST_PT_NX_FAULT) || defined(HEPTAKERNEL_TEST_PT_NX_STALE) || defined(HEPTAKERNEL_TEST_PT_NX_BYPASS)
    /* Seed an original RET instruction while the old 2MiB RW map is live. */
    movq $ARENA_MIN, %rdi
    movb $0xc3, (%rdi)
#endif
    movabsq $0xa55aa55a5aa55aa5, %r10
    movq %r10, pte_guard_before(%rip)
    movq %r10, pte_guard_after(%rip)
    movq %r10, pte_unused(%rip)
    movq %r10, pte_unused+8(%rip)
    movq $0x400000, pte_request(%rip)
    movq $0x400000, pte_request+8(%rip)
#ifdef HEPTAKERNEL_TEST_INJECT_PTE_UNSAFE
    movq $7, pte_request+16(%rip) /* illegal W+X, must be refused */
#elif defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS)
    movq $1, pte_request+16(%rip) /* HIA read-only + NX */
#elif defined(HEPTAKERNEL_TEST_PT_NX_FAULT) || defined(HEPTAKERNEL_TEST_PT_NX_STALE) || defined(HEPTAKERNEL_TEST_PT_NX_BYPASS)
    movq $5, pte_request+16(%rip) /* HIA read-only + executable */
#else
    movq $3, pte_request+16(%rip) /* R+W, NX */
#endif
    movl pte_caps(%rip), %eax
    movq %rax, pte_request+24(%rip)
    movq $-1, pte_reply(%rip)
    movq $-1, pte_reply+8(%rip)
    leaq pte_request(%rip), %rdi
    movl $32, %esi
    leaq pte_reply(%rip), %rdx
    movl $16, %ecx
    leaq pte_unused(%rip), %r8
    movl $16, %r9d
    call pte_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, pte_reply(%rip)
    jne fail64
#if defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS)
    movabsq $0x8000000000400001, %r10
#elif defined(HEPTAKERNEL_TEST_PT_NX_FAULT) || defined(HEPTAKERNEL_TEST_PT_NX_STALE) || defined(HEPTAKERNEL_TEST_PT_NX_BYPASS)
    movabsq $0x0000000000400001, %r10
#else
    movabsq $0x8000000000400003, %r10
#endif
    cmpq %r10, pte_reply+8(%rip)
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %r10
    cmpq %r10, pte_guard_before(%rip)
    jne fail64
    cmpq %r10, pte_guard_after(%rip)
    jne fail64
    cmpq %r10, pte_unused(%rip)
    jne fail64
    cmpq %r10, pte_unused+8(%rip)
    jne fail64

    /* Existing 4-6MiB 2MiB PDE becomes a regular PT. Only the first
     * actual leaf is sourced from HIA; do not claim whole-page-table purity. */
    leaq page_table_4m(%rip), %rdi
    movabsq $0x8000000000400003, %rax
    movl $512, %ecx
pte_fill_4m:
    movq %rax, (%rdi)
    addq $4096, %rax
    addq $8, %rdi
    loop pte_fill_4m
    /* The leaf update is now performed by genuine HIA native code.
     * HIA checks an exclusive 4KiB page-table capability, candidate
     * permission bits, CPU admission and expected current PTE bytes.
     * This caller remains responsible for nonaliasing and CR3/TLB state. */
    movq $0, pt_commit_request(%rip)    /* leaf slot 0 => 0x400000 */
    movabsq $0x8000000000400003, %rax  /* assembly-filled old leaf */
    movq %rax, pt_commit_request+8(%rip)
#ifdef HEPTAKERNEL_TEST_PT_COMMIT_CONFLICT
    xorq $8, pt_commit_request+8(%rip) /* stale expected-old negative */
#endif
    movq pte_reply+8(%rip), %rax
    movq %rax, pt_commit_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_commit_request+24(%rip)
    movq $-1, pt_commit_reply(%rip)
    movq $-1, pt_commit_reply+8(%rip)
    leaq pt_commit_request(%rip), %rdi
    movl $32, %esi
    leaq pt_commit_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_commit_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_commit_reply(%rip)
    jne fail64
    movq pte_reply+8(%rip), %r10
    cmpq %r10, pt_commit_reply+8(%rip)
    jne fail64
    cmpq %r10, page_table_4m(%rip)
    jne fail64
    leaq message_pt_commit_pass(%rip), %rsi
    call puts64
    leaq page_table_4m(%rip), %rax
    orq $3, %rax
    movq %rax, page_directory+16(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
#if defined(HEPTAKERNEL_TEST_PT_NX_FAULT) || defined(HEPTAKERNEL_TEST_PT_NX_STALE) || defined(HEPTAKERNEL_TEST_PT_NX_BYPASS)
    /* Execute the genuine RX mapping before downgrading. The CPU may set
     * Accessed, hence capture the expected old leaf only after this fetch. */
    movq $ARENA_MIN, %rax
    call *%rax
    movq $ARENA_MIN, %rdi
    cmpb $0xc3, (%rdi)
    jne fail64
    movq $0, pt_nx_request(%rip)
    movq page_table_4m(%rip), %rax
    movq %rax, pt_nx_observed(%rip)
    movq %rax, pt_nx_request+8(%rip)
    btsq $63, %rax
    movq %rax, pt_nx_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_nx_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_PT_NX_STALE
    /* Valid candidate with mismatched old value, not a malformed request. */
    xorq $8, pt_nx_request+8(%rip)
    xorq $8, pt_nx_request+16(%rip)
#endif
    movq $-1, pt_nx_reply(%rip)
    movq $-1, pt_nx_reply+8(%rip)
    leaq pt_nx_request(%rip), %rdi
    movl $32, %esi
    leaq pt_nx_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_nx_f0                   /* selfhost HIA .text, not opaque bytes */
#ifdef HEPTAKERNEL_TEST_PT_NX_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pt_nx_reply(%rip)
    jne fail64
    cmpq $0, pt_nx_reply+8(%rip)
    jne fail64
    movq pt_nx_observed(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_pt_nx_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_nx_reply(%rip)
    jne fail64
    movq pt_nx_request+16(%rip), %rax
    cmpq %rax, pt_nx_reply+8(%rip)
    jne fail64
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_pt_nx_pass(%rip), %rsi
    call puts64
    movq $ARENA_MIN, %rdi
    invlpg (%rdi)                   /* NON-HIA TLB test bridge */
    cmpb $0xc3, (%rdi)              /* data read is still allowed */
    jne fail64
#ifdef HEPTAKERNEL_TEST_PT_NX_BYPASS
    btrq $63, page_table_4m(%rip)   /* deliberate NON-HIA restoration */
    invlpg (%rdi)
    movq $ARENA_MIN, %rax
    call *%rax                      /* bypass must be executable */
    leaq message_pt_nx_bypass(%rip), %rsi
    call puts64
    movl $0x1e, %eax                /* QEMU exit 61 */
    jmp debug_exit64
#else
    movq $0x4e585052, pt_nx_armed(%rip)
    movq $ARENA_MIN, %rax
    call *%rax                      /* must #PF, never return */
    jmp fail64
#endif
#endif
#endif
#if defined(HEPTAKERNEL_TEST_PT_PROTECT_FAULT) || defined(HEPTAKERNEL_TEST_PT_PROTECT_STALE) || defined(HEPTAKERNEL_TEST_PT_PROTECT_BYPASS)
    /* First warm the real leaf with a write and read. Hardware may set
     * Accessed and Dirty: exact old must be read after warming. */
    movq $ARENA_MIN, %rdi
    movabsq $0x1122334455667788, %r10
    movq %r10, (%rdi)
    cmpq %r10, (%rdi)
    jne fail64
    movq $0, pt_protect_request(%rip)
    movq page_table_4m(%rip), %rax
    movq %rax, pt_protect_observed(%rip)
    movq %rax, pt_protect_request+8(%rip)
    andq $-3, %rax
    movq %rax, pt_protect_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_protect_request+24(%rip)
#ifdef HEPTAKERNEL_TEST_PT_PROTECT_STALE
    /* The stale candidate must itself be a valid RW->RO transition:
     * otherwise the HIA gate rejects format before comparing the old PTE. */
    xorq $8, pt_protect_request+8(%rip)
    xorq $8, pt_protect_request+16(%rip)
#endif
    movq $-1, pt_protect_reply(%rip)
    movq $-1, pt_protect_reply+8(%rip)
    leaq pt_protect_request(%rip), %rdi
    movl $32, %esi
    leaq pt_protect_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_protect_f0            /* pinned selfhost HIA native object */
#ifdef HEPTAKERNEL_TEST_PT_PROTECT_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pt_protect_reply(%rip)
    jne fail64
    cmpq $0, pt_protect_reply+8(%rip)
    jne fail64
    movq pt_protect_observed(%rip), %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_pt_protect_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_protect_reply(%rip)
    jne fail64
    movq pt_protect_request+16(%rip), %rax
    cmpq %rax, pt_protect_reply+8(%rip)
    jne fail64
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_pt_protect_pass(%rip), %rsi
    call puts64
    movq $ARENA_MIN, %rdi
    invlpg (%rdi)                 /* NON-HIA CPL0 TLB bridge */
    movabsq $0x1122334455667788, %r10
    cmpq %r10, (%rdi)            /* read stays permitted */
    jne fail64
#ifdef HEPTAKERNEL_TEST_PT_PROTECT_BYPASS
    btsq $1, page_table_4m(%rip) /* deliberately restore RW outside HIA */
    invlpg (%rdi)
    movabsq $0x8899aabbccddeeff, %r10
    movq %r10, (%rdi)
    cmpq %r10, (%rdi)
    jne fail64
    leaq message_pt_protect_bypass(%rip), %rsi
    call puts64
    movl $0x1c, %eax            /* QEMU exit 57 */
    jmp debug_exit64
#else
    movq $0x50524f54, pt_protect_armed(%rip)
    movabsq $0x8899aabbccddeeff, %r10
pt_protect_store_insn:
    movq %r10, (%rdi)           /* must fault with P=1/W=1 */
    jmp fail64
#endif
#endif
#endif
#if defined(HEPTAKERNEL_TEST_PT_REVOKE_FAULT) || defined(HEPTAKERNEL_TEST_PT_REVOKE_STALE) || defined(HEPTAKERNEL_TEST_PT_REVOKE_BYPASS)
    /* Read the actual mapping before invalidation; retain independent
     * readback for the deliberately restored-mapping negative control. */
    movq $ARENA_MIN, %rdi
    movq (%rdi), %rax
    movq %rax, pt_revoke_observed(%rip)
    movq $0, pt_revoke_request(%rip)
    movq page_table_4m(%rip), %rax
    movq %rax, pt_revoke_request+8(%rip)
#ifdef HEPTAKERNEL_TEST_PT_REVOKE_STALE
    xorq $8, pt_revoke_request+8(%rip)
#endif
    movq $0, pt_revoke_request+16(%rip)
    movl pte_caps(%rip), %eax
    movq %rax, pt_revoke_request+24(%rip)
    movq $-1, pt_revoke_reply(%rip)
    movq $-1, pt_revoke_reply+8(%rip)
    leaq pt_revoke_request(%rip), %rdi
    movl $32, %esi
    leaq pt_revoke_reply(%rip), %rdx
    movl $16, %ecx
    leaq page_table_4m(%rip), %r8
    movl $4096, %r9d
    call pt_revoke_f0
#ifdef HEPTAKERNEL_TEST_PT_REVOKE_STALE
    cmpl $9, %eax
    jne fail64
    cmpq $9, pt_revoke_reply(%rip)
    jne fail64
    cmpq $0, pt_revoke_reply+8(%rip)
    jne fail64
    /* The CPU sets PTE.Accessed=1 during the warm read. Compare the actual
     * captured old value (with that hardware side effect) rather than the
     * earlier admission value returned by pt_commit_f0. */
    movq pt_revoke_request+8(%rip), %rax
    xorq $8, %rax
    cmpq %rax, page_table_4m(%rip)
    jne fail64
    leaq message_pt_revoke_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0, pt_revoke_reply(%rip)
    jne fail64
    cmpq $0, pt_revoke_reply+8(%rip)
    jne fail64
    cmpq $0, page_table_4m(%rip)
    jne fail64
    leaq message_pt_revoke_pass(%rip), %rsi
    call puts64
    movq $ARENA_MIN, %rdi
    invlpg (%rdi)                    /* NON-HIA CPL0 bridge */
#ifdef HEPTAKERNEL_TEST_PT_REVOKE_BYPASS
    /* Adversarial bridge restores PTE, flushes translation, and MUST read. */
    movq pt_commit_reply+8(%rip), %rax
    movq %rax, page_table_4m(%rip)
    invlpg (%rdi)
    movq (%rdi), %rax
    cmpq pt_revoke_observed(%rip), %rax
    jne fail64
    leaq message_pt_revoke_bypass(%rip), %rsi
    call puts64
    movl $0x1a, %eax                 /* debug exit 53 */
    jmp debug_exit64
#else
    movq $0x52564f4b, pt_revoke_armed(%rip)
pt_revoke_load_insn:
    movq (%rdi), %rax                /* must #PF, not return */
    jmp fail64
#endif
#endif
#endif
#if defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS)
    /* A real HIA read-only PTE is installed; the negative mutant
     * changes only the PTE RW bit in this explicit non-HIA test bridge. */
    movq $0x5750524f, pte_wp_armed(%rip)
#ifdef HEPTAKERNEL_TEST_WP_BYPASS
    btsq $1, page_table_4m(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
#endif
    movq $ARENA_MIN, %rdi
    movabsq $0x1122334455667788, %r10
wp_store_insn:
    movq %r10, (%rdi)
#ifdef HEPTAKERNEL_TEST_WP_BYPASS
    cmpq %r10, (%rdi)
    jne fail64
    leaq message_wp_bypass_pass(%rip), %rsi
    call puts64
    movl $0x15, %eax               /* QEMU exit 43, store + readback */
    jmp debug_exit64
#else
    jmp fail64                     /* WP must have trapped the store */
#endif
#else
    movq $0x400000, %rdi
    movabsq $0x1122334455667788, %r10
    movq %r10, (%rdi)
    cmpq %r10, (%rdi)
    jne fail64
#if defined(HEPTAKERNEL_TEST_NX_FETCH) || defined(HEPTAKERNEL_TEST_NX_BYPASS) || defined(HEPTAKERNEL_TEST_WP_STORE) || defined(HEPTAKERNEL_TEST_WP_BYPASS)
    /* A RET opcode gives an executable-page bypass a defined return path.
     * In the genuine test, NX must fault before this byte can execute. */
    movb $0xc3, (%rdi)
#ifdef HEPTAKERNEL_TEST_NX_BYPASS
    /* Deliberately corrupt the HIA-produced NX bit in a test-only bridge.
     * Re-load CR3 to invalidate the previously cached translation. */
    movq page_table_4m(%rip), %rax
    btrq $63, %rax
    movq %rax, page_table_4m(%rip)
    movq %cr3, %rax
    movq %rax, %cr3
#endif
    movq $0x4e584650, pte_nx_armed(%rip)
    movl $ARENA_MIN, %eax
    call *%rax
#ifdef HEPTAKERNEL_TEST_NX_BYPASS
    leaq message_nx_bypass_pass(%rip), %rsi
    call puts64
    movl $0x13, %eax               /* QEMU exit 39, bypass executed */
    jmp debug_exit64
#else
    jmp fail64                      /* NX would be broken if fetch returned */
#endif
#else
    movq $0, (%rdi)
    ret
#endif
#endif /* WP store or bypass */

/* The non-HIA Multiboot transport populates a bounded native-HIA request.
 * Three actual live intervals cover the image/BSS/stack, Multiboot info,
 * and original loader mmap. The fixed fixture checks all 4-8 MiB.
 * The opt-in discovery fixture checks its exact returned span and,
 * in its reserved variant, also checks the declared exclusion.
 */
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
#include "e820_discovery_fixture.inc"
#endif
reservation_admit64:
    movabsq $0xa55aa55a5aa55aa5, %r10
    movq %r10, reservation_guard_before(%rip)
    movq %r10, reservation_guard_after(%rip)
    movq %r10, reservation_unused(%rip)
    movq %r10, reservation_unused+8(%rip)
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
    movq e820_request(%rip), %rax
    movq %rax, reservation_request(%rip)
    movq $DISCOVERY_PAGES, reservation_request+8(%rip)
#else
    movq $ARENA_MIN, reservation_request(%rip)
    movq $1024, reservation_request+8(%rip)
#endif
    movq $0, reservation_request+16(%rip)
    movq $3, reservation_request+24(%rip)
    leaq __kernel_start(%rip), %rax
    movq %rax, reservation_request+32(%rip)
    leaq __kernel_end(%rip), %rdx
    subq %rax, %rdx
    jz fail64
    movq %rdx, reservation_request+40(%rip)
    movl boot_info(%rip), %eax
    movq %rax, reservation_request+48(%rip)
    movq $116, reservation_request+56(%rip)
    movl 48(%rax), %edx
    movq %rdx, reservation_request+64(%rip)
    movl 44(%rax), %edx
    movq %rdx, reservation_request+72(%rip)
#if defined(HEPTAKERNEL_TEST_E820_DISCOVERY_RESERVED)
    movq $4, reservation_request+24(%rip)
    movq $(ARENA_MIN+1), reservation_request+80(%rip)
    movq $1, reservation_request+88(%rip)
    movl $96, %esi
#elif defined(HEPTAKERNEL_TEST_INJECT_PROTECTED)
    /* Test-only claimed reservation overlapping otherwise usable RAM. */
    movq $4, reservation_request+24(%rip)
    movq $(ARENA_MIN + PAGE_BYTES), reservation_request+80(%rip)
    movq $PAGE_BYTES, reservation_request+88(%rip)
    movl $96, %esi
#else
    movl $80, %esi
#endif
    leaq reservation_request(%rip), %rdi
    movq $-1, reservation_reply(%rip)
    movq $-1, reservation_reply+8(%rip)
    leaq reservation_reply(%rip), %rdx
    movl $16, %ecx
    leaq reservation_unused(%rip), %r8
    movl $16, %r9d
    call reservation_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, reservation_reply(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY
    cmpq $DISCOVERY_PAGES, reservation_reply+8(%rip)
#else
    cmpq $1024, reservation_reply+8(%rip)
#endif
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %r10
    cmpq %r10, reservation_guard_before(%rip)
    jne fail64
    cmpq %r10, reservation_guard_after(%rip)
    jne fail64
    cmpq %r10, reservation_unused(%rip)
    jne fail64
    cmpq %r10, reservation_unused+8(%rip)
    jne fail64
    ret


/* Terminal, isolated physical-RAM observation. The single-owner compact PMM
 * records and 14-page independent oracle are NON-HIA fixtures. Only the
 * pinned Core v8 native HIA dual_claim_f0 performs claims and state writes.
 * Actual E820 is checked twice before any test physical page is touched.
 * This proves neither trusted ownership provenance nor SMP atomicity. */
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_HW
dual_claim_hardware_exercise64:
    movq $0x500000, %rdi
    movq $8, %rsi
    call owner_admit64
    movq $0x700000, %rdi
    movq $8, %rsi
    call owner_admit64
    movabsq $0x8b0f5a7cd320196e, %rax
    movq %rax, dual_claim_guard_before(%rip)
    movq %rax, dual_claim_guard_after(%rip)
    movq %rax, dual_claim_reply_guard_before(%rip)
    movq %rax, dual_claim_reply_guard_after(%rip)
    cld
    leaq dual_claim_seed(%rip), %rsi
    leaq dual_claim_state(%rip), %rdi
    movl $130, %ecx
    rep movsb
    leaq dual_claim_seed(%rip), %rsi
    leaq dual_claim_expected(%rip), %rdi
    movl $130, %ecx
    rep movsb

#if defined(HEPTAKERNEL_TEST_PMM_DUAL_STALE) || defined(HEPTAKERNEL_TEST_PMM_DUAL_LIAR)
    /* Bitmap 0x01 has one reserved page; free count 8 is forged (not 7).
     * Fault injection precedes HIA and no physical frame may be touched. */
    movq $8, dual_claim_state+32(%rip)
    movq $8, dual_claim_expected+32(%rip)
    call dual_claim_call64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_LIAR
    /* Compiled dishonest HIA returns 0 without changing its reply. The
     * independent oracle expects rejection, so the liar is detected. */
    testl %eax, %eax
    jne fail64
    movabsq $0xd0e1f2a3b4c59687, %rax
    cmpq %rax, dual_claim_reply(%rip)
    jne fail64
    cmpq %rax, dual_claim_reply+8(%rip)
    jne fail64
#else
    cmpl $4, %eax
    jne fail64
    cmpq $4, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
#endif
    call dual_claim_compare64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_LIAR
    leaq message_dual_liar(%rip), %rsi
#else
    leaq message_dual_stale(%rip), %rsi
#endif
    call puts64
    jmp fail64
#else
    /* Consume seven available pages in each HIA-owned bounded record.
     * Every HIA result is compared against an independently updated state
     * model before the observer writes its frame-specific full-page pattern. */
    xorq %r12, %r12
dual_claim_positive_loop:
    movq %r12, case_index(%rip)
    call dual_claim_call64
    testl %eax, %eax
    jne fail64
    cmpq $0, dual_claim_reply(%rip)
    jne fail64
    call dual_claim_expected_address64
    movq %rax, %r15
    cmpq %r15, dual_claim_reply+8(%rip)
    jne fail64
    movq %r12, %r14
    cmpq $7, %r12
    jb dual_claim_model_a
    subq $7, %r14
dual_claim_model_b:
    movq %r14, %rcx
    addq $2, %rcx
    movl $1, %eax
    shll %cl, %eax
    decl %eax
    movb %al, dual_claim_expected+129(%rip)
    movq $6, %rax
    subq %r14, %rax
    movq %rax, dual_claim_expected+97(%rip)
    jmp dual_claim_model_done
dual_claim_model_a:
    movq %r14, %rcx
    addq $2, %rcx
    movl $1, %eax
    shll %cl, %eax
    decl %eax
    movb %al, dual_claim_expected+64(%rip)
    movq $6, %rax
    subq %r14, %rax
    movq %rax, dual_claim_expected+32(%rip)
dual_claim_model_done:
    call dual_claim_compare64
    movq %r15, %rdi
    movabsq $0x7a3b91e24dc6580f, %rax
    xorq %r12, %rax
    movl $512, %ecx
    cld
    rep stosq                      /* independently write all 4KiB */
    incq %r12
    cmpq $14, %r12
    jb dual_claim_positive_loop

    /* The two zones are full. Two repeated HIA requests must refuse
     * exhaustion, returning 5/0 and preserving all 130 state bytes. */
    movq $2, %r14
dual_claim_exhaustion:
    call dual_claim_call64
    cmpl $5, %eax
    jne fail64
    cmpq $5, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
    decq %r14
    jnz dual_claim_exhaustion

#ifdef HEPTAKERNEL_TEST_PMM_DUAL_DECOY
    /* Adversarial RAM mutation after *successful* native HIA allocation;
     * the final CPU physical-page scan must see it, not cached receipts. */
    xorq $1, 0x501000
#endif
    xorq %r12, %r12
dual_claim_ram_scan:
    call dual_claim_expected_address64
    movq %rax, %rdi
    movabsq $0x7a3b91e24dc6580f, %r10
    xorq %r12, %r10
    movl $512, %ecx
dual_claim_ram_word:
    cmpq %r10, (%rdi)
    jne dual_claim_ram_bad
    addq $8, %rdi
    decl %ecx
    jnz dual_claim_ram_word
    incq %r12
    cmpq $14, %r12
    jb dual_claim_ram_scan
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_DECOY
    jmp fail64
#else
#ifdef HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_CLAIM
    /* Existing native HIA frees a frame for this isolated single-owner
     * experiment; new original HIA zeroes and reclaims it in one call. */
    call dual_claim_native_scrub_claim64
    leaq message_dual_native_claim(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_RELEASE)
    /* One genuine HIA call first zeroes the still-owned physical frame,
     * then marks it free in the HIA PMM state. This is a single-owner test. */
    call dual_claim_native_scrub_release64
    leaq message_dual_native_scrub(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_PMM_DUAL_RELEASE)
    /* The non-HIA observer checks a genuine HIA release, double-free
     * refusal and first-free reallocation of an E820-admitted RAM page. */
    call dual_claim_release_exercise64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB
    leaq message_dual_scrub(%rip), %rsi
#else
    leaq message_dual_release(%rip), %rsi
#endif
#else
    leaq message_dual_pass(%rip), %rsi
#endif
    call puts64
    movl $0x10, %eax              /* QEMU isa-debug-exit: 33 */
    jmp debug_exit64
#endif
dual_claim_ram_bad:
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_DECOY
    leaq message_dual_decoy(%rip), %rsi
    call puts64
#endif
    jmp fail64
#endif

#ifdef HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_CLAIM
dual_claim_native_scrub_claim64:
    /* The page was genuinely allocated, marked full and filled with a
     * known nonzero 4KiB pattern. Isolated owner first returns it through
     * the existing native HIA release ABI; no CPU/DMA concurrency is claimed. */
    movq $0x501000, dual_claim_release_request(%rip)
    call dual_claim_release_call64
    testl %eax, %eax
    jne fail64
    cmpq $0, dual_claim_reply(%rip)
    jne fail64
    cmpq $0x501000, dual_claim_reply+8(%rip)
    jne fail64
    movb $0xfd, dual_claim_expected+64(%rip)
    movq $1, dual_claim_expected+32(%rip)
    call dual_claim_compare64
    movq $0x501000, %rdi
    movabsq $0x7a3b91e24dc6580f, %r10
    movl $512, %ecx
dual_native_claim_old_scan:
    cmpq %r10, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_native_claim_old_scan

    /* The original, separately compiled HIA Core v8 .text performs both
     * zeroing and occupancy publication. The bridge only binds the guest
     * physical address and independently observes full RAM and metadata. */
    leaq dual_claim_release_request(%rip), %rdi
    movl $8, %esi
    leaq dual_claim_state(%rip), %rdx
    movl $130, %ecx
    movq $0x501000, %r8
    movl $4096, %r9d
    call pmm_scrub_claim_f0
    testl %eax, %eax
    jne fail64
#ifdef HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_CLAIM_NOOP
    /* A dishonest HIA function returns 0 while leaving old data and
     * unclaimed state unchanged. The independent observer must catch it. */
    call dual_claim_compare64
    movabsq $0x7a3b91e24dc6580f, %r10
    cmpq %r10, 0x501000
    jne fail64
    leaq message_dual_native_claim_noop(%rip), %rsi
    call puts64
    jmp fail64
#else
    movb $0xff, dual_claim_expected+64(%rip)
    movq $0, dual_claim_expected+32(%rip)
    call dual_claim_compare64
    movq $0x501000, %rdi
    movl $512, %ecx
dual_native_claim_zero_scan:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_native_claim_zero_scan
    /* A second claim of this occupied address must refuse without
     * zeroing its page; inject an observer-only sentinel to detect writes
     * in the reject path, and recheck full state plus all other words. */
    movabsq $0xdeadfacecafebeef, %r10
    movq %r10, 0x501000
    leaq dual_claim_release_request(%rip), %rdi
    movl $8, %esi
    leaq dual_claim_state(%rip), %rdx
    movl $130, %ecx
    movq $0x501000, %r8
    movl $4096, %r9d
    call pmm_scrub_claim_f0
    cmpl $6, %eax
    jne fail64
    call dual_claim_compare64
    movabsq $0xdeadfacecafebeef, %r10
    cmpq %r10, 0x501000
    jne fail64
    movq $0x501008, %rdi
    movl $511, %ecx
dual_native_claim_reject_scan:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_native_claim_reject_scan
    call dual_claim_call64
    cmpl $5, %eax
    jne fail64
    cmpq $5, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
    ret
#endif
#endif

#ifdef HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_RELEASE
dual_claim_native_scrub_release64:
    /* All fourteen distinct guest frames have been E820-admitted, claimed
     * by real native HIA and fully checked against the non-HIA RAM oracle.
     * The chosen frame 0x501000 is still occupied and contains old data. */
    movabsq $0x7a3b91e24dc6580f, %r10
    cmpq %r10, 0x501000
    jne fail64
    movq $0x501000, dual_claim_release_request(%rip)
    leaq dual_claim_release_request(%rip), %rdi
    movl $8, %esi
    leaq dual_claim_state(%rip), %rdx
    movl $130, %ecx
    movq $0x501000, %r8
    movl $4096, %r9d
    call pmm_scrub_release_f0  /* HIA Core v8 native code; no foreign zero */
    testl %eax, %eax
    jne fail64
#ifdef HEPTAKERNEL_TEST_PMM_NATIVE_SCRUB_RELEASE_NOOP
    /* The injected genuine HIA no-op falsely returns zero; both the PMM
     * state and physical frame remain unchanged. The independent observer
     * must catch this, never mistake a return code for scrub completion. */
    call dual_claim_compare64
    movabsq $0x7a3b91e24dc6580f, %r10
    cmpq %r10, 0x501000
    jne fail64
    leaq message_dual_native_scrub_noop(%rip), %rsi
    call puts64
    jmp fail64
#else
    /* Independent state model: previously occupied bit 1 is now free.
     * A real full-page scan, not the HIA return value, observes zero. */
    movb $0xfd, dual_claim_expected+64(%rip)
    movq $1, dual_claim_expected+32(%rip)
    call dual_claim_compare64
    movq $0x501000, %rdi
    movl $512, %ecx
dual_claim_native_scrub_scan64:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_claim_native_scrub_scan64
    /* Retried scrub on a now-free page must refuse, with both state and
     * the entire physical frame unchanged. */
    leaq dual_claim_release_request(%rip), %rdi
    movl $8, %esi
    leaq dual_claim_state(%rip), %rdx
    movl $130, %ecx
    movq $0x501000, %r8
    movl $4096, %r9d
    call pmm_scrub_release_f0
    cmpl $6, %eax
    jne fail64
    call dual_claim_compare64
    /* First free still belongs to zone zero; native HIA must reclaim
     * exactly this physical page. Keep the full zero scan after reclaim. */
    call dual_claim_call64
    testl %eax, %eax
    jne fail64
    cmpq $0x501000, dual_claim_reply+8(%rip)
    jne fail64
    movb $0xff, dual_claim_expected+64(%rip)
    movq $0, dual_claim_expected+32(%rip)
    call dual_claim_compare64
    movq $0x501000, %rdi
    movl $512, %ecx
dual_claim_native_scrub_reclaim_scan64:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_claim_native_scrub_reclaim_scan64
    ret
#endif
#endif

#ifdef HEPTAKERNEL_TEST_PMM_DUAL_RELEASE
dual_claim_release_exercise64:
    /* The requested frame was actually allocated as first user page of
     * zone zero; verify its existing 4KiB contents before release. */
    movabsq $0x7a3b91e24dc6580f, %r10
    cmpq %r10, 0x501000
    jne fail64
    /* Full-frame HIA scrub and independent readback must precede the
     * first native HIA release of this still-owned page. */
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB
    /* Single-owner test: zero the still-allocated E820-admitted page with
     * the unchanged native HIA page_zero_f0. No free-list publication may
     * precede the complete physical zero scan and its fault injection. */
    /* Even a zeroed page is still occupied until HIA releases it. */
    call dual_claim_call64
    cmpl $5, %eax
    jne fail64
    cmpq $5, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
    movabsq $0x4197eac3db5602f8, %rax
    movq %rax, dual_claim_scrub_guard_before(%rip)
    movq %rax, dual_claim_scrub_guard_after(%rip)
    movq $0, dual_claim_scrub_reply(%rip)
    movq $4096, dual_claim_scrub_reply+8(%rip)
    leaq dual_claim_empty_request(%rip), %rdi
    xorq %rsi, %rsi
    leaq dual_claim_scrub_reply(%rip), %rdx
    movl $16, %ecx
    movq $0x501000, %r8
    movl $4096, %r9d
#ifndef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_BYPASS
    call page_zero_f0         /* native HIA, not the assembly bridge */
#else
    xorl %eax, %eax          /* adversarial forged successful return */
#endif
    testl %eax, %eax
    jne fail64
    cmpq $0, dual_claim_scrub_reply(%rip)
    jne fail64
    cmpq $4096, dual_claim_scrub_reply+8(%rip)
    jne fail64
    movabsq $0x4197eac3db5602f8, %rax
    cmpq %rax, dual_claim_scrub_guard_before(%rip)
    jne fail64
    cmpq %rax, dual_claim_scrub_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_DECOY
    /* Independent post-HIA RAM mutation, invisible to the forged receipt. */
    movb $0xf3, 0x501a00
#endif
    movq $0x501000, %rdi
    movl $512, %ecx
dual_claim_scrub_scan64:
    cmpq $0, (%rdi)
    jne dual_claim_scrub_reject64
    addq $8, %rdi
    decl %ecx
    jnz dual_claim_scrub_scan64
#if defined(HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_BYPASS) || defined(HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_DECOY)
    /* A negative image passing the complete physical scan is a failure. */
    jmp fail64
#endif
    jmp dual_claim_scrub_clean64
dual_claim_scrub_reject64:
    /* Both negative images must retain full ownership: no release occurred. */
    /* Even a zeroed page is still occupied until HIA releases it. */
    call dual_claim_call64
    cmpl $5, %eax
    jne fail64
    cmpq $5, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_BYPASS
    leaq message_dual_scrub_bypass(%rip), %rsi
    call puts64
#elif defined(HEPTAKERNEL_TEST_PMM_DUAL_SCRUB_DECOY)
    leaq message_dual_scrub_decoy(%rip), %rsi
    call puts64
#endif
    jmp fail64
dual_claim_scrub_clean64:
    call dual_claim_compare64
    /* Even a zeroed page is still occupied until HIA releases it. */
    call dual_claim_call64
    cmpl $5, %eax
    jne fail64
    cmpq $5, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
#endif
    movq $0x501000, dual_claim_release_request(%rip)
    call dual_claim_release_call64
    testl %eax, %eax
    jne fail64
    cmpq $0, dual_claim_reply(%rip)
    jne fail64
    cmpq $0x501000, dual_claim_reply+8(%rip)
    jne fail64
    movb $0xfd, dual_claim_expected+64(%rip)
    movq $1, dual_claim_expected+32(%rip)
    call dual_claim_compare64
    /* The HIA PMM release does not change RAM: plain release keeps the
     * old pattern, whereas scrub mode must already contain only zeros. */
#ifndef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB
    movabsq $0x7a3b91e24dc6580f, %r10
    cmpq %r10, 0x501000
    jne fail64
#else
    cmpq $0, 0x501000
    jne fail64
#endif
    /* The second release must be rejected, leaving both zones untouched. */
    call dual_claim_release_call64
    cmpl $6, %eax
    jne fail64
    cmpq $6, dual_claim_reply(%rip)
    jne fail64
    cmpq $0, dual_claim_reply+8(%rip)
    jne fail64
    call dual_claim_compare64
    /* A new HIA claim must first-fit exactly the page now available. */
    call dual_claim_call64
    testl %eax, %eax
    jne fail64
    cmpq $0, dual_claim_reply(%rip)
    jne fail64
    cmpq $0x501000, dual_claim_reply+8(%rip)
    jne fail64
    movb $0xff, dual_claim_expected+64(%rip)
    movq $0, dual_claim_expected+32(%rip)
    call dual_claim_compare64
#ifdef HEPTAKERNEL_TEST_PMM_DUAL_SCRUB
    /* The reclaimed physical frame must STILL be fully zero before a
     * different principal could be allowed to populate it. */
    movq $0x501000, %rdi
    movl $512, %ecx
dual_claim_scrub_reclaim_scan64:
    cmpq $0, (%rdi)
    jne fail64
    addq $8, %rdi
    decl %ecx
    jnz dual_claim_scrub_reclaim_scan64
#endif
    movabsq $0x5511abcddcba1155, %r10
    movq %r10, 0x501000
    cmpq %r10, 0x501000
    jne fail64
    ret
dual_claim_release_call64:
    movabsq $0xd0e1f2a3b4c59687, %rax
    movq %rax, dual_claim_reply(%rip)
    movq %rax, dual_claim_reply+8(%rip)
    leaq dual_claim_release_request(%rip), %rdi
    movl $8, %esi
    leaq dual_claim_reply(%rip), %rdx
    movl $16, %ecx
    leaq dual_claim_state(%rip), %r8
    movl $130, %r9d
    call dual_claim_f0
    ret
#endif

dual_claim_call64:
    movabsq $0xd0e1f2a3b4c59687, %rax
    movq %rax, dual_claim_reply(%rip)
    movq %rax, dual_claim_reply+8(%rip)
    leaq dual_claim_empty_request(%rip), %rdi
    xorq %rsi, %rsi
    leaq dual_claim_reply(%rip), %rdx
    movl $16, %ecx
    leaq dual_claim_state(%rip), %r8
    movl $130, %r9d
    call dual_claim_f0
    ret

dual_claim_expected_address64:
    movq %r12, %rax
    cmpq $7, %rax
    jb 1f
    subq $7, %rax
    shlq $12, %rax
    addq $0x701000, %rax
    ret
1:
    shlq $12, %rax
    addq $0x501000, %rax
    ret

dual_claim_compare64:
    cld
    leaq dual_claim_expected(%rip), %rsi
    leaq dual_claim_state(%rip), %rdi
    movl $130, %ecx
    repe cmpsb
    jne fail64
    movabsq $0x8b0f5a7cd320196e, %rax
    cmpq %rax, dual_claim_guard_before(%rip)
    jne fail64
    cmpq %rax, dual_claim_guard_after(%rip)
    jne fail64
    cmpq %rax, dual_claim_reply_guard_before(%rip)
    jne fail64
    cmpq %rax, dual_claim_reply_guard_after(%rip)
    jne fail64
    ret
#endif /* HEPTAKERNEL_TEST_PMM_DUAL_HW */

/* Test-only multi-zone handoff. The policy and physical readback observer
 * remain NON-HIA; e820_f0, arena_f0 and f0 are the actual fixed HIA objects.
 * No state aliases, host syscalls, or external allocator are permitted.
 */
owner_exercise64:
    movabsq $0xa55aa55a5aa55aa5, %rax
    movq %rax, owner_a_guard_before(%rip)
    movq %rax, owner_a_guard_after(%rip)
    movq %rax, owner_b_guard_before(%rip)
    movq %rax, owner_b_guard_after(%rip)
    movq %rax, owner_reply_guard_before(%rip)
    movq %rax, owner_reply_guard_after(%rip)
    movq %rax, owner_route_guard_before(%rip)
    movq %rax, owner_route_guard_after(%rip)
    movq %rax, owner_route_unused(%rip)
    movq $1, owner_route_request(%rip)
    movq $2, owner_route_request+24(%rip)
    leaq owner_descriptors(%rip), %rsi
    leaq owner_route_request+32(%rip), %rdi
    movl $6, %ecx
    rep movsq

    /* Two separate E820 admissions against the retained loader map, not
     * merely a router success flag. 17 pages at each non-overlapping base. */
    movq $0x400000, %rdi
    movq $17, %rsi
    call owner_admit64
    movq $0x600000, %rdi
    movq $17, %rsi
    call owner_admit64

    /* The genuine HIA router chooses the state pointer via immutable table.
     * Check exact IDs rather than trusting a generic successful return. */
    movq $0x402000, %rdi
    movq $2, %rsi
    call owner_route64
    leaq owner_a_state(%rip), %rdx
    cmpq %rdx, %rax
    jne fail64
    movq %rax, owner_choice_a(%rip)
    movq $0x601000, %rdi
    movq $2, %rsi
    call owner_route64
#ifdef HEPTAKERNEL_TEST_ALIAS_OWNER_STATE
    /* Independent fault injection: fraudulent alias between two ownership
     * domains must be rejected before any physical page is touched. */
    movq owner_choice_a(%rip), %rax
#endif
    leaq owner_b_state(%rip), %rdx
    cmpq %rdx, %rax
    jne fail64
    cmpq owner_choice_a(%rip), %rax
    je fail64
    movq %rax, owner_choice_b(%rip)

    leaq owner_init_a(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $0, %rdx
    movq $15, %rcx
    call owner_call64
    leaq owner_init_b(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $0, %rdx
    movq $16, %rcx
    call owner_call64

    /* Validate each HIA-created PMM header against its physical arena
     * descriptor in separately native-compiled HIA, before touching pages.
     * This does not replace the full PMM state_valid() or E820 admission. */
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $15, %rdx
    call owner_bind64
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $16, %rdx
    call owner_bind64

    leaq owner_alloc_two(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $0, %rdx
    movq $0x402000, %rcx
    call owner_call64
    leaq owner_alloc_two(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $0, %rdx
    movq $0x601000, %rcx
    call owner_call64

    /* Probe all four real physical pages before either domain releases them.
     * Distinct full-word sentinels independently detect a physical alias. */
    movq $0x402000, %rdi
    movq $0x601000, %rsi
    movabsq $0x11447788aabbccdd, %rax
    movq %rax, (%rdi)
    movabsq $0x22558899bbccddee, %rax
    movq %rax, PAGE_BYTES(%rdi)
    movabsq $0x336699aaccddeeff, %rax
    movq %rax, (%rsi)
    movabsq $0x4477aabbddff0011, %rax
    movq %rax, PAGE_BYTES(%rsi)
    movabsq $0x11447788aabbccdd, %rax
    cmpq %rax, (%rdi)
    jne fail64
    movabsq $0x22558899bbccddee, %rax
    cmpq %rax, PAGE_BYTES(%rdi)
    jne fail64
    movabsq $0x336699aaccddeeff, %rax
    cmpq %rax, (%rsi)
    jne fail64
    movabsq $0x4477aabbddff0011, %rax
    cmpq %rax, PAGE_BYTES(%rsi)
    jne fail64
    movq $0, (%rdi)
    movq $0, PAGE_BYTES(%rdi)
    movq $0, (%rsi)
    movq $0, PAGE_BYTES(%rsi)

#if defined(HEPTAKERNEL_TEST_ELF_PLAN_HW)
    /* HIA reads actual ELF PHDRs before its independently compiled HIA fill. */
    call elf_plan_hw_exercise64
#elif defined(HEPTAKERNEL_TEST_ELF_PAGE_HW)
    /* Existing isolated file/BSS fill experiment, unchanged. */
    call elf_page_hw_exercise64
#elif defined(HEPTAKERNEL_TEST_ELF_STACK_HW)
    /* HIA writes an ELF initial-stack suffix to an E820/HIA-PMM RAM page. */
    call elf_stack_hw_exercise64
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3
#ifdef HEPTAKERNEL_TEST_ELF_STACK_RING3_DECOY
    /* Hostile fixture overwrites only AT_PHDR after genuine HIA success. */
    xorq $1, 0x601fa0
#endif
    call rsp0_ring3_exercise64
    jmp fail64
#endif
#endif

#if defined(HEPTAKERNEL_TEST_COW_REFCOUNT_HW)
    /* Quiescent, explicitly NON-HIA hardware observer. These two slots
     * represent the two distinct E820-admitted HIA PMM physical zones.
     * The mapping into the refcount table is TEST-ONLY; it is not a kernel
     * capability, concurrent COW manager, atomic count or ownership proof.
     * Genuine selfhost_elf HIA performs EVERY refcount table mutation. */
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $13, %rdx
    call owner_bind64
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64

    leaq cow_refcount_hw_table(%rip), %rdi
    movabsq $0x5b5b5b5b5b5b5b5b, %rax
    movl $512, %ecx
    rep stosq
    movb $1, cow_refcount_hw_table+2(%rip)
    movb $1, cow_refcount_hw_table+17(%rip)
    movabsq $0xa17be4c6d30f9285, %rax
    movq %rax, cow_refcount_hw_guard_before(%rip)
    movq %rax, cow_refcount_hw_guard_after(%rip)
    leaq cow_refcount_hw_slots(%rip), %r12
    movl $2, %r13d
cow_refcount_hw_each:
    movzwq (%r12), %r14
    movw %r14w, cow_refcount_hw_request(%rip)
    movb $1, cow_refcount_hw_request+2(%rip)
    movb $1, cow_refcount_hw_request+3(%rip)
    movq $0, cow_refcount_hw_reply(%rip)
    movq $2, cow_refcount_hw_reply+8(%rip)
    leaq cow_refcount_hw_request(%rip), %rdi
    movl $16, %esi
    leaq cow_refcount_hw_reply(%rip), %rdx
    movl $16, %ecx
    leaq cow_refcount_hw_table(%rip), %r8
    movl $4096, %r9d
    call cow_refcount_f0             /* original compiled HIA native code */
    testl %eax, %eax
    jne fail64
    leaq cow_refcount_hw_table(%rip), %r15
    cmpb $2, (%r15,%r14,1)           /* independent actual RAM observer */
    jne fail64
    cmpq $0, cow_refcount_hw_reply(%rip)
    jne fail64
    cmpq $2, cow_refcount_hw_reply+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_REFCOUNT_STALE
    /* Attempt detach with an explicitly stale expected-old count 1.
     * Success requires an actual HIA status 7, unchanged count and
     * unchanged 16-byte receipt, not a generic failure/timeout. */
    movb $2, cow_refcount_hw_request+2(%rip)
    movb $1, cow_refcount_hw_request+3(%rip)
    movabsq $0xd3a1792ee3b1558a, %rax
    movq %rax, cow_refcount_hw_reply(%rip)
    movq %rax, cow_refcount_hw_reply+8(%rip)
    leaq cow_refcount_hw_request(%rip), %rdi
    movl $16, %esi
    leaq cow_refcount_hw_reply(%rip), %rdx
    movl $16, %ecx
    leaq cow_refcount_hw_table(%rip), %r8
    movl $4096, %r9d
    call cow_refcount_f0
    cmpl $7, %eax
    jne fail64
    cmpb $2, (%r15,%r14,1)
    jne fail64
    movabsq $0xd3a1792ee3b1558a, %rax
    cmpq %rax, cow_refcount_hw_reply(%rip)
    jne fail64
    cmpq %rax, cow_refcount_hw_reply+8(%rip)
    jne fail64
    leaq message_cow_refcount_stale(%rip), %rsi
    call puts64
    jmp fail64
#endif
    /* Detach 2 -> 1 and release 1 -> 0 via the SAME native HIA code. */
    movb $2, cow_refcount_hw_request+2(%rip)
    movb $2, cow_refcount_hw_request+3(%rip)
    movq $0, cow_refcount_hw_reply(%rip)
    movq $1, cow_refcount_hw_reply+8(%rip)
    leaq cow_refcount_hw_request(%rip), %rdi
    movl $16, %esi
    leaq cow_refcount_hw_reply(%rip), %rdx
    movl $16, %ecx
    leaq cow_refcount_hw_table(%rip), %r8
    movl $4096, %r9d
    call cow_refcount_f0
    testl %eax, %eax
    jne fail64
    cmpb $1, (%r15,%r14,1)
    jne fail64
    cmpq $0, cow_refcount_hw_reply(%rip)
    jne fail64
    cmpq $1, cow_refcount_hw_reply+8(%rip)
    jne fail64
    movb $3, cow_refcount_hw_request+2(%rip)
    movb $1, cow_refcount_hw_request+3(%rip)
    movq $0, cow_refcount_hw_reply(%rip)
    movq $0, cow_refcount_hw_reply+8(%rip)
    leaq cow_refcount_hw_request(%rip), %rdi
    movl $16, %esi
    leaq cow_refcount_hw_reply(%rip), %rdx
    movl $16, %ecx
    leaq cow_refcount_hw_table(%rip), %r8
    movl $4096, %r9d
    call cow_refcount_f0
    testl %eax, %eax
    jne fail64
    cmpb $0, (%r15,%r14,1)
    jne fail64
    cmpq $0, cow_refcount_hw_reply(%rip)
    jne fail64
    cmpq $0, cow_refcount_hw_reply+8(%rip)
    jne fail64
    addq $2, %r12
    decq %r13
    jnz cow_refcount_hw_each
#ifdef HEPTAKERNEL_TEST_COW_REFCOUNT_DECOY
    /* Even with every HIA return/receipt valid, a NON-HIA adversary
     * corrupts an unrelated byte. Full-table RAM readback must reject. */
    movb $0x11, cow_refcount_hw_table+317(%rip)
#endif
    /* Full 4KiB byte oracle, including all 4094 unchanged slots.
     * Neither the HIA return value nor its receipt substitutes for RAM. */
    leaq cow_refcount_hw_table(%rip), %r15
    xorq %rcx, %rcx
cow_refcount_hw_scan:
    movb $0x5b, %al
    cmpq $2, %rcx
    je cow_refcount_hw_expected_zero
    cmpq $17, %rcx
    jne cow_refcount_hw_compare
cow_refcount_hw_expected_zero:
    xorb %al, %al
cow_refcount_hw_compare:
    cmpb %al, (%r15,%rcx,1)
    jne fail64
    incq %rcx
    cmpq $4096, %rcx
    jb cow_refcount_hw_scan
    movabsq $0xa17be4c6d30f9285, %rax
    cmpq %rax, cow_refcount_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, cow_refcount_hw_guard_after(%rip)
    jne fail64
    leaq message_cow_refcount_hw_pass(%rip), %rsi
    call puts64
#endif


#if defined(HEPTAKERNEL_TEST_COW_SPLIT_HW)
    /* Non-HIA QEMU oracle: physical frames allocated by real HIA PMM
     * and cross-checked with E820 and HIA ownership state. The genuine
     * cow_split_f0 alone performs the page copy and counter transitions.
     * Physical pointers and observers are expressly NON-HIA test scaffolding. */
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $13, %rdx
    call owner_bind64
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64
    leaq cow_split_hw_table(%rip), %rdi
    movabsq $0x5b5b5b5b5b5b5b5b, %rax
    movl $512, %ecx
    rep stosq
    movq $0, cow_split_hw_table(%rip)
    movq $0, cow_split_hw_table+8(%rip)
    movw $17, cow_split_hw_table+2(%rip)
    movb $2, cow_split_hw_table+4(%rip)
    movb $2, cow_split_hw_table+16(%rip)
    movb $0, cow_split_hw_table+33(%rip)
    movabsq $0xa17be4c6d30f9285, %rax
    movq %rax, cow_split_hw_guard_before(%rip)
    movq %rax, cow_split_hw_guard_after(%rip)
    movq $0x402000, %r14          /* actual zone A source frame */
    movq $0x601000, %r15          /* actual zone B destination frame */
    movq %r14, %rdi
    movabsq $0x125a73de6789abcd, %r10
    movl $512, %ecx
cow_split_hw_seed_source:
    movq %r10, (%rdi)
    addq $8, %rdi
    addq $0x10101, %r10
    decl %ecx
    jnz cow_split_hw_seed_source
    movq %r15, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    /* The actual source count remains 2; expected-old 1 must refuse. */
    movb $1, cow_split_hw_table+4(%rip)
#endif
    movq %r14, %rdi
    movl $4096, %esi
    movq %r15, %rdx
    movl $4096, %ecx
    leaq cow_split_hw_table(%rip), %r8
    movl $4096, %r9d
    call cow_split_f0              /* exact pinned HIA selfhost_elf object */
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    cmpl $6, %eax
    jne fail64
#else
    testl %eax, %eax
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_DEST_DECOY
    movb $0x44, 2033(%r15)       /* independent hostile RAM mutation */
#endif
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_SOURCE_DECOY
    movb $0x55, 3001(%r14)
#endif
#endif
    /* Full 8 KiB physical-page oracle. A stale refusal leaves destination
     * at its original sentinel; success copies every source byte. */
    movabsq $0x125a73de6789abcd, %r10
    movq %r14, %rdi
    movq %r15, %rsi
    movl $512, %ecx
cow_split_hw_pages:
    cmpq %r10, (%rdi)
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    cmpq %rax, (%rsi)
#else
    cmpq %r10, (%rsi)
#endif
    jne fail64
    addq $8, %rdi
    addq $8, %rsi
    addq $0x10101, %r10
    decl %ecx
    jnz cow_split_hw_pages
    /* Full 4096-byte state-table oracle: reserved bytes and untouched
     * counters stay unchanged. Check actual state, not a success receipt. */
    leaq cow_split_hw_table(%rip), %r15
    xorq %rcx, %rcx
cow_split_hw_table_scan:
    movb $0x5b, %al
    cmpq $16, %rcx
    jb cow_split_hw_header
    cmpq $16, %rcx
    je cow_split_hw_source_count
    cmpq $33, %rcx
    je cow_split_hw_target_count
    jmp cow_split_hw_compare
cow_split_hw_header:
    xorb %al, %al
    cmpq $2, %rcx
    je cow_split_hw_seventeen
    cmpq $4, %rcx
    je cow_split_hw_expected_old
    jmp cow_split_hw_compare
cow_split_hw_seventeen:
    movb $17, %al
    jmp cow_split_hw_compare
cow_split_hw_expected_old:
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    movb $1, %al
#else
    movb $2, %al
#endif
    jmp cow_split_hw_compare
cow_split_hw_source_count:
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    movb $2, %al
#else
    movb $1, %al
#endif
    jmp cow_split_hw_compare
cow_split_hw_target_count:
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    xorb %al, %al
#else
    movb $1, %al
#endif
cow_split_hw_compare:
    cmpb %al, (%r15,%rcx,1)
    jne fail64
    incq %rcx
    cmpq $4096, %rcx
    jb cow_split_hw_table_scan
    movabsq $0xa17be4c6d30f9285, %rax
    cmpq %rax, cow_split_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, cow_split_hw_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_COW_SPLIT_STALE
    leaq message_cow_split_stale(%rip), %rsi
    call puts64
    jmp fail64
#else
    leaq message_cow_split_hw_pass(%rip), %rsi
    call puts64
#endif
#endif

#if defined(HEPTAKERNEL_TEST_PAGE_COPY_HW)
    /* Recheck both actual native HIA PMM states after allocating both
     * cross-zone runs, immediately before providing the physical addresses
     * to HIA page_copy. This verifies the HIA bitmap/header state against
     * independently fixed descriptors and free counts (13 and 14).
     * It is a quiescent handoff, NOT an authenticated pointer capability
     * or atomic pin; the observer remains explicitly NON-HIA. */
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_OWNER_BASE_FORGE
    /* Fault injection: an apparently allocated destination zone is
     * misbound to a different physical base in its HIA-owned header. */
    movq $0x700000, owner_b_state+16(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_OWNER_COUNT_FORGE
    /* Fault injection: header free count disagrees with the bitmap. */
    movq $16, owner_b_state+32(%rip)
#endif
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $13, %rdx
    call owner_bind64            /* genuine native HIA state/bitmap checker */
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64            /* reject forged B domain before any copy */

    /* NON-HIA physical observer, not a capability/provenance implementation:
     * both pages of each pair were admitted by the actual Multiboot E820
     * gate, allocated by native HIA PMM and bound to distinct owner states.
     * Source and destination are disjoint physical frames. Only the
     * unchanged native HIA page_copy_f0 performs the measured copy. */
    leaq page_copy_hw_pairs(%rip), %r12
    movq $2, %r13
page_copy_hw_each:
    movq (%r12), %r14             /* E820/HIA PMM owned source physical RAM */
    movq 8(%r12), %r15            /* other-zone owned destination physical RAM */
    movq 16(%r12), %r10           /* independent per-pair expected byte seed */
    movq %r14, %rdi
    movl $512, %ecx
page_copy_hw_seed_source:
    movq %r10, (%rdi)             /* NON-HIA setup of adversarial source */
    addq $8, %rdi
    addq $0x10101, %r10
    decl %ecx
    jnz page_copy_hw_seed_source
    movq %r15, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq                     /* NON-HIA setup, not a copy */
    movabsq $0x35a5c66cd33db44b, %rax
    movq %rax, page_copy_hw_guard_before(%rip)
    movq %rax, page_copy_hw_guard_after(%rip)
    /* Plausible reply is seeded before call so a dishonest HIA no-op
     * cannot be caught merely by omitting a reply write. */
    movq $0, page_copy_hw_reply(%rip)
    movq $4096, page_copy_hw_reply+8(%rip)
    movq %r14, %rdi
    movl $4096, %esi
    leaq page_copy_hw_reply(%rip), %rdx
    movl $16, %ecx
    movq %r15, %r8
    movl $4096, %r9d
    call page_copy_f0             /* original native HIA selfhost_elf .text */
    testl %eax, %eax
    jne fail64
    cmpq $0, page_copy_hw_reply(%rip)
    jne fail64
    cmpq $4096, page_copy_hw_reply+8(%rip)
    jne fail64
    movabsq $0x35a5c66cd33db44b, %rax
    cmpq %rax, page_copy_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, page_copy_hw_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_DECOY
    /* Hostile NON-HIA bridge changes actual destination RAM after HIA. */
    cmpq $2, %r13
    jne page_copy_hw_after_dest_decoy
    movb $0x44, 2033(%r15)
page_copy_hw_after_dest_decoy:
#endif
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_SOURCE_DECOY
    /* Hostile NON-HIA bridge changes actual read-only source contents. */
    cmpq $2, %r13
    jne page_copy_hw_after_source_decoy
    movb $0x55, 3001(%r14)
page_copy_hw_after_source_decoy:
#endif
    /* Independent full-physical-RAM 8-byte oracle. Verify BOTH original
     * source and destination against the known 4096-byte sequence. */
    movq 16(%r12), %r10
    movq %r14, %rdi
    movq %r15, %rsi
    movl $512, %ecx
page_copy_hw_readback:
    cmpq %r10, (%rdi)
    jne fail64
    cmpq %r10, (%rsi)
    jne fail64
    addq $8, %rdi
    addq $8, %rsi
    addq $0x10101, %r10
    decl %ecx
    jnz page_copy_hw_readback
    addq $24, %r12
    decq %r13
    jnz page_copy_hw_each
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_DETACH
    /* Isolated COW data-path prerequisite, NOT a page-fault/COW manager:
     * after genuine HIA copy, invoke genuine HIA zero on the separately
     * PMM-owned destination. Independent physical readback must establish
     * source integrity and destination isolation across both arenas.
     * The NON-HIA test bridge provides addresses and a quiescent context. */
    leaq page_copy_hw_pairs(%rip), %r12
    movq $2, %r13
page_copy_detach_each:
    movq (%r12), %r14
    movq 8(%r12), %r15
    /* Preseed a plausible success receipt: never use it as the oracle. */
    movq $0, page_zero_hw_reply(%rip)
    movq $4096, page_zero_hw_reply+8(%rip)
    movabsq $0x4773bde155aae991, %rax
    movq %rax, page_zero_hw_guard_before(%rip)
    movq %rax, page_zero_hw_guard_after(%rip)
    leaq page_zero_hw_empty_request(%rip), %rdi
    xorq %rsi, %rsi
    leaq page_zero_hw_reply(%rip), %rdx
    movl $16, %ecx
    movq %r15, %r8
    movl $4096, %r9d
    call page_zero_f0             /* genuine native HIA; bypass swaps a dishonest native HIA */
    testl %eax, %eax
    jne fail64
    cmpq $0, page_zero_hw_reply(%rip)
    jne fail64
    cmpq $4096, page_zero_hw_reply+8(%rip)
    jne fail64
    movabsq $0x4773bde155aae991, %rax
    cmpq %rax, page_zero_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, page_zero_hw_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PAGE_COPY_DETACH_SOURCE_DECOY
    /* Hostile observer corrupts the original after HIA zeroes destination. */
    cmpq $2, %r13
    jne page_copy_detach_no_source_decoy
    movb $0xfa, 3171(%r14)
page_copy_detach_no_source_decoy:
#endif
    /* Full 16 KiB physical RAM oracle over the two pairs, not a receipt:
     * original source must retain every byte; detached destination is zero. */
    movq 16(%r12), %r10
    movq %r14, %rdi
    movq %r15, %rsi
    movl $512, %ecx
page_copy_detach_readback:
    cmpq %r10, (%rdi)
    jne fail64
    cmpq $0, (%rsi)
    jne fail64
    addq $8, %rdi
    addq $8, %rsi
    addq $0x10101, %r10
    decl %ecx
    jnz page_copy_detach_readback
    addq $24, %r12
    decq %r13
    jnz page_copy_detach_each
    leaq message_page_copy_detach_pass(%rip), %rsi
    call puts64
#endif
    leaq message_page_copy_hw_pass(%rip), %rsi
    call puts64
#endif

#if defined(HEPTAKERNEL_TEST_PAGE_ZERO_HW)
    /* NON-HIA independent QEMU observer: these four frames are currently
     * owned by two distinct native-HIA PMM states. Both zones passed actual
     * Multiboot E820 and protected-range admission before allocation.
     * The physical contents are filled nonzero, then only the genuine HIA
     * page-zero object is allowed to clear them. This fixture does NOT
     * establish authority inside page_zero or SMP synchronization. */
    leaq page_zero_hw_physical_pages(%rip), %r12
    movq $4, %r13
page_zero_hw_each:
    movq (%r12), %r14
    movq %r14, %rdi
    movabsq $0xd75ac321f00dbabe, %rax
    movl $512, %ecx
    rep stosq                       /* NON-HIA: initialize adversarial RAM */
    movabsq $0xa55aa55a5aa55aa5, %rax
    movq %rax, page_zero_hw_guard_before(%rip)
    movq %rax, page_zero_hw_guard_after(%rip)
    /* Pre-seed an apparently valid reply, so a dishonest no-op HIA cannot
     * be rejected based on missing reply writes alone. Physical readback
     * must separately prove every byte was cleared. */
    movq $0, page_zero_hw_reply(%rip)
    movq $4096, page_zero_hw_reply+8(%rip)
    leaq page_zero_hw_empty_request(%rip), %rdi
    xorq %rsi, %rsi
    leaq page_zero_hw_reply(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
    call page_zero_f0              /* genuine fixed upstream HIA machine code */
    testl %eax, %eax
    jne fail64
    cmpq $0, page_zero_hw_reply(%rip)
    jne fail64
    cmpq $4096, page_zero_hw_reply+8(%rip)
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, page_zero_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, page_zero_hw_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_PAGE_ZERO_DECOY
    /* Hostile NON-HIA bridge changes real RAM AFTER native HIA returns.
     * The independent full-byte observer must refuse false success. */
    cmpq $4, %r13
    jne 94f
    movb $0xe1, 2048(%r14)
94:
#endif
    movq %r14, %rsi
    movl $4096, %ecx
page_zero_hw_check:
    cmpb $0, (%rsi)
    jne fail64
    incq %rsi
    loop page_zero_hw_check
    addq $8, %r12
    decq %r13
    jnz page_zero_hw_each
    leaq message_page_zero_hw_pass(%rip), %rsi
    call puts64
#endif

    /* Exact cross-zone claims must fail without changing either owner. */
    leaq owner_claim_b(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $6, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_claim_a(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $6, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_query_a(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $5, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_query_b(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $5, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_free_a(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    xorq %rdx, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_free_b(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    xorq %rdx, %rdx
    xorq %rcx, %rcx
    call owner_call64
#if defined(HEPTAKERNEL_TEST_PAGE_ZERO_HW)
    /* Real PMM lifecycle on BOTH E820-admitted zones. After native HIA
     * releases both runs, its independent state binder must observe every
     * page as free, then native HIA first-fit must reallocate exactly those
     * physical frames. This is a quiescent NON-HIA coordinator, not SMP
     * ownership, authenticated DMA protection or safe user-space reuse. */
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $15, %rdx
    call owner_bind64
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $16, %rdx
    call owner_bind64
    leaq owner_alloc_two(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $0, %rdx
    movq $0x402000, %rcx
    call owner_call64
    leaq owner_alloc_two(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $0, %rdx
    movq $0x601000, %rcx
    call owner_call64
    leaq owner_descriptors(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $13, %rdx
    call owner_bind64
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64

    /* Reallocated RAM is deliberately made dirty AFTER reallocation.
     * An independent full-byte readback must refuse a claimed success if
     * either the native HIA scrub or any of its 4096 physical stores is
     * omitted. The third image bypasses the scrub but spoofs its reply. */
    leaq page_zero_hw_physical_pages(%rip), %r12
    movq $4, %r13
page_zero_recycle_each:
    movq (%r12), %r14
    movq %r14, %rdi
    movabsq $0xc1eada7afaceb00c, %rax
    movl $512, %ecx
    rep stosq
    movq $0, page_zero_hw_reply(%rip)
    movq $4096, page_zero_hw_reply+8(%rip)
    leaq page_zero_hw_empty_request(%rip), %rdi
    xorq %rsi, %rsi
    leaq page_zero_hw_reply(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
#ifndef HEPTAKERNEL_TEST_PAGE_ZERO_RECYCLE_BYPASS
    call page_zero_f0              /* exact genuine HIA object, no bridge zero */
#else
    xorq %rax, %rax                 /* hostile NON-HIA test-only forged status */
#endif
    testl %eax, %eax
    jne fail64
    cmpq $0, page_zero_hw_reply(%rip)
    jne fail64
    cmpq $4096, page_zero_hw_reply+8(%rip)
    jne fail64
    movq %r14, %rsi
    movl $4096, %ecx
page_zero_recycle_check:
    cmpb $0, (%rsi)
    jne fail64
    incq %rsi
    loop page_zero_recycle_check
    addq $8, %r12
    decq %r13
    jnz page_zero_recycle_each
    leaq message_page_zero_recycle_pass(%rip), %rsi
    call puts64

    /* Release again so original double-free refusal and free-count
     * postconditions retain their exact expected values. */
    leaq owner_free_a(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    xorq %rdx, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_free_b(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    xorq %rdx, %rdx
    xorq %rcx, %rcx
    call owner_call64
#endif

    leaq owner_free_a(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    movq $7, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_free_b(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $7, %rdx
    xorq %rcx, %rcx
    call owner_call64
    leaq owner_count(%rip), %rdi
    movq owner_choice_a(%rip), %rsi
    xorq %rdx, %rdx
    movq $15, %rcx
    call owner_call64
    leaq owner_count(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    xorq %rdx, %rdx
    movq $16, %rcx
    call owner_call64
    leaq message_owner_pass(%rip), %rsi
    call puts64
    ret


/* Real guest RAM byte oracle for genuine native HIA ELF64 page filling.
 * Both pages belong to the zone-B two-page run allocated by HIA PMM.
 * The non-HIA bridge alone arranges the fixture, checks ownership and
 * observes physical memory. No kernel ELF loader/privilege claim. */
#ifdef HEPTAKERNEL_TEST_ELF_PAGE_HW
elf_page_hw_exercise64:
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64
    /* Copy immutable on-image file bytes and request to a guarded envelope. */
    movabsq $0x9dc743a160b2e58f, %rax
    movq %rax, elf_hw_guard_before(%rip)
    movq %rax, elf_hw_guard_after(%rip)
    movq %rax, elf_hw_receipt_guard_before(%rip)
    movq %rax, elf_hw_receipt_guard_after(%rip)
    leaq elf_page_fixture(%rip), %rsi
    leaq elf_hw_envelope(%rip), %rdi
    movl $390, %ecx
    cld
    rep movsq
    movq $0x601000, %r14
    movq %r14, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq
    /* Deliberately seed a plausible SUCCESS receipt, so an HIA no-op is
     * caught by full physical RAM rather than a missing receipt. */
    movq $0xa5, elf_hw_receipt(%rip)
    movq $0, elf_hw_receipt+8(%rip)
    leaq elf_hw_envelope(%rip), %rdi
#ifdef HEPTAKERNEL_TEST_ELF_PAGE_TRUNCATED
    /* Same real source bytes but the final file byte is inaccessible.
     * HIA must refuse *before* writing even one physical byte. */
    movl $3119, %esi
#else
    movl $3120, %esi
#endif
    leaq elf_hw_receipt(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
    call elf_page_f0          /* original HIA selfhost_elf .text */
#ifdef HEPTAKERNEL_TEST_ELF_PAGE_TRUNCATED
    cmpl $5, %eax
    jne fail64
    cmpq $0xa5, elf_hw_receipt(%rip)
    jne fail64
    cmpq $0, elf_hw_receipt+8(%rip)
    jne fail64
    xorq %rcx, %rcx
elf_hw_refusal_scan:
    cmpb $0xe7, (%r14,%rcx)
    jne fail64
    incq %rcx
    cmpq $4096, %rcx
    jb elf_hw_refusal_scan
    leaq message_elf_hw_truncated(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpq $0xa5, elf_hw_receipt(%rip)
    jne fail64
    cmpq $0, elf_hw_receipt+8(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_PAGE_NOOP
    /* Dishonest native HIA returns success but leaves both physical ends
     * at the original dirty sentinel. The independent observer detects it. */
    cmpb $0xe7, (%r14)
    jne fail64
    cmpb $0xe7, 4095(%r14)
    jne fail64
    leaq message_elf_hw_noop(%rip), %rsi
    call puts64
    jmp fail64
#endif
#ifdef HEPTAKERNEL_TEST_ELF_PAGE_DECOY
    /* A malicious NON-HIA post-call store must defeat the byte oracle,
     * notwithstanding correct HIA return, receipt and original object. */
    movb $0xec, 2048(%r14)
    cmpb $0xec, 2048(%r14)
    jne fail64
    cmpb $0x66, 2048(%r14)     /* file byte (2048 - 123) % 8 = 5 */
    je fail64
    leaq message_elf_hw_decoy(%rip), %rsi
    call puts64
    jmp fail64
#endif
    /* Independent expected bytes: 123 leading zeroes, 3073 file bytes
     * with a known eight-byte pattern, 900 BSS/unused zeroes. */
    xorq %r12, %r12
elf_hw_file_scan:
    xorq %r10, %r10
    cmpq $123, %r12
    jb elf_hw_file_compare
    cmpq $3196, %r12
    jae elf_hw_file_compare
    movq %r12, %r10
    subq $123, %r10
    andq $7, %r10
    leaq elf_page_pattern(%rip), %r11
    movzbl (%r11,%r10,1), %r10d
elf_hw_file_compare:
    cmpb %r10b, (%r14,%r12,1)
    jne fail64
    incq %r12
    cmpq $4096, %r12
    jb elf_hw_file_scan
    /* HIA must not modify either red zone or source file payload. */
    movabsq $0x9dc743a160b2e58f, %rax
    cmpq %rax, elf_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_hw_guard_after(%rip)
    jne fail64
    cmpq %rax, elf_hw_receipt_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_hw_receipt_guard_after(%rip)
    jne fail64
    leaq elf_page_fixture+40(%rip), %rsi
    leaq elf_hw_envelope+40(%rip), %rdi
    movl $385, %ecx
    repe cmpsq
    jne fail64

    /* Fill the *second* PMM-owned physical frame from the same real bytes.
     * It is entirely BSS because 123+3073 fits into the first page. */
    movq $1, elf_hw_envelope+32(%rip)
    movq $0x602000, %r14
    movq %r14, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq
    movq $0xa5, elf_hw_receipt(%rip)
    movq $0, elf_hw_receipt+8(%rip)
    leaq elf_hw_envelope(%rip), %rdi
    movl $3120, %esi
    leaq elf_hw_receipt(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
    call elf_page_f0
    testl %eax, %eax
    jne fail64
    cmpq $0xa5, elf_hw_receipt(%rip)
    jne fail64
    cmpq $0, elf_hw_receipt+8(%rip)
    jne fail64
    xorq %rcx, %rcx
elf_hw_bss_scan:
    cmpb $0, (%r14,%rcx,1)
    jne fail64
    incq %rcx
    cmpq $4096, %rcx
    jb elf_hw_bss_scan
    movabsq $0x9dc743a160b2e58f, %rax
    cmpq %rax, elf_hw_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_hw_guard_after(%rip)
    jne fail64
    cmpq %rax, elf_hw_receipt_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_hw_receipt_guard_after(%rip)
    jne fail64
    leaq elf_page_fixture+40(%rip), %rsi
    leaq elf_hw_envelope+40(%rip), %rdi
    movl $385, %ecx
    repe cmpsq
    jne fail64
    leaq message_elf_hw_pass(%rip), %rsi
    call puts64
    ret
#endif
#endif



/* The source/receipt come from genuine HIA Core v8 machine code, run against
 * E820-admitted physical RAM allocated by the native HIA PMM.  This non-HIA
 * observer supplies the static test metadata, compares every physical byte,
 * and exits on explicit failed/hostile cases. Not a Linux execve/VM loader. */
#ifdef HEPTAKERNEL_TEST_ELF_STACK_HW
elf_stack_hw_exercise64:
    movq $0x601000, %rdi
    movq $1, %rsi
    call owner_admit64
    movq $0x602000, %rdi
    movq $1, %rsi
    call owner_admit64
    movq $0x601000, %rdi
    movabsq $0x5a5a5a5a5a5a5a5a, %rax
    movl $512, %ecx
    rep stosq
    movq $0x602000, %rdi
    movabsq $0x9dc743a160b2e58f, %rax
    movq %rax, (%rdi)              /* adjoining allocation canary */
    movq $0x601000, elf_stack_request(%rip)
    movq $0x401000, elf_stack_request+8(%rip)
    movq $0x400040, elf_stack_request+16(%rip)
    movq $56, elf_stack_request+24(%rip)
    movq $3, elf_stack_request+32(%rip)
    movabsq $0x5a5a5a5a5a5a5a5a, %rax
    movq %rax, elf_stack_receipt(%rip)
    movq %rax, elf_stack_receipt+8(%rip)
#ifdef HEPTAKERNEL_TEST_ELF_STACK_BAD_PHENT
    movq $64, elf_stack_request+24(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_ELF_STACK_ENTRY_COLLISION
    /* The entry RIP must not alias the writable initial stack page. */
    movq $0x601000, elf_stack_request+8(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_ELF_STACK_PHDR_COLLISION
    /* AT_PHDR begins before the stack, but 3*56 bytes overlap it. */
    movq $0x600ff0, elf_stack_request+16(%rip)
#endif
    leaq elf_stack_request(%rip), %rdi
    movl $40, %esi
    movq $0x601000, %rdx
    movl $4096, %ecx
    leaq elf_stack_receipt(%rip), %r8
    movl $16, %r9d
    call elf_stack_f0              /* actual original selfhost_elf HIA .text */
#if defined(HEPTAKERNEL_TEST_ELF_STACK_BAD_PHENT) || defined(HEPTAKERNEL_TEST_ELF_STACK_ENTRY_COLLISION) || defined(HEPTAKERNEL_TEST_ELF_STACK_PHDR_COLLISION)
    cmpl $3, %eax                  /* geometry rejected before any store */
    jne fail64
    movq $0x601000, %rdi
    movabsq $0x5a5a5a5a5a5a5a5a, %rax
    movl $512, %ecx
.Lelf_stack_refusal_scan:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop .Lelf_stack_refusal_scan
    cmpq %rax, elf_stack_receipt(%rip)
    jne fail64
    cmpq %rax, elf_stack_receipt+8(%rip)
    jne fail64
    movq $0x602000, %rdi
    movabsq $0x9dc743a160b2e58f, %rax
    cmpq %rax, (%rdi)
    jne fail64
#if defined(HEPTAKERNEL_TEST_ELF_STACK_ENTRY_COLLISION)
    leaq message_elf_stack_entry_collision(%rip), %rsi
#elif defined(HEPTAKERNEL_TEST_ELF_STACK_PHDR_COLLISION)
    leaq message_elf_stack_phdr_collision(%rip), %rsi
#else
    leaq message_elf_stack_bad_phent(%rip), %rsi
#endif
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_STACK_LIAR
    /* A status=0-only malicious HIA must not pass physical/receipt oracle. */
    movq $0x601000, %rdi
    cmpq $0, 3968(%rdi)
    je fail64
    movabsq $0x5a5a5a5a5a5a5a5a, %rax
    cmpq %rax, elf_stack_receipt(%rip)
    jne fail64
    cmpq %rax, elf_stack_receipt+8(%rip)
    jne fail64
    movq $0x602000, %rdi
    movabsq $0x9dc743a160b2e58f, %rax
    cmpq %rax, (%rdi)
    jne fail64
    leaq message_elf_stack_liar(%rip), %rsi
    call puts64
    jmp fail64
#else
    cmpq $0x601f80, elf_stack_receipt(%rip)
    jne fail64
    cmpq $128, elf_stack_receipt+8(%rip)
    jne fail64
    movq $0x601000, %rdi
    movabsq $0x5a5a5a5a5a5a5a5a, %rax
    movl $496, %ecx
.Lelf_stack_prefix_scan:
    cmpq %rax, (%rdi)
    jne fail64
    addq $8, %rdi
    loop .Lelf_stack_prefix_scan
    leaq elf_stack_expected_words(%rip), %rsi
    movl $16, %ecx
    repe cmpsq                      /* every byte in original HIA 128-byte suffix */
    jne fail64
    movq $0x602000, %rdi
    movabsq $0x9dc743a160b2e58f, %rax
    cmpq %rax, (%rdi)
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_STACK_DECOY
    /* After a verified true HIA write, tamper only the physical output. */
    movq $0x601000, %rdi
    xorq $1, 4000(%rdi)
    leaq elf_stack_expected_words(%rip), %rsi
    leaq 3968(%rdi), %rdi
    movl $16, %ecx
    repe cmpsq
    je fail64                      /* bypass was incorrectly accepted */
    leaq message_elf_stack_decoy(%rip), %rsi
    call puts64
    jmp fail64
#else
    leaq message_elf_stack_pass(%rip), %rsi
    call puts64
    ret
#endif
#endif
#endif
#endif

/* Independent NON-HIA hardware choreography of the original native HIA
 * ELF PT_LOAD plan + independently compiled genuine HIA physical page fill.
 * The source fixture, immutable snapshot discipline, oracle, and privilege
 * operations are NOT a HIA kernel ELF loader or a publication transaction. */
#ifdef HEPTAKERNEL_TEST_ELF_PLAN_HW
elf_plan_hw_exercise64:
    leaq owner_descriptors+24(%rip), %rdi
    movq owner_choice_b(%rip), %rsi
    movq $14, %rdx
    call owner_bind64

    movabsq $0x7c51df2948ea036b, %rax
    movq %rax, elf_plan_guard_before(%rip)
    movq %rax, elf_plan_guard_after(%rip)
    movq %rax, elf_plan_env_guard_before(%rip)
    movq %rax, elf_plan_env_guard_after(%rip)
    leaq elf_plan_image(%rip), %rsi
    leaq elf_plan_mutable(%rip), %rdi
    movl $7292, %ecx
    cld
    rep movsb
    movq $0, elf_plan_selector(%rip)
    movq $0, elf_plan_selector+8(%rip)
    leaq elf_plan_out(%rip), %rdi
    movb $0xe9, %al
    movl $40, %ecx
    rep stosb

    /* The genuine HIA full-file gate runs on the SAME ELF bytes as the
     * HIA selected-PT_LOAD planner. It refuses conflicting page layouts
     * and PT_INTERP before either physical page can be written. This is
     * an isolated read-only admission, not authenticated file ownership. */
#if defined(HEPTAKERNEL_TEST_ELF_LAYOUT_OVERLAP) || defined(HEPTAKERNEL_TEST_ELF_LAYOUT_LIAR)
    /* Independent hostile fixture: a second valid, read-only PT_LOAD
     * occupies the first segment's virtual page. The selected page-plan
     * alone would admit PHDR 0, but full-file HIA must return 13. */
    movw $2, elf_plan_mutable+56(%rip)
    movl $1, elf_plan_mutable+120(%rip)
    movl $4, elf_plan_mutable+124(%rip)
    movq $0x1200, elf_plan_mutable+128(%rip)
    movq $0x401200, elf_plan_mutable+136(%rip)
    movq $0, elf_plan_mutable+144(%rip)
    movq $128, elf_plan_mutable+152(%rip)
    movq $4096, elf_plan_mutable+160(%rip)
    movq $4096, elf_plan_mutable+168(%rip)
#endif
    /* The real HIA stage object copies the already prepared source.
     * All following HIA layout, plan, fill and equality calls use its
     * distinct destination. Ownership is still a test-bridge assumption. */
    movabsq $0xe9e9e9e9e9e9e9e9, %rax
    movq %rax, elf_plan_stage_receipt(%rip)
    movq %rax, elf_plan_stage_receipt+8(%rip)
    movabsq $0x7c51df2948ea036b, %rax
    movq %rax, elf_plan_stage_guard_before(%rip)
    movq %rax, elf_plan_stage_guard_after(%rip)
    leaq elf_plan_mutable(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_staged(%rip), %rdx
    movl $7292, %ecx
    leaq elf_plan_stage_receipt(%rip), %r8
    movl $16, %r9d
    call elf_stage_f0
    testl %eax, %eax
    jne fail64
    cmpb $0xa5, elf_plan_stage_receipt(%rip)
    jne fail64
    cmpb $0x5a, elf_plan_stage_receipt+1(%rip)
    jne fail64
    movabsq $0x7c51df2948ea036b, %rax
    cmpq %rax, elf_plan_stage_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_plan_stage_guard_after(%rip)
    jne fail64

    /* Independent full-file bytes defeat a dishonest HIA which returns
     * 0 and forges the receipt while skipping the copy. */
    leaq elf_plan_mutable(%rip), %rsi
    leaq elf_plan_staged(%rip), %rdi
    movl $7292, %ecx
    cld
    repe cmpsb
#ifdef HEPTAKERNEL_TEST_ELF_STAGE_NOOP
    je fail64
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_stage_noop(%rip), %rsi
    call puts64
    jmp fail64
#else
    jne fail64
#endif
#ifdef HEPTAKERNEL_TEST_ELF_STAGE_CORRUPT
    xorb $0x5a, elf_plan_staged+0x1200(%rip)
#endif
#ifdef HEPTAKERNEL_TEST_ELF_SOURCE_ISOLATED
    xorb $0x5a, elf_plan_mutable+0x1200(%rip)
    movzbl elf_plan_staged+0x1200(%rip), %eax
    cmpb %al, elf_plan_mutable+0x1200(%rip)
    je fail64
#endif

    leaq elf_plan_staged(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_out(%rip), %rdx
    movl $40, %ecx
    leaq elf_plan_selector(%rip), %r8
    movl $16, %r9d
    call elf_layout_f0       /* original native HIA full PT_LOAD admission */
#ifdef HEPTAKERNEL_TEST_ELF_LAYOUT_OVERLAP
    cmpl $13, %eax
    jne fail64
    /* Check the ENTIRE 8KiB physical target, not only its first word. */
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_layout_overlap(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_ELF_LAYOUT_LIAR)
    testl %eax, %eax
    jne fail64
    cmpw $2, elf_plan_mutable+56(%rip)
    jne fail64
    cmpl $1, elf_plan_mutable+120(%rip)
    jne fail64
    /* Deliberately dishonest native HIA accepted an overlapping file. */
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_layout_liar(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
#endif


    /* Sentinel is initialized before the first equality call, so the
     * stage-corrupt refusal can prove that HIA leaves its receipt unchanged. */
    movabsq $0xe9e9e9e9e9e9e9e9, %rax
    movq %rax, elf_plan_snapshot_receipt(%rip)
    movq %rax, elf_plan_snapshot_receipt+8(%rip)
    /* True native HIA byte-by-byte scan of the immutable fixture versus
     * the exact working ELF used by the full-layout admission. This does
     * not authenticate the reference or make later accesses atomic. */
    leaq elf_plan_image(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_staged(%rip), %rdx
    movl $7292, %ecx
    leaq elf_plan_snapshot_receipt(%rip), %r8
    movl $16, %r9d
    call elf_snapshot_f0
#ifdef HEPTAKERNEL_TEST_ELF_STAGE_CORRUPT
    cmpl $4, %eax
    jne fail64
    cmpb $0xe9, elf_plan_snapshot_receipt(%rip)
    jne fail64
    cmpb $0xe9, elf_plan_snapshot_receipt+15(%rip)
    jne fail64
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_stage_corrupt(%rip), %rsi
    call puts64
    jmp fail64
#endif
    testl %eax, %eax
    jne fail64
    cmpb $0xa5, elf_plan_snapshot_receipt(%rip)
    jne fail64
    cmpb $0x5a, elf_plan_snapshot_receipt+1(%rip)
    jne fail64

#ifdef HEPTAKERNEL_TEST_ELF_PLAN_INVALID
    /* A hostile coordinator changes p_offset after the source snapshot:
     * 0x107c no longer has the same 4KiB residue as 0x40107b. */
    addq $1, elf_plan_staged+72(%rip)
#endif
    leaq elf_plan_staged(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_selector(%rip), %rdx
    movl $16, %ecx
    leaq elf_plan_out(%rip), %r8
    movl $40, %r9d
    call elf_plan_f0         /* exact native HIA .text, not a foreign decoder */

#ifdef HEPTAKERNEL_TEST_ELF_PLAN_INVALID
    cmpl $6, %eax
    jne fail64
    leaq elf_plan_out(%rip), %rsi
    xorq %rcx, %rcx
.Lelf_plan_invalid_unchanged:
    cmpb $0xe9, (%rsi,%rcx,1)
    jne fail64
    incq %rcx
    cmpq $40, %rcx
    jb .Lelf_plan_invalid_unchanged
    cmpq $0, 0x601000
    jne fail64
    cmpq $0, 0x602000
    jne fail64
    leaq message_elf_plan_invalid(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_PLAN_NOOP
    cmpb $0xe9, elf_plan_out(%rip)
    jne fail64
    cmpb $0xe9, elf_plan_out+39(%rip)
    jne fail64
    leaq message_elf_plan_noop(%rip), %rsi
    call puts64
    jmp fail64
#endif
#ifdef HEPTAKERNEL_TEST_ELF_PLAN_DECOY
    addq $1, elf_plan_out(%rip)    /* hostile post-HIA coordinator write */
    cmpq $0x107c, elf_plan_out(%rip)
    jne fail64
    leaq message_elf_plan_decoy(%rip), %rsi
    call puts64
    jmp fail64
#endif
    cmpq $0x107b, elf_plan_out(%rip)
    jne fail64
    cmpq $3073, elf_plan_out+8(%rip)
    jne fail64
    cmpq $8192, elf_plan_out+16(%rip)
    jne fail64
    cmpq $123, elf_plan_out+24(%rip)
    jne fail64
    cmpq $0, elf_plan_out+32(%rip)
    jne fail64
    cmpq $0, elf_plan_selector(%rip)
    jne fail64
    cmpq $0, elf_plan_selector+8(%rip)
    jne fail64


    /* Fault injected AFTER full HIA ELF admission and successful HIA page
     * planning. This data-only edit preserves every ELF/PT_LOAD header:
     * both original modules would otherwise accept and copy the corruption. */
#if defined(HEPTAKERNEL_TEST_ELF_SNAPSHOT_MUTATED) || defined(HEPTAKERNEL_TEST_ELF_SNAPSHOT_LIAR)
    xorb $0x5a, elf_plan_staged+0x1200(%rip)
#endif
    movabsq $0xe9e9e9e9e9e9e9e9, %rax
    movq %rax, elf_plan_snapshot_receipt(%rip)
    movq %rax, elf_plan_snapshot_receipt+8(%rip)
    leaq elf_plan_image(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_staged(%rip), %rdx
    movl $7292, %ecx
    leaq elf_plan_snapshot_receipt(%rip), %r8
    movl $16, %r9d
    call elf_snapshot_f0    /* second genuine native HIA source equality gate */
#ifdef HEPTAKERNEL_TEST_ELF_SNAPSHOT_MUTATED
    cmpl $4, %eax
    jne fail64
    cmpb $0xe9, elf_plan_snapshot_receipt(%rip)
    jne fail64
    cmpb $0xe9, elf_plan_snapshot_receipt+15(%rip)
    jne fail64
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_snapshot_mutated(%rip), %rsi
    call puts64
    jmp fail64
#elif defined(HEPTAKERNEL_TEST_ELF_SNAPSHOT_LIAR)
    testl %eax, %eax
    jne fail64
    cmpb $0xa5, elf_plan_snapshot_receipt(%rip)
    jne fail64
    cmpb $0x5a, elf_plan_snapshot_receipt+1(%rip)
    jne fail64
    movzbl elf_plan_image+0x1200(%rip), %edx
    cmpb %dl, elf_plan_staged+0x1200(%rip)
    je fail64
    xorq %rax, %rax
    movq $0x601000, %rdi
    movl $1024, %ecx
    repe scasq
    jne fail64
    leaq message_elf_snapshot_liar(%rip), %rsi
    call puts64
    jmp fail64
#else
    testl %eax, %eax
    jne fail64
    cmpb $0xa5, elf_plan_snapshot_receipt(%rip)
    jne fail64
    cmpb $0x5a, elf_plan_snapshot_receipt+1(%rip)
    jne fail64
#endif

    /* The bridge constructs a copied envelope; HIA independently generated
     * its 40-byte prefix, and HIA alone writes the 4KiB physical page. */
    leaq elf_plan_out(%rip), %rsi
    leaq elf_plan_envelope(%rip), %rdi
    movl $40, %ecx
    rep movsb
    leaq elf_plan_staged(%rip), %rsi
    movl $7292, %ecx
    rep movsb
    movq $0x601000, %r14
    movq %r14, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq
    movq $0xa5, elf_plan_receipt(%rip)
    movq $0, elf_plan_receipt+8(%rip)
    leaq elf_plan_envelope(%rip), %rdi
    movl $7332, %esi
    leaq elf_plan_receipt(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
    call elf_page_f0        /* unchanged real HIA page fill */
    testl %eax, %eax
    jne fail64
    cmpq $0xa5, elf_plan_receipt(%rip)
    jne fail64
    cmpq $0, elf_plan_receipt+8(%rip)
    jne fail64
    xorq %r12, %r12
.Lelf_plan_file_page:
    xorq %r10, %r10
    cmpq $123, %r12
    jb .Lelf_plan_file_compare
    cmpq $3196, %r12
    jae .Lelf_plan_file_compare
    movq %r12, %r10
    subq $123, %r10
    andq $7, %r10
    leaq elf_page_pattern(%rip), %r11
    movzbl (%r11,%r10,1), %r10d
.Lelf_plan_file_compare:
    cmpb %r10b, (%r14,%r12,1)
    jne fail64
    incq %r12
    cmpq $4096, %r12
    jb .Lelf_plan_file_page

    /* Recompute second-page plan from the same ELF bytes, do not rewrite
     * page_index in the first HIA-produced plan. */
    movq $1, elf_plan_selector+8(%rip)
    leaq elf_plan_staged(%rip), %rdi
    movl $7292, %esi
    leaq elf_plan_selector(%rip), %rdx
    movl $16, %ecx
    leaq elf_plan_out(%rip), %r8
    movl $40, %r9d
    call elf_plan_f0
    testl %eax, %eax
    jne fail64
    cmpq $0x107b, elf_plan_out(%rip)
    jne fail64
    cmpq $3073, elf_plan_out+8(%rip)
    jne fail64
    cmpq $8192, elf_plan_out+16(%rip)
    jne fail64
    cmpq $123, elf_plan_out+24(%rip)
    jne fail64
    cmpq $1, elf_plan_out+32(%rip)
    jne fail64
    leaq elf_plan_out(%rip), %rsi
    leaq elf_plan_envelope(%rip), %rdi
    movl $40, %ecx
    rep movsb
    movq $0x602000, %r14
    movq %r14, %rdi
    movabsq $0xe7e7e7e7e7e7e7e7, %rax
    movl $512, %ecx
    rep stosq
    movq $0xa5, elf_plan_receipt(%rip)
    movq $0, elf_plan_receipt+8(%rip)
    leaq elf_plan_envelope(%rip), %rdi
    movl $7332, %esi
    leaq elf_plan_receipt(%rip), %rdx
    movl $16, %ecx
    movq %r14, %r8
    movl $4096, %r9d
    call elf_page_f0
    testl %eax, %eax
    jne fail64
    cmpq $0xa5, elf_plan_receipt(%rip)
    jne fail64
    cmpq $0, elf_plan_receipt+8(%rip)
    jne fail64
    xorq %rcx, %rcx
.Lelf_plan_bss_page:
    cmpb $0, (%r14,%rcx,1)
    jne fail64
    incq %rcx
    cmpq $4096, %rcx
    jb .Lelf_plan_bss_page

    /* Compare every original file byte (not merely the HIA return value)
     * and the guarded status, output and envelope regions. */
    movabsq $0x7c51df2948ea036b, %rax
    cmpq %rax, elf_plan_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_plan_guard_after(%rip)
    jne fail64
    cmpq %rax, elf_plan_env_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_plan_env_guard_after(%rip)
    jne fail64
    leaq elf_plan_image(%rip), %rsi
    leaq elf_plan_staged(%rip), %rdi
    movl $7292, %ecx
    repe cmpsb
    jne fail64
    leaq elf_plan_staged(%rip), %rsi
    leaq elf_plan_envelope+40(%rip), %rdi
    movl $7292, %ecx
    repe cmpsb
    jne fail64
    movabsq $0x7c51df2948ea036b, %rax
    cmpq %rax, elf_plan_stage_guard_before(%rip)
    jne fail64
    cmpq %rax, elf_plan_stage_guard_after(%rip)
    jne fail64
#ifdef HEPTAKERNEL_TEST_ELF_SOURCE_ISOLATED
    movzbl elf_plan_staged+0x1200(%rip), %eax
    cmpb %al, elf_plan_mutable+0x1200(%rip)
    je fail64
    leaq message_elf_source_isolated(%rip), %rsi
    call puts64
#endif
    leaq message_elf_plan_pass(%rip), %rsi
    call puts64
    ret
#endif
#endif

/* Input: physical base in rdi, page count in rsi. The existing bounded
 * firmware-record bytes at e820_request+24 remain unchanged. */
owner_admit64:
    pushq %r12
    movq %rsi, %r12                /* retain exact HIA admission page count */
    movq %rdi, e820_request(%rip)
    movq %rsi, e820_request+8(%rip)
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
    cmpq %r12, e820_reply+8(%rip) /* HIA reply must match this request */
    jne fail64
    popq %r12
    ret

/* Input: rdi=requested absolute page address, rsi=length in pages.
 * Return: the state address indexed by the real native HIA router. */
owner_route64:
    movq %rdi, owner_route_request+8(%rip)
    movq %rsi, owner_route_request+16(%rip)
    movq $-1, owner_route_reply(%rip)
    movq $-1, owner_route_reply+8(%rip)
    leaq owner_route_request(%rip), %rdi
    movl $80, %esi
    leaq owner_route_reply(%rip), %rdx
    movl $16, %ecx
    leaq owner_route_unused(%rip), %r8
    movl $16, %r9d
    call arena_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_route_reply(%rip)
    jne fail64
    movq owner_route_reply+8(%rip), %rax
    cmpq $1, %rax
    jb fail64
    cmpq $2, %rax
    ja fail64
    movabsq $0xa55aa55a5aa55aa5, %rdx
    cmpq %rdx, owner_route_guard_before(%rip)
    jne fail64
    cmpq %rdx, owner_route_guard_after(%rip)
    jne fail64
    cmpq %rdx, owner_route_unused(%rip)
    jne fail64
    decq %rax
    leaq owner_state_table(%rip), %rdx
    movq (%rdx,%rax,8), %rax
    ret

/* Input: rdi=24-byte trusted descriptor, rsi=HIA-initialized PMM state,
 * rdx=expected free frames. Actual native HIA object validates identity. */
owner_bind64:
    pushq %r12
    movq %rdx, %r12
    movq %rsi, %r8
    movq $-1, owner_alloc_reply(%rip)
    movq $-1, owner_alloc_reply+8(%rip)
    movl $24, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    movl $STATE_BYTES, %r9d
    call owner_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, owner_alloc_reply(%rip)
    jne fail64
    cmpq %r12, owner_alloc_reply+8(%rip)
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, owner_reply_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_reply_guard_after(%rip)
    jne fail64
    cmpq %rax, owner_a_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_a_guard_after(%rip)
    jne fail64
    cmpq %rax, owner_b_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_b_guard_after(%rip)
    jne fail64
    popq %r12
    ret

/* Input: rdi=immutable request, rsi=state chosen by HIA router,
 * rdx=independent expected status, rcx=expected value. */
owner_call64:
    pushq %r12
    pushq %r13
    movq %rdx, %r12
    movq %rcx, %r13
    movq %rsi, %r8
    movq $-1, owner_alloc_reply(%rip)
    movq $-1, owner_alloc_reply+8(%rip)
    movl $32, %esi
    leaq owner_alloc_reply(%rip), %rdx
    movl $16, %ecx
    movl $STATE_BYTES, %r9d
    call f0
    movl %eax, %eax
    cmpq %r12, %rax
    jne fail64
    cmpq %r12, owner_alloc_reply(%rip)
    jne fail64
    cmpq %r13, owner_alloc_reply+8(%rip)
    jne fail64
    movabsq $0xa55aa55a5aa55aa5, %rax
    cmpq %rax, owner_a_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_a_guard_after(%rip)
    jne fail64
    cmpq %rax, owner_b_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_b_guard_after(%rip)
    jne fail64
    cmpq %rax, owner_reply_guard_before(%rip)
    jne fail64
    cmpq %rax, owner_reply_guard_after(%rip)
    jne fail64
    popq %r13
    popq %r12
    ret

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
    .quad 0                        /* selector 0x20: 64-bit TSS low */
    .quad 0                        /* selector 0x20: 64-bit TSS high */
    .quad 0                        /* 0x33: HIA installs CPL3 code */
    .quad 0                        /* 0x3b: HIA installs CPL3 data */
    .quad 0                        /* 0x43: HIA installs SYSRETQ CPL3 code at 0x40 */
gdt_end:
gdt_descriptor:
    .word gdt_end - gdt - 1
    .long gdt
idt64_descriptor:
    .word 4095
    .quad idt64
message_tss_state_pass:
    .asciz "HEPTAKERNEL HIA LIVE TSS STATE VERIFIED\r\n"
message_tss_state_stale:
    .asciz "HEPTAKERNEL HIA TSS STATE STALE WORD REJECTED\r\n"
message_tss_rsp0_stale:
    .asciz "HEPTAKERNEL HIA TSS RSP0 STALE WORD REJECTED\r\n"
message_rsp0_switch:
    .asciz "HEPTAKERNEL HIA TSS RSP0 CPL3 HARDWARE SWITCH VERIFIED\r\n"
message_sysret_gdt:
    .asciz "HEPTAKERNEL HIA SYSRETQ GDT SLOT INSTALLED\r\n"
message_sysret_gdt_stale:
    .asciz "HEPTAKERNEL HIA SYSRETQ GDT STALE WORD REJECTED\r\n"
message_sysret_ring3:
    .asciz "HEPTAKERNEL HIA SYSRETQ CPL3 HARDWARE SWITCH VERIFIED\r\n"
message_sysret_rflags_bit3:
    .asciz "HEPTAKERNEL HIA SYSRETQ RESERVED RFLAGS BIT3 REJECTED\r\n"
message_syscall_msr_pass:
    .asciz "HEPTAKERNEL HIA LIVE SYSCALL MSR SNAPSHOT ADMITTED\r\n"
message_syscall_msr_stale:
    .asciz "HEPTAKERNEL HIA SYSCALL MSR STALE SNAPSHOT REJECTED\r\n"
message_syscall_roundtrip:
    .asciz "HEPTAKERNEL NON-HIA SYSCALL SYSRETQ HARDWARE ROUNDTRIP VERIFIED\r\n"
message_syscall_one_task_getpid:
    .asciz "HEPTAKERNEL HIA ONE-TASK GETPID HARDWARE RESULT VERIFIED\r\n"
message_syscall_one_task_enosys:
    .asciz "HEPTAKERNEL HIA ONE-TASK ENOSYS HARDWARE RESULT VERIFIED\r\n"
message_syscall_task_tid:
    .asciz "HEPTAKERNEL HIA TASK VIEW WORKER TID HARDWARE RESULT VERIFIED\r\n"
message_syscall_task_leader_stale:
    .asciz "HEPTAKERNEL HIA TASK VIEW MISSING LEADER REJECTED IN USER RAX\r\n"
message_syscall_life_spawned:
    .asciz "HEPTAKERNEL HIA TASK LIFECYCLE SPAWN USER GETTID VERIFIED\r\n"
message_syscall_life_retired:
    .asciz "HEPTAKERNEL HIA TASK LIFECYCLE RETIRE USER ESRCH VERIFIED\r\n"
message_syscall_life_stale:
    .asciz "HEPTAKERNEL HIA TASK LIFECYCLE STALE RETIRE PRESERVED USER TID\r\n"
message_syscall_stack_pass:
    .asciz "HEPTAKERNEL HIA SYSCALL KERNEL STACK ADMITTED\r\n"
message_syscall_stack_stale:
    .asciz "HEPTAKERNEL HIA SYSCALL KERNEL STACK STALE REJECTED\r\n"
message_syscall_stack_corrupt:
    .asciz "HEPTAKERNEL SYSCALL USER STACK CORRUPTION DETECTED\r\n"
message_syscall_frame_pass:
    .asciz "HEPTAKERNEL HIA SYSCALL RETURN FRAME ADMITTED\r\n"
message_syscall_frame_rcx_stale:
    .asciz "HEPTAKERNEL HIA SYSCALL RETURN RCX STALE REJECTED\r\n"
message_syscall_frame_r11_stale:
    .asciz "HEPTAKERNEL HIA SYSCALL RETURN R11 STALE REJECTED\r\n"
message_syscall_frame_rsp_stale:
    .asciz "HEPTAKERNEL HIA SYSCALL RETURN RSP STALE REJECTED\r\n"
message_us_initial:
    .asciz "HEPTAKERNEL HIA CPL3 USER FETCH BEFORE REVOKE VERIFIED\r\n"
message_us_live:
    .asciz "HEPTAKERNEL HIA LIVE PT USER REVOKE VERIFIED\r\n"
message_us_fault:
    .asciz "HEPTAKERNEL HIA PT USER REVOKE CPL3 FAULT VERIFIED\r\n"
message_us_stale:
    .asciz "HEPTAKERNEL HIA PT USER REVOKE STALE REJECTED\r\n"
message_us_bypass:
    .asciz "HEPTAKERNEL HIA PT USER REVOKE BYPASS EXECUTED\r\n"
message_rsp0_decoy:
    .asciz "HEPTAKERNEL HIA TSS RSP0 DECOY STACK DETECTED\r\n"
message_elf_stack_ring3:
    .asciz "HEPTAKERNEL HIA ELF64 STACK CPL3 AUXV READ VERIFIED\r\n"
message_elf_stack_ring3_decoy:
    .asciz "HEPTAKERNEL HIA ELF64 STACK CPL3 POSTWRITE DECOY OBSERVED\r\n"
message_elf_stack_iret_stale:
    .asciz "HEPTAKERNEL HIA IRET USER STACK RIP REFUSED BEFORE IRETQ\r\n"
message_elf_stack_iret_reserved_bit3:
    .asciz "HEPTAKERNEL HIA IRET RFLAGS RESERVED BIT3 REFUSED BEFORE IRETQ\r\n"
message_upper_pass:
    .asciz "HEPTAKERNEL HIA LIVE UPPER USER TABLE VERIFIED\r\n"
message_upper_stale:
    .asciz "HEPTAKERNEL HIA UPPER USER TABLE STALE OLD REJECTED\r\n"
message_pdpt_1g_warmed:
    .asciz "HEPTAKERNEL HIA 1G PDPTE HARDWARE ALIAS WARMED BEFORE UNMAP\r\n"
message_pdpt_1g_unmap_fault:
    .asciz "HEPTAKERNEL HIA 1G PDPTE REMOVAL HARDWARE FAULT VERIFIED\r\n"
message_pdpt_1g_unmap_stale:
    .asciz "HEPTAKERNEL HIA 1G PDPTE REMOVAL STALE OLD REJECTED\r\n"
message_pdpt_1g_unmap_bypass:
    .asciz "HEPTAKERNEL HIA 1G PDPTE REMOVAL BYPASS EXECUTED\r\n"
message_pdpt_1g_hw:
    .asciz "HEPTAKERNEL HIA 1G PDPTE HARDWARE ALIAS VERIFIED\r\n"
message_pdpt_1g_stale:
    .asciz "HEPTAKERNEL HIA 1G PDPTE STALE OLD REJECTED\r\n"
message_pdpt_1g_decoy:
    .asciz "HEPTAKERNEL HIA 1G PDPTE POSTWRITE DECOY DETECTED\r\n"
message_pde_2m_unmap_warmed:
    .asciz "HEPTAKERNEL HIA 2M PDE HARDWARE LEAF WARMED BEFORE UNMAP\r\n"
message_pde_2m_unmap_fault:
    .asciz "HEPTAKERNEL HIA 2M PDE REMOVAL HARDWARE FAULT VERIFIED\r\n"
message_pde_2m_unmap_stale:
    .asciz "HEPTAKERNEL HIA 2M PDE REMOVAL STALE OLD REJECTED\r\n"
message_pde_2m_unmap_bypass:
    .asciz "HEPTAKERNEL HIA 2M PDE REMOVAL BYPASS EXECUTED\r\n"
message_pde_2m_pass:
    .asciz "HEPTAKERNEL HIA LIVE USER 2M PDE VERIFIED\r\n"
message_pde_2m_stale:
    .asciz "HEPTAKERNEL HIA USER 2M PDE STALE OLD REJECTED\r\n"
message_user_gdt_pass:
    .asciz "HEPTAKERNEL HIA LIVE USER GDT VERIFIED\r\n"
message_user_gdt_stale:
    .asciz "HEPTAKERNEL HIA USER GDT STALE WORD REJECTED\r\n"
message_tss_gdt_pass:
    .asciz "HEPTAKERNEL HIA LIVE TSS GDT VERIFIED\r\n"
message_tss_gdt_stale:
    .asciz "HEPTAKERNEL HIA TSS GDT STALE WORD REJECTED\r\n"
message_idt_pass:
    .asciz "HEPTAKERNEL HIA LIVE IDT VERIFIED\r\n"
message_idt_stale_pass:
    .asciz "HEPTAKERNEL HIA IDT STALE WORD REJECTED\r\n"
message_ist_verified:
    .asciz "HEPTAKERNEL HIA IDT IST1 HARDWARE STACK VERIFIED\r\n"
message_map_pass:
    .asciz "HEPTAKERNEL HIA E820 VERIFIED\r\n"
message_reservation_pass:
    .asciz "HEPTAKERNEL HIA RESERVATIONS VERIFIED\r\n"
message_shadow_owner_hw:
    .asciz "HEPTAKERNEL HIA LIVE PMM SHADOW FRAME CPU PUBLISH VERIFIED\r\n"
message_shadow_owner_stale:
    .asciz "HEPTAKERNEL HIA LIVE SHADOW STALE PARENT REFUSED UNCHANGED\r\n"
message_shadow_owner_liar:
    .asciz "HEPTAKERNEL HIA LIVE SHADOW DISHONEST ADMIT DETECTED\r\n"
message_shadow_owner_bitmap:
    .asciz "HEPTAKERNEL HIA LIVE SHADOW MISSING PMM CLAIM REFUSED\r\n"
message_shadow_owner_recheck:
    .asciz "HEPTAKERNEL HIA LIVE SHADOW POSTADMIT PMM CHANGE REFUSED\r\n"
message_shadow_owner_free_stale:
    .asciz "HEPTAKERNEL HIA SHADOW COMPLETE PMM FREE COUNT STALE REFUSED\r\n"
message_shadow_owner_free_liar:
    .asciz "HEPTAKERNEL HIA SHADOW DISHONEST FULL PMM CHECK DETECTED\r\n"
message_shadow_owner_post_tail:
    .asciz "HEPTAKERNEL HIA SHADOW POSTSCAN TAIL CORRUPTION REJECTED\r\n"
message_shadow_owner_post_balanced:
    .asciz "HEPTAKERNEL HIA SHADOW POSTSCAN BALANCED MUTATION REJECTED\r\n"
message_pt_shadow_live:
    .asciz "HEPTAKERNEL HIA OFFLINE PT SHADOW HARDWARE VERIFIED\r\n"
message_pt_shadow_stale:
    .asciz "HEPTAKERNEL HIA OFFLINE PT SHADOW STALE SECOND REFUSED UNCHANGED\r\n"
message_pt_shadow_liar:
    .asciz "HEPTAKERNEL HIA OFFLINE PT SHADOW DISHONEST NOOP DETECTED\r\n"
message_pt_shadow_tamper:
    .asciz "HEPTAKERNEL HIA OFFLINE PT SHADOW POSTBUILD TAMPER DETECTED\r\n"
message_pt_pair_live:
    .asciz "HEPTAKERNEL HIA TWO PTE HARDWARE SWAPPED MAPPINGS VERIFIED\r\n"
message_pt_pair_stale:
    .asciz "HEPTAKERNEL HIA TWO PTE STALE SECOND REFUSED UNCHANGED\r\n"
message_pt_pair_liar:
    .asciz "HEPTAKERNEL HIA TWO PTE DISHONEST NOOP DETECTED\r\n"
message_pt_commit_pass:
    .asciz "HEPTAKERNEL HIA PT COMMIT VERIFIED\r\n"
message_pt_nx_pass:
    .asciz "HEPTAKERNEL HIA LIVE PT NX PROTECT VERIFIED\r\n"
message_pt_nx_fault:
    .asciz "HEPTAKERNEL HIA PT NX HARDWARE FETCH FAULT VERIFIED\r\n"
message_pt_nx_stale:
    .asciz "HEPTAKERNEL HIA PT NX STALE OLD REJECTED\r\n"
message_pt_nx_bypass:
    .asciz "HEPTAKERNEL HIA PT NX BYPASS EXECUTED\r\n"
message_cow_pte_mapped:
    .asciz "HEPTAKERNEL HIA COW PTE SOURCE MAPPING VERIFIED\r\n"
message_cow_pte_fault_observed:
    .asciz "HEPTAKERNEL COW PTE REAL WRITE PROTECT FAULT OBSERVED\r\n"
message_cow_pte_remap_success:
    .asciz "HEPTAKERNEL HIA COW PTE HARDWARE REMAP AND PHYSICAL RAM VERIFIED\r\n"
message_cow_pte_stale:
    .asciz "HEPTAKERNEL HIA COW PTE STALE EXPECTED OLD REJECTED\r\n"
message_cow_pte_dishonest:
    .asciz "HEPTAKERNEL HIA COW PTE DISHONEST NOOP REJECTED\r\n"
message_cow_pte_bypass:
    .asciz "HEPTAKERNEL HIA COW PTE RESTORE BYPASS REFAULT VERIFIED\r\n"
message_dual_pass:
    .asciz "HEPTAKERNEL HIA DUAL PMM PHYSICAL PAGES AND TWO-ZONE EXHAUSTION VERIFIED\r\n"
message_dual_release:
    .asciz "HEPTAKERNEL HIA DUAL PMM RELEASE DOUBLE FREE AND RECLAIM VERIFIED\r\n"
message_dual_scrub:
    .asciz "HEPTAKERNEL HIA DUAL PMM NATIVE SCRUB AND ZEROED RECLAIM VERIFIED\r\n"
message_dual_native_scrub:
    .asciz "HEPTAKERNEL HIA NATIVE SINGLE CALL SCRUB RELEASE AND ZEROED RECLAIM VERIFIED\r\n"
message_dual_native_scrub_noop:
    .asciz "HEPTAKERNEL HIA NATIVE SINGLE CALL SCRUB RELEASE DISHONEST NOOP DETECTED\r\n"
message_dual_native_claim:
    .asciz "HEPTAKERNEL HIA NATIVE SINGLE CALL SCRUB CLAIM PHYSICAL ZERO VERIFIED\r\n"
message_dual_native_claim_noop:
    .asciz "HEPTAKERNEL HIA NATIVE SINGLE CALL SCRUB CLAIM DISHONEST NOOP DETECTED\r\n"
message_dual_scrub_bypass:
    .asciz "HEPTAKERNEL HIA DUAL PMM SCRUB BYPASS DETECTED\r\n"
message_dual_scrub_decoy:
    .asciz "HEPTAKERNEL HIA DUAL PMM POST SCRUB RAM DECOY DETECTED\r\n"
message_dual_stale:
    .asciz "HEPTAKERNEL HIA DUAL PMM STALE FREE REFUSED UNCHANGED\r\n"
message_dual_liar:
    .asciz "HEPTAKERNEL HIA DUAL PMM DISHONEST SUCCESS DETECTED\r\n"
message_dual_decoy:
    .asciz "HEPTAKERNEL HIA DUAL PMM POSTCLAIM RAM DECOY DETECTED\r\n"
message_pmm_bitmap_live:
    .asciz "HEPTAKERNEL HIA PMM LIVE COMPLETE BITMAP VERIFIED\r\n"
message_pmm_bitmap_free_stale:
    .asciz "HEPTAKERNEL HIA PMM STALE FREE COUNT REFUSED UNCHANGED\r\n"
message_pmm_bitmap_reserved_missing:
    .asciz "HEPTAKERNEL HIA PMM MISSING RESERVED BIT REFUSED UNCHANGED\r\n"
message_pmm_bitmap_tail_dirty:
    .asciz "HEPTAKERNEL HIA PMM TAIL BIT REFUSED UNCHANGED\r\n"
message_pmm_bitmap_noop:
    .asciz "HEPTAKERNEL HIA PMM DISHONEST ACCEPT DETECTED\r\n"
message_cow_frame_binding_live:
    .asciz "HEPTAKERNEL HIA COW FRAME BINDING LIVE PMM PTE VERIFIED\r\n"
message_cow_frame_binding_bitmap:
    .asciz "HEPTAKERNEL HIA COW FRAME BINDING BITMAP REFUSED UNCHANGED\r\n"
message_cow_frame_binding_pte_stale:
    .asciz "HEPTAKERNEL HIA COW FRAME BINDING STALE PTE REFUSED UNCHANGED\r\n"
message_cow_frame_binding_noop:
    .asciz "HEPTAKERNEL HIA COW FRAME BINDING DISHONEST ACCEPT DETECTED\r\n"
message_cow_pmm_reissued:
    .asciz "HEPTAKERNEL HIA COW PMM FRAME FREED REISSUED ZERO VERIFIED\r\n"
message_cow_pmm_double_free:
    .asciz "HEPTAKERNEL HIA COW PMM DOUBLE FREE REFUSED STATE UNCHANGED\r\n"
message_cow_integrated_aborted:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED LATE PTE REJECT ABORT ZERO COUNTS RESTORED\r\n"
message_cow_integrated_guard_refused:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED LIVE PTE GUARDED ABORT REFUSED UNCHANGED\r\n"
message_cow_integrated_abort_rejected:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED ABORT DISHONEST OR CORRUPT REJECTED\r\n"
message_cow_integrated_prepared:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED PAGE COPY AND COUNTS VERIFIED\r\n"
message_cow_integrated_verified:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED PF COPY REFCOUNT PTE VERIFIED\r\n"
message_cow_integrated_stale:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED STALE REFCOUNT REFUSED\r\n"
message_cow_integrated_rejected:
    .asciz "HEPTAKERNEL HIA COW INTEGRATED DISHONEST OR CORRUPT COPY REJECTED\r\n"
message_pt_protect_pass:
    .asciz "HEPTAKERNEL HIA LIVE PT WRITE PROTECT VERIFIED\r\n"
message_pt_protect_fault:
    .asciz "HEPTAKERNEL HIA PT WRITE PROTECT HARDWARE FAULT VERIFIED\r\n"
message_pt_protect_stale:
    .asciz "HEPTAKERNEL HIA PT WRITE PROTECT STALE OLD REJECTED\r\n"
message_pt_protect_bypass:
    .asciz "HEPTAKERNEL HIA PT WRITE PROTECT BYPASS STORED\r\n"
message_pt_revoke_pass:
    .asciz "HEPTAKERNEL HIA LIVE PT REVOKE VERIFIED\r\n"
message_pt_revoke_fault:
    .asciz "HEPTAKERNEL HIA PT REVOKE HARDWARE FAULT VERIFIED\r\n"
message_pt_revoke_stale:
    .asciz "HEPTAKERNEL HIA PT REVOKE STALE OLD REJECTED\r\n"
message_pt_revoke_bypass:
    .asciz "HEPTAKERNEL HIA PT REVOKE BYPASS READ VERIFIED\r\n"
message_pf_admission_pass:
    .asciz "HEPTAKERNEL HIA PF RECORD ADMITTED\r\n"
message_pte_pass:
    .asciz "HEPTAKERNEL HIA LIVE PTE VERIFIED\r\n"
message_nx_fault_pass:
    .asciz "HEPTAKERNEL HIA NX FETCH FAULT VERIFIED\r\n"
message_nx_bypass_pass:
    .asciz "HEPTAKERNEL HIA NX BYPASS EXECUTED\r\n"
message_wp_fault_pass:
    .asciz "HEPTAKERNEL HIA SUPERVISOR WRITE-PROTECT FAULT VERIFIED\r\n"
message_wp_bypass_pass:
    .asciz "HEPTAKERNEL HIA WRITE-PROTECT BYPASS STORED\r\n"
message_router_pass:
    .asciz "HEPTAKERNEL HIA ARENA ROUTER VERIFIED\r\n"
message_owner_pass:
    .asciz "HEPTAKERNEL HIA MULTI-ARENA OWNERSHIP VERIFIED\r\n"
message_cow_refcount_hw_pass:
    .asciz "HEPTAKERNEL HIA COW REFCOUNT QEMU TRANSITIONS VERIFIED\r\n"
message_cow_refcount_stale:
    .asciz "HEPTAKERNEL HIA COW REFCOUNT STALE EXPECTED-OLD REFUSED\r\n"
message_cow_split_hw_pass:
    .asciz "HEPTAKERNEL HIA COW SPLIT PHYSICAL RAM AND COUNTS VERIFIED\r\n"
message_cow_split_stale:
    .asciz "HEPTAKERNEL HIA COW SPLIT STALE EXPECTED-OLD REFUSED\r\n"
message_elf_stack_pass:
    .asciz "HEPTAKERNEL HIA ELF64 INITIAL STACK PHYSICAL SUFFIX VERIFIED\r\n"
message_elf_stack_bad_phent:
    .asciz "HEPTAKERNEL HIA ELF64 STACK BAD PHENT REFUSED UNCHANGED\r\n"
message_elf_stack_entry_collision:
    .asciz "HEPTAKERNEL HIA ELF64 STACK ENTRY COLLISION REFUSED UNCHANGED\r\n"
message_elf_stack_phdr_collision:
    .asciz "HEPTAKERNEL HIA ELF64 STACK PHDR COLLISION REFUSED UNCHANGED\r\n"
message_elf_stack_liar:
    .asciz "HEPTAKERNEL HIA ELF64 STACK DISHONEST NOOP DETECTED\r\n"
message_elf_stack_decoy:
    .asciz "HEPTAKERNEL HIA ELF64 STACK POSTWRITE DECOY DETECTED\r\n"
message_elf_hw_pass:
    .asciz "HEPTAKERNEL HIA ELF64 PMM PHYSICAL PAGE FILE BSS VERIFIED\\r\\n"
message_elf_hw_truncated:
    .asciz "HEPTAKERNEL HIA ELF64 TRUNCATED REFUSED PHYSICAL UNCHANGED\\r\\n"
message_elf_hw_noop:
    .asciz "HEPTAKERNEL HIA ELF64 DISHONEST NOOP PHYSICAL MISMATCH DETECTED\\r\\n"
message_elf_hw_decoy:
    .asciz "HEPTAKERNEL HIA ELF64 POST-CALL PHYSICAL DECOY DETECTED\\r\\n"

message_elf_layout_overlap:
    .asciz "HEPTAKERNEL HIA ELF64 FULL LAYOUT OVERLAP REFUSED PHYSICAL UNCHANGED\r\n"
message_elf_layout_liar:
    .asciz "HEPTAKERNEL HIA ELF64 DISHONEST FULL LAYOUT ACCEPT DETECTED\r\n"
message_elf_snapshot_mutated:
    .asciz "HEPTAKERNEL HIA ELF64 POST PLAN PAYLOAD MUTATION REFUSED PHYSICAL UNCHANGED\r\n"
message_elf_snapshot_liar:
    .asciz "HEPTAKERNEL HIA ELF64 DISHONEST SNAPSHOT EQUALITY DETECTED\r\n"
message_elf_stage_noop:
    .asciz "HEPTAKERNEL HIA ELF64 DISHONEST STAGE NO-COPY DETECTED PHYSICAL UNCHANGED\r\n"
message_elf_stage_corrupt:
    .asciz "HEPTAKERNEL HIA ELF64 STAGED PAYLOAD CORRUPTION REFUSED PHYSICAL UNCHANGED\r\n"
message_elf_source_isolated:
    .asciz "HEPTAKERNEL HIA ELF64 STAGED SOURCE MUTATION ISOLATED\r\n"
message_elf_plan_pass:
    .asciz "HEPTAKERNEL HIA ELF64 NATIVE PLAN PHYSICAL FILE BSS VERIFIED\r\n"
message_elf_plan_invalid:
    .asciz "HEPTAKERNEL HIA ELF64 INVALID PLAN REFUSED PHYSICAL UNCHANGED\r\n"
message_elf_plan_noop:
    .asciz "HEPTAKERNEL HIA ELF64 DISHONEST PLAN NOOP DETECTED\r\n"
message_elf_plan_decoy:
    .asciz "HEPTAKERNEL HIA ELF64 POST PLAN DECOY DETECTED\r\n"
message_page_copy_hw_pass:
    .asciz "HEPTAKERNEL HIA PHYSICAL PAGE COPY TWO PAIRS VERIFIED\r\n"
message_page_copy_detach_pass:
    .asciz "HEPTAKERNEL HIA PHYSICAL COPY DETACH ZERO VERIFIED\r\n"
message_page_zero_hw_pass:
    .asciz "HEPTAKERNEL HIA PHYSICAL PAGE ZERO FOUR FRAMES VERIFIED\r\n"
message_page_zero_recycle_pass:
    .asciz "HEPTAKERNEL HIA PHYSICAL PAGE REUSE SCRUB VERIFIED\r\n"
root_live_message:
    .asciz "HEPTAKERNEL HIA LIVE CR3 ROOT PAGE VERIFIED\r\n"
root_unsafe_message:
    .asciz "HEPTAKERNEL HIA CR3 ROOT UNSAFE ACCEPT DETECTED\r\n"
root_spoof_message:
    .asciz "HEPTAKERNEL HIA CR3 ROOT SPOOF REFUSED BY OBSERVER\r\n"
message_cr3_live:
    .asciz "HEPTAKERNEL HIA CR3 LIVE CPU SNAPSHOT VERIFIED\r\n"
message_cr3_unsafe:
    .asciz "HEPTAKERNEL HIA CR3 DISHONEST BYPASS DETECTED\r\n"
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
elf_stack_expected_words:
    .quad 0, 0, 0, 3, 0x400040, 4, 56, 5
    .quad 3, 6, 4096, 9, 0x401000, 0, 0, 0
elf_page_pattern:
    .byte 0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88
.balign 8

/* Synthetic ELF64 ET_EXEC PT_LOAD admission fixture, non-HIA test data.
 * p_offset 0x107b congruent to p_vaddr 0x40107b, file 3073, mem 8192.
 * Bytes after the 123-byte leading zero region match elf_page_pattern. */
.balign 8
elf_plan_image:
    .byte 0x7f, 0x45, 0x4c, 0x46, 2, 1, 1, 0
    .fill 8,1,0
    .short 2, 62
    .long 1
    .quad 0x40107b, 64, 0
    .long 0
    .short 64, 56, 1, 0, 0, 0
    .long 1, 5
    .quad 0x107b, 0x40107b, 0, 3073, 8192, 4096
    .fill (0x107b - (. - elf_plan_image)),1,0
    .rept 384
        .byte 0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88
    .endr
    .byte 0x11
elf_plan_image_end:
.if (elf_plan_image_end - elf_plan_image) != 7292
.error "ELF64 PT_LOAD fixture byte length mismatch"
.endif

elf_page_fixture:
    .quad 7, 3073, 8192, 123, 0
    .fill 7,1,0xe9
    .rept 384
        .byte 0x11,0x22,0x33,0x44,0x55,0x66,0x77,0x88
    .endr
    .byte 0x11
elf_page_fixture_end:
.if (elf_page_fixture_end - elf_page_fixture) != 3120
.error "ELF page fill physical fixture length mismatch"
.endif
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

.balign 8
/* Non-HIA fixture. Both eight-page zones have a reserved first page.
 * The native HIA receives the disjoint 130-byte mutable copy. */
.balign 8
dual_claim_seed:
    .quad 3552580688320940353, 8, 0x500000, 1, 7
    .zero 24
    .byte 1
    .quad 3552580688320940353, 8, 0x700000, 1, 7
    .zero 24
    .byte 1
dual_claim_seed_end:
.if (dual_claim_seed_end - dual_claim_seed) != 130
.error "dual PMM fixture must have exact 130-byte layout"
.endif

arena_cases:
    /* Independent router fixture 0: op, address, pages, arenas, status/value. */
    .quad 0, 0, 0, 2
    .quad 0x400000, 512, 0
    .quad 6291456, 512, 1
    .quad 0, 2
    /* Independent router fixture 1: op, address, pages, arenas, status/value. */
    .quad 1, 4194304, 1, 2
    .quad 0x400000, 512, 0
    .quad 6291456, 512, 1
    .quad 0, 1
    /* Independent router fixture 2: op, address, pages, arenas, status/value. */
    .quad 1, 6295552, 1, 2
    .quad 0x400000, 512, 0
    .quad 6291456, 512, 1
    .quad 0, 2
    /* Independent router fixture 3: op, address, pages, arenas, status/value. */
    .quad 1, 6291456, 1, 2
    .quad 0x400000, 512, 0
    .quad 6291456, 512, 1
    .quad 5, 0
    /* Independent router fixture 4: op, address, pages, arenas, status/value. */
    .quad 1, 6287360, 2, 2
    .quad 0x400000, 512, 0
    .quad 6291456, 512, 1
    .quad 5, 0
    /* Independent router fixture 5: op, address, pages, arenas, status/value. */
    .quad 0, 0, 0, 2
    .quad 0x400000, 512, 0
    .quad 5242880, 512, 1
    .quad 6, 0
    /* Native HIA first-fit: align 4 pages, two-page span after 3 reserved. */
    .quad 2, 4, 2, 2
    .quad 0x400000, 512, 3
    .quad 0x600000, 512, 1
    .quad 0, 0x404000
    /* First region is exhausted: second region at aligned absolute page. */
    .quad 2, 8, 3, 2
    .quad 0x400000, 2, 2
    .quad 0x600000, 17, 1
    .quad 0, 0x608000
    /* Both regions lack enough pages: never return a partial candidate. */
    .quad 2, 2, 4, 2
    .quad 0x400000, 2, 1
    .quad 0x600000, 2, 1
    .quad 5, 0
arena_cases_end:
.if ((arena_cases_end - arena_cases) != 864)
.error "arena fixture length must be exactly 9 records"
.endif


/* Two physically disjoint, explicitly E820-admitted regions. Addresses and
 * expected HIA outcomes are fixed independent observer fixtures. */
.balign 8
owner_descriptors:
    .quad 0x400000, 17, 2
    .quad 0x600000, 17, 1
cow_refcount_hw_slots:
    .word 2, 17
page_copy_hw_pairs:
    .quad 0x402000, 0x601000, 0x125a73de6789abcd
    .quad 0x403000, 0x602000, 0x39be1247f0ca8865
page_zero_hw_physical_pages:
    .quad 0x402000, 0x403000, 0x601000, 0x602000
owner_state_table:
    .quad owner_a_state, owner_b_state
owner_init_a:    .quad 0, 17, 0x400000, 2
owner_init_b:    .quad 0, 17, 0x600000, 1
owner_alloc_two: .quad 4, 2, 1, 0
owner_cow_free_target: .quad 2, 0x602000, 0, 0
owner_cow_reallocate: .quad 1, 1, 0, 0
owner_claim_a:   .quad 6, 0x402000, 1, 0
owner_claim_b:   .quad 6, 0x601000, 1, 0
owner_query_a:   .quad 7, 0x402000, 2, 0
owner_query_b:   .quad 7, 0x601000, 2, 0
owner_free_a:    .quad 5, 0x402000, 2, 0
owner_free_b:    .quad 5, 0x601000, 2, 0
owner_count:     .quad 3, 0, 0, 0

.section .bss.boot,"aw",@nobits
.balign 4096
pml4:             .skip 4096
pdpt:             .skip 4096
page_directory:   .skip 4096
page_table_4m:    .skip 4096
idt64:            .skip 4096
.balign 16
tss64:            .skip 104
.balign 16
ist_stack_base:   .skip 8192
ist_stack_top:
.balign 16
rsp0_decoy_stack_base: .skip 8192
rsp0_decoy_stack_top:
.balign 16
.balign 4096
root_copy:       .skip 4096
.balign 16
root_request:    .skip 24
root_reply:      .skip 16
tss_state_request: .skip 40
tss_state_reply:   .skip 16
upper_user_request: .skip 24
upper_user_reply:   .skip 16
pde_2m_request:  .skip 32
pde_2m_reply:    .skip 16
pde_2m_unmap_old:  .skip 8
pde_2m_unmap_armed: .skip 8
pdpt_1g_request: .skip 32
pdpt_1g_reply:   .skip 16
pdpt_1g_unmap_old:   .skip 8
pdpt_1g_unmap_armed: .skip 8
user_gdt_request: .skip 16
user_gdt_reply:   .skip 16
sysret_gdt_request: .skip 16
sysret_gdt_reply:   .skip 16
syscall_expected_lstar: .skip 8
syscall_user_rsp: .skip 8
syscall_saved_rcx: .skip 8
syscall_saved_r11: .skip 8
syscall_number: .skip 8
syscall_result: .skip 8
syscall_task_request: .skip 16
syscall_task_reply: .skip 8
syscall_task_snapshot: .skip 64  /* two fixture records, not real tasks */
syscall_task_life_request: .skip 32
syscall_task_life_reply: .skip 8
tss_gdt_request:  .skip 32
tss_gdt_reply:    .skip 16
idt_gate_request: .skip 40
idt_gate_reply:   .skip 16
.balign 16
state_guard_before: .skip 8
allocator_state:    .skip STATE_BYTES
state_guard_after:  .skip 8
reply_guard_before: .skip 8
reply:              .skip 16
reply_guard_after:  .skip 8
.balign 8
boot_magic:       .skip 4
pte_caps:         .skip 4
boot_info:        .skip 4
mmap_end32:       .skip 4
.balign 8
e820_request:     .skip (24 + 128 * 24)
e820_reply:       .skip 16
e820_unused:      .skip 16
.balign 16
reservation_request:      .skip 96
reservation_guard_before: .skip 8
reservation_reply:        .skip 16
reservation_guard_after:  .skip 8
reservation_unused:       .skip 16
/* Input snapshot and private aligned live-shadow candidate are disjoint. */
.balign 8
pt_shadow_hw_request: .skip 4160
pt_shadow_hw_receipt: .skip 16
shadow_owner_request:  .skip 64
shadow_owner_reply:    .skip 16
.balign 4096
pt_shadow_hw_table:   .skip 4096
pt_pair_hw_request: .skip 64
pt_pair_hw_receipt: .skip 16
pt_commit_request: .skip 32
pt_commit_reply:   .skip 16
pt_nx_request:       .skip 32
pt_nx_reply:         .skip 16
pt_nx_observed:      .skip 8
pt_nx_armed:         .skip 8
cow_pte_request:      .skip 32
cow_pte_reply:        .skip 16
cow_pte_old:          .skip 8
cow_pte_stage:        .skip 8
cow_pte_fault_rsp:    .skip 8
cow_pte_saved_rdi:    .skip 8
cow_pte_saved_r10:    .skip 8
/* Isolated 4KiB COW refcount table. Not a PMM-owned mapping authority. */
cow_integrated_guard_before: .skip 8
.balign 4096
cow_integrated_state:        .skip 4096
cow_integrated_guard_after:  .skip 8
/* 48-byte HIA request; actual current PTE and HIA PMM are NOT snapshots. */
pmm_bitmap_live_request: .skip 24
pmm_bitmap_live_unused: .skip 8
cow_frame_binding_request: .skip 48
.balign 16
cow_frame_binding_snapshot: .skip STATE_BYTES
/* Non-HIA independent full-byte pre-refusal snapshot. */
.balign 4096
cow_integrated_guard_snapshot: .skip 4096
pt_protect_request:  .skip 32
pt_protect_reply:    .skip 16
pt_protect_observed: .skip 8
pt_protect_armed:    .skip 8
pt_revoke_request: .skip 32
pt_revoke_reply:   .skip 16
pt_revoke_observed: .skip 8
pt_revoke_armed:    .skip 8
us_request:      .skip 32
us_reply:        .skip 16
us_stage:        .skip 8
pte_request:      .skip 32
pte_guard_before: .skip 8
pte_reply:        .skip 16
pte_guard_after:  .skip 8
pte_unused:       .skip 16
pf_guard_before:  .skip 8
pf_request:       .skip 72
pf_reply:         .skip 16
pf_guard_after:   .skip 8
pf_unused:        .skip 16
pte_nx_armed:     .skip 8
pte_wp_armed:     .skip 8
/* Disjoint fixture buffers and sentinels: never alias borrowed HIA slices. */
.balign 8
dual_claim_guard_before:       .skip 8
dual_claim_state:              .skip 130
dual_claim_guard_after:        .skip 8
dual_claim_reply_guard_before: .skip 8
dual_claim_reply:              .skip 16
dual_claim_reply_guard_after:  .skip 8
dual_claim_expected:           .skip 130
dual_claim_empty_request:      .skip 1
.balign 8
dual_claim_release_request:    .skip 8
dual_claim_scrub_guard_before: .skip 8
dual_claim_scrub_reply:        .skip 16
dual_claim_scrub_guard_after:  .skip 8
arena_guard_before: .skip 8
arena_reply:       .skip 16
arena_guard_after: .skip 8
arena_unused:      .skip 16
/* Private state per region; the immutable state table binds HIA route IDs. */
.balign 16
owner_a_guard_before: .skip 8
owner_a_state:        .skip STATE_BYTES
owner_a_guard_after:  .skip 8
owner_b_guard_before: .skip 8
owner_b_state:        .skip STATE_BYTES
owner_b_guard_after:  .skip 8
owner_reply_guard_before: .skip 8
owner_alloc_reply:       .skip 16
owner_reply_guard_after:  .skip 8
owner_route_guard_before: .skip 8
owner_route_reply:        .skip 16
owner_route_guard_after:  .skip 8
owner_route_unused:       .skip 16
owner_route_request:      .skip 80
owner_choice_a:           .skip 8
owner_choice_b:           .skip 8
.balign 8
/* A real guest-RAM 4096-byte table; the bridge is an observer only. */
.balign 8
cow_refcount_hw_guard_before: .skip 8
.balign 4096
cow_refcount_hw_table:        .skip 4096
cow_refcount_hw_guard_after:  .skip 8
cow_refcount_hw_request:      .skip 16
cow_refcount_hw_reply:        .skip 16
/* Test-only 4096-byte table and independent guard words. */
cow_split_hw_guard_before: .skip 8
.balign 4096
cow_split_hw_table:        .skip 4096
cow_split_hw_guard_after:  .skip 8
page_copy_hw_guard_before: .skip 8
page_copy_hw_reply:        .skip 16
page_copy_hw_guard_after:  .skip 8
page_zero_hw_guard_before: .skip 8
page_zero_hw_reply:        .skip 16
page_zero_hw_guard_after:  .skip 8
page_zero_hw_empty_request: .skip 1

/* Separate, isolated real HIA ELF plan -> physical page experiment. */
.balign 8
elf_plan_guard_before: .skip 8
elf_plan_mutable: .skip 7292
elf_plan_guard_after: .skip 8
elf_plan_stage_guard_before: .skip 8
elf_plan_staged: .skip 7292
elf_plan_stage_guard_after: .skip 8
elf_plan_stage_receipt: .skip 16
elf_plan_selector: .skip 16
elf_plan_out: .skip 40
elf_plan_snapshot_receipt: .skip 16
elf_plan_env_guard_before: .skip 8
elf_plan_envelope: .skip 7332
elf_plan_env_guard_after: .skip 8
elf_plan_receipt: .skip 16

/* The NON-HIA fixture is mutable; only genuine HIA fills allocated RAM. */
.balign 8
elf_hw_guard_before: .skip 8
elf_hw_envelope: .skip 3120
elf_hw_guard_after: .skip 8
elf_hw_receipt_guard_before: .skip 8
elf_hw_receipt: .skip 16
elf_hw_receipt_guard_after: .skip 8
.balign 8
elf_stack_request: .skip 40
elf_stack_receipt: .skip 16
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
