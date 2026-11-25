/* NON-HIA Multiboot and independent PIT reference observer.
 * f0 arms the masked APIC countdown; f1 samples and stops it. */
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

    /* Preserve a genuinely stopped, masked original timer. */
    movl 0x320(%r12),%eax
    movl %eax,old_timer_lvt(%rip)
    testl $0x10000,%eax
    jz abort
    movl 0x3e0(%r12),%eax
    movl %eax,old_timer_div(%rip)
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    movl $0x10051,0x320(%r12)
    movl $0,0x3e0(%r12)
    cmpl $0x10051,0x320(%r12)
    jne abort
    cmpl $0,0x3e0(%r12)
    jne abort
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort

    inb $0x61,%al
    movb %al,saved_port61(%rip)
    movl $12000,%r15d
    call sample
#if defined(HIA_TEST_DIV_NOP) || defined(HIA_TEST_COUNT_NOP) || defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_STALE) || defined(HIA_TEST_STOP_COUNT_NOP)
    jmp done
#endif
    movl %eax,short_native(%rip)
    movl %edx,short_reference(%rip)
    movl $24000,%r15d
    call sample
    movl %eax,long_native(%rip)
    movl %edx,long_reference(%rip)
    /* For two independent PIT windows, doubled time implies comparable rate.
     * Accept a wide bounded ratio [1.5,2.5], with integer arithmetic. */
    movl short_reference(%rip),%eax
    movl long_reference(%rip),%edx
    leaq (%rax,%rax,2),%rcx
    addq %rdx,%rdx
    cmpq %rcx,%rdx
    jb abort
    leaq (%rax,%rax,4),%rcx
    cmpq %rcx,%rdx
    ja abort
    /* Emit actual measurements, not a precomputed expected frequency. */
    movl short_native(%rip),%eax
    call print_hex
    movl short_reference(%rip),%eax
    call print_hex
    movl long_native(%rip),%eax
    call print_hex
    movl long_reference(%rip),%eax
    call print_hex
    movb $'P',%bl
done:
    movb saved_port61(%rip),%al
    outb %al,$0x61
    jmp verify_local
sample:
    /* PIT reference starts only after the masked APIC has been armed. */
    inb $0x61,%al
    andb $0xfc,%al
    outb %al,$0x61
    movb $0xb0,%al
    outb %al,$0x43
    movw %r15w,%ax
    outb %al,$0x42
    movb %ah,%al
    outb %al,$0x42
    inb $0x61,%al
    testb $0x20,%al
    jnz abort
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl $0x10051,%edx
    xorl %ecx,%ecx
#ifdef HIA_TEST_BAD_BASE
    incq %rdi
#elif defined(HIA_TEST_STALE)
    xorq $0x100,%rsi
#endif
    subq $8,%rsp
    call f0
    addq $8,%rsp
#if defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_STALE) || defined(HIA_TEST_DIV_NOP) || defined(HIA_TEST_COUNT_NOP)
#ifdef HIA_TEST_BAD_BASE
    cmpq $6,%rax
    movb $'B',%bl
#elif defined(HIA_TEST_STALE)
    cmpq $9,%rax
    movb $'S',%bl
#elif defined(HIA_TEST_DIV_NOP)
    cmpq $13,%rax
    movb $'V',%bl
#else
    cmpq $15,%rax
    movb $'N',%bl
#endif
    jne abort
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
#if defined(HIA_TEST_COUNT_NOP)
    cmpl $3,0x3e0(%r12)
#else
    cmpl $0,0x3e0(%r12)
#endif
    jne abort
    ret
#else
    testq %rax,%rax
    jnz abort
    cmpl $3,0x3e0(%r12)
    jne abort
    cmpl $0x10051,0x320(%r12)
    jne abort
    cmpl $-1,0x380(%r12)
    jne abort
    movl 0x390(%r12),%r13d
    testl %r13d,%r13d
    jz abort
    inb $0x61,%al
    orb $1,%al
    outb %al,$0x61
    movl $0x40000000,%ecx
pit_wait:
    inb $0x61,%al
    testb $0x20,%al
    jnz pit_done
    decl %ecx
    jnz pit_wait
    jmp abort
pit_done:
    movl 0x390(%r12),%r14d
    testl %r14d,%r14d
    jz abort
    cmpl %r13d,%r14d
    jae abort
    /* Stop/sample rejects a stale MSR without changing initial count. */
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    xorq $0x100,%rsi
    subq $8,%rsp
    call f1
    addq $8,%rsp
    testl %eax,%eax
    jnz abort
    cmpl $-1,0x380(%r12)
    jne abort
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    subq $8,%rsp
    call f1
    addq $8,%rsp
#ifdef HIA_TEST_STOP_COUNT_NOP
    testl %eax,%eax
    jnz abort
    cmpl $-1,0x380(%r12)
    jne abort
    movl $0,0x380(%r12)
    movb $'Y',%bl
    ret
#else
    testl %eax,%eax
    jz abort
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    /* Native elapsed >= independently sampled total, and overhead <= 25%.
     * The second comparison uses only the actual PIT-window difference. */
    movl $-1,%edx
    subl %r14d,%edx
    cmpl %edx,%eax
    jb abort
    movl %r13d,%edx
    subl %r14d,%edx
    movl %edx,%ecx
    shrl $2,%ecx
    addl %edx,%ecx
    cmpl %ecx,%eax
    ja abort
    movl $0,0x3e0(%r12)
    ret
#endif
#endif
print_hex:
    movl %eax,%ecx
    movl $8,%r8d
    movw $0xe9,%dx
hex_loop:
    roll $4,%ecx
    movl %ecx,%eax
    andb $15,%al
    addb $'0',%al
    cmpb $'9',%al
    jbe hex_emit
    addb $7,%al
hex_emit:
    outb %al,%dx
    decl %r8d
    jnz hex_loop
    ret
verify_local:
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    /* Independent teardown; no HIA teardown claimed. */
    movl $0x10051,0x320(%r12)
    movl $0,0x380(%r12)
    movl old_timer_div(%rip),%eax
    movl %eax,0x3e0(%r12)
    cmpl 0x3e0(%r12),%eax
    jne abort
    movl old_timer_lvt(%rip),%eax
    movl %eax,0x320(%r12)
    cmpl 0x320(%r12),%eax
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    jmp restore
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
/* Unexpected timer vector is a test failure; no IRQ entry is claimed. */
.balign 16
ipi_handler:
    jmp abort
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

.balign 4
old_timer_lvt: .skip 4
old_timer_div: .skip 4

.balign 1
saved_port61: .skip 1

.balign 4
short_native: .skip 4
short_reference: .skip 4
long_native: .skip 4
long_reference: .skip 4
