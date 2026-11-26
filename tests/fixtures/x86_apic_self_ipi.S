/* NON-HIA Multiboot and independent interrupt observer. Only f0 (send)
 * and f1 (EOI) are the native HIA device subject. */
.set MB_MAGIC,0x1badb002
.set MB_FLAGS,3
.set APIC,0xfee00000
.set VEC,0x51
.set VBIT,0x20000
.section .multiboot,"a",@progbits
.balign 4
.long MB_MAGIC,MB_FLAGS,-(MB_MAGIC+MB_FLAGS)
.section .text.boot,"ax",@progbits
.code32
.global _start
_start:
    cli
    cld
    cmpl $0x2badb002,%eax
    jne fail32
    lgdt gdt_ptr
    ljmp $0x08,$protected32
protected32:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    movl $stack32_top,%esp
    xorl %eax,%eax
    movl $pml4,%edi
    movl $4096,%ecx
    rep stosl
    movl $pdpt,%eax
    orl $3,%eax
    movl %eax,pml4
    movl $pd0,%eax
    orl $3,%eax
    movl %eax,pdpt
    movl $pd3,%eax
    orl $3,%eax
    movl %eax,pdpt+3*8
    movl $pd0,%edi
    movl $0x83,%eax
    movl $512,%ecx
1:  movl %eax,(%edi)
    movl $0,4(%edi)
    addl $0x200000,%eax
    addl $8,%edi
    loop 1b
    /* PCD/PWT UC, 2 MiB identity-mapped APIC aperture, supervisor only. */
    movl $0xfee0009b,pd3+503*8
    movl %cr4,%eax
    orl $0x20,%eax
    movl %eax,%cr4
    movl $pml4,%eax
    movl %eax,%cr3
    movl $0xc0000080,%ecx
    rdmsr
    orl $0x100,%eax
    wrmsr
    movl %cr0,%eax
    orl $0x80010000,%eax
    movl %eax,%cr0
    ljmp $0x18,$long64
fail32:
    movl $0x12,%eax
    movw $0xf4,%dx
    outl %eax,%dx
1:  cli
    hlt
    jmp 1b
.code64
long64:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    leaq stack64_top(%rip),%rsp
    movl $27,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    movq %rax,saved_apic_msr(%rip)
    movq %rax,%rcx
    andq $0xc00,%rcx
    cmpq $0x800,%rcx
    jne abort
    andq $-4096,%rax
    movabsq $APIC,%r12
    cmpq %r12,%rax
    jne abort
    inb $0x21,%al
    movb %al,old_pic1(%rip)
    inb $0xa1,%al
    movb %al,old_pic2(%rip)
    movb $0xff,%al
    outb %al,$0x21
    outb %al,$0xa1
    movl 0xf0(%r12),%eax
    movl %eax,old_svr(%rip)
    movl 0x80(%r12),%eax
    movl %eax,old_tpr(%rip)
    movl $0x1ff,0xf0(%r12)
    movl $0,0x80(%r12)
    leaq ipi_handler(%rip),%rax
    leaq idt+VEC*16(%rip),%rdi
    movw %ax,(%rdi)
    movw $0x18,2(%rdi)
    movb $0,4(%rdi)
    movb $0x8e,5(%rdi)
    shrq $16,%rax
    movw %ax,6(%rdi)
    shrq $16,%rax
    movl %eax,8(%rdi)
    movl $0,12(%rdi)
    lidt idt_ptr(%rip)
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl $VEC,%edx
#ifdef HIA_TEST_BAD_BASE
    incq %rdi
#elif defined(HIA_TEST_STALE)
    xorq $0x100,%rsi
#elif defined(HIA_TEST_VECTOR)
    incl %edx
#elif defined(HIA_TEST_DISABLED)
    movl $0xff,0xf0(%r12)
#elif defined(HIA_TEST_PRIORITY)
    movl $0x50,0x80(%r12)
#elif defined(HIA_TEST_PENDING)
    movl $0x40051,0x300(%r12)
    testl $VBIT,0x220(%r12)
    jz abort
#elif defined(HIA_TEST_EOI_EMPTY)
    call f1
    cmpq $11,%rax
    jne abort
    testl $VBIT,0x120(%r12)
    jnz abort
    movb $'E',%bl
    jmp restore
#endif
    call f0
#if defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_VECTOR)
    cmpq $6,%rax
    jne abort
    movb $'B',%bl
#elif defined(HIA_TEST_STALE)
    cmpq $9,%rax
    jne abort
    movb $'S',%bl
#elif defined(HIA_TEST_DISABLED) || defined(HIA_TEST_PRIORITY)
    cmpq $10,%rax
    jne abort
    movb $'D',%bl
#elif defined(HIA_TEST_SEND_NOP)
    cmpq $13,%rax
    jne abort
    movb $'N',%bl
#elif defined(HIA_TEST_PENDING)
    cmpq $11,%rax
    jne abort
    movb $'R',%bl
    jmp delivery
#else
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_EOI_NOP
    movb $'M',%bl
#else
    movb $'P',%bl
#endif
    jmp delivery
#endif
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    jmp restore
delivery:
    testl $VBIT,0x220(%r12)
    jz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    sti
    hlt
    cli
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $0,handler_bad(%rip)
    jne abort
#ifdef HIA_TEST_EOI_NOP
    cmpq $13,eoi_status(%rip)
#else
    cmpq $0,eoi_status(%rip)
#endif
    jne abort
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
restore:
    movl old_tpr(%rip),%eax
    movl %eax,0x80(%r12)
    cmpl 0x80(%r12),%eax
    jne abort
    movl old_svr(%rip),%eax
    movl %eax,0xf0(%r12)
    cmpl 0xf0(%r12),%eax
    jne abort
    movb old_pic1(%rip),%al
    outb %al,$0x21
    movb old_pic2(%rip),%al
    outb %al,$0xa1
    movl $27,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    cmpq saved_apic_msr(%rip),%rax
    jne abort
    movl $0x10,%eax
    cmpb $'P',%bl
    je finish
    movl $0x11,%eax
    jmp finish
/* Explicitly NON-HIA entry and IRETQ. Save every GPR used by the
 * call ABI, align the supervisor stack, and check the real ISR bit. */
.balign 16
ipi_handler:
    pushq %rax
    pushq %rbx
    pushq %rcx
    pushq %rdx
    pushq %rsi
    pushq %rdi
    pushq %rbp
    pushq %r8
    pushq %r9
    pushq %r10
    pushq %r11
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq %rsp,%rbp
    andq $-16,%rsp
    movabsq $APIC,%r12
    incq interrupt_count(%rip)
    testl $VBIT,0x120(%r12)
    jz handler_fail
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    call f1
    movq %rax,eoi_status(%rip)
#ifdef HIA_TEST_EOI_NOP
    cmpq $13,%rax
    jne handler_fail
    testl $VBIT,0x120(%r12)
    jz handler_fail
    /* Cleanup solely for the intentionally broken HIA object. */
    movl $0,0xb0(%r12)
#else
    testq %rax,%rax
    jnz handler_fail
#endif
    testl $VBIT,0x120(%r12)
    jnz handler_fail
    jmp handler_return
handler_fail:
    incq handler_bad(%rip)
    movl $0,0xb0(%r12)
handler_return:
    movq %rbp,%rsp
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %r11
    popq %r10
    popq %r9
    popq %r8
    popq %rbp
    popq %rdi
    popq %rsi
    popq %rdx
    popq %rcx
    popq %rbx
    popq %rax
    iretq
abort:
    movb $'A',%bl
    movl $0x12,%eax
finish:
    pushq %rax
    movw $0xe9,%dx
    movb %bl,%al
    outb %al,%dx
    popq %rax
    movw $0xf4,%dx
    outl %eax,%dx
1:  cli
    hlt
    jmp 1b
.section .rodata,"a",@progbits
.balign 8
gdt:
    .quad 0,0x00cf9a000000ffff,0x00cf92000000ffff,0x00af9a000000ffff
gdt_end:
gdt_ptr:
    .word gdt_end-gdt-1
    .long gdt
idt_ptr:
    .word 4095
    .quad idt
.section .bss,"aw",@nobits
.balign 4096
pml4: .skip 4096
pdpt: .skip 4096
pd0: .skip 4096
pd3: .skip 4096
idt: .skip 4096
.balign 16
stack32: .skip 4096
stack32_top:
stack64: .skip 8192
stack64_top:
.balign 8
saved_apic_msr: .skip 8
interrupt_count: .skip 8
handler_bad: .skip 8
eoi_status: .skip 8
old_svr: .skip 4
old_tpr: .skip 4
old_pic1: .skip 1
old_pic2: .skip 1
