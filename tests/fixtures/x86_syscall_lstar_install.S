/* NON-HIA guest-only bootstrap and independent observer.
 * The actual LSTAR transition is the compiled HIA f0 subject. */
.set MB_MAGIC,0x1badb002
.set MB_FLAGS,3
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
    movl $3072,%ecx
    rep stosl
    movl $pdpt,%eax
    orl $7,%eax
    movl %eax,pml4
    andl $-5,%eax
    movl %eax,pml4+256*8
    movl $pd0,%eax
    orl $7,%eax
    movl %eax,pdpt
    movl $pd0,%edi
    movl $0x83,%eax
    movl $512,%ecx
1:  movl %eax,(%edi)
    movl $0,4(%edi)
    addl $0x200000,%eax
    addl $8,%edi
    loop 1b
    /* User RX code and separate RW/NX stack; all kernel leaves supervisor. */
    movl $0x400085,pd0+2*8
    movl $0x600087,pd0+3*8
    movl $0x80000000,pd0+3*8+4
    movl $user_payload,%esi
    movl $0x400000,%edi
    movl $(user_end-user_payload),%ecx
    rep movsb
    movl %cr4,%eax
    orl $0x20,%eax
    movl %eax,%cr4
    movl $pml4,%eax
    movl %eax,%cr3
    movl $0xc0000080,%ecx
    rdmsr
    orl $0x900,%eax
    andl $-2,%eax
    wrmsr
    movl %cr0,%eax
    orl $0x80010000,%eax
    movl %eax,%cr0
    ljmp $0x18,$long64
fail32:
    movl $0x12,%eax
    movw $0xf4,%dx
    outl %eax,%dx
    cli
1:  hlt
    jmp 1b
.code64
.macro get_msr index
    movl $\index,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
.endm
.macro put_msr index
    movq %rax,%rdx
    shrq $32,%rdx
    movl $\index,%ecx
    wrmsr
.endm
long64:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    leaq stack64_top(%rip),%rsp
    get_msr 0xc0000080
    movq %rax,old_efer(%rip)
    testq $1,%rax
    jnz abort
    get_msr 0xc0000081
    movq %rax,old_star(%rip)
    get_msr 0xc0000084
    movq %rax,old_fmask(%rip)
    get_msr 0xc0000082
    movq %rax,old_lstar(%rip)
    movq %rax,%rdi
    movabsq $0xffff800000000000,%r12
    movabsq $syscall_entry,%rsi
    orq %r12,%rsi
    movq %rsi,desired_lstar(%rip)
    cmpq %rdi,%rsi
    je abort
#ifdef HIA_TEST_STALE
    xorq $16,%rdi
#elif defined(HIA_TEST_NONCANONICAL)
    movabsq $0x0000800000000000,%rsi
#elif defined(HIA_TEST_UNALIGNED)
    incq %rsi
#elif defined(HIA_TEST_ACTIVE)
    movq old_efer(%rip),%rax
    orq $1,%rax
    put_msr 0xc0000080
#endif
    call f0
    movq %rax,%r13
    /* No other MSR may change during the HIA transition. */
    get_msr 0xc0000080
    movq old_efer(%rip),%r8
#ifdef HIA_TEST_ACTIVE
    orq $1,%r8
#endif
    cmpq %r8,%rax
    jne abort
    get_msr 0xc0000081
    cmpq old_star(%rip),%rax
    jne abort
    get_msr 0xc0000084
    cmpq old_fmask(%rip),%rax
    jne abort
    get_msr 0xc0000082
#if defined(HIA_TEST_STALE) || defined(HIA_TEST_NONCANONICAL) || defined(HIA_TEST_UNALIGNED) || defined(HIA_TEST_ACTIVE) || defined(HIA_TEST_NO_WRITE)
    cmpq old_lstar(%rip),%rax
    jne abort
#ifdef HIA_TEST_STALE
    cmpq $9,%r13
    jne abort
    movb $'S',%bl
#elif defined(HIA_TEST_ACTIVE)
    cmpq $8,%r13
    jne abort
    movb $'E',%bl
#elif defined(HIA_TEST_NO_WRITE)
    cmpq $10,%r13
    jne abort
    movb $'N',%bl
#else
    cmpq $6,%r13
    jne abort
    movb $'B',%bl
#endif
    jmp restore
#else
    testq %r13,%r13
    jnz abort
    cmpq desired_lstar(%rip),%rax
    jne abort
    /* Only these remaining MSR setup operations and IRETQ are observer
     * code. The subject wrote the actual LSTAR used by SYSCALL. */
    movabsq $0x0000001800000000,%rax
    put_msr 0xc0000081
    movq $1,%rax
    put_msr 0xc0000084
    movq old_efer(%rip),%rax
    orq $1,%rax
    put_msr 0xc0000080
    pushq $0x33
    pushq $0x700000
    pushq $3
    pushq $0x2b
    pushq $0x400000
    iretq
#endif
.balign 16
syscall_entry:
    /* Hardware does not switch the user stack. Before any stack access
     * capture the user state and switch to a supervisor-only stack. */
    movq %rsp,%r12
    movq %rcx,%r13
    movq %r11,%r14
    leaq stack64_top(%rip),%rsp
    pushfq
    popq %r15
    cmpq $0x13579bdf,%rax
    jne abort
    cmpw $0x2b,%dx
    jne abort
    cmpw $0x33,%si
    jne abort
    cmpq $0x700000,%r12
    jne abort
    cmpq $(0x400000+user_after-user_payload),%r13
    jne abort
    andq $0x203,%r14
    cmpq $3,%r14
    jne abort
    testq $0x201,%r15
    jnz abort
    xorq %rax,%rax
    movw %cs,%ax
    cmpq $0x18,%rax
    jne abort
    movw %ss,%ax
    cmpq $0x20,%rax
    jne abort
    leaq syscall_entry(%rip),%r8
    cmpq desired_lstar(%rip),%r8
    jne abort
    get_msr 0xc0000082
    cmpq desired_lstar(%rip),%rax
    jne abort
    movb $'P',%bl
restore:
    movq old_efer(%rip),%rax
    put_msr 0xc0000080
    movq old_lstar(%rip),%rax
    put_msr 0xc0000082
    movq old_star(%rip),%rax
    put_msr 0xc0000081
    movq old_fmask(%rip),%rax
    put_msr 0xc0000084
    get_msr 0xc0000080
    cmpq old_efer(%rip),%rax
    jne abort
    get_msr 0xc0000082
    cmpq old_lstar(%rip),%rax
    jne abort
    get_msr 0xc0000081
    cmpq old_star(%rip),%rax
    jne abort
    get_msr 0xc0000084
    cmpq old_fmask(%rip),%rax
    jne abort
    movl $0x10,%eax
    cmpb $'P',%bl
    je finish
    movl $0x11,%eax
    jmp finish
.global abort
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
    cli
1:  hlt
    jmp 1b
.section .rodata,"a",@progbits
.balign 8
gdt:
    .quad 0,0x00cf9a000000ffff,0x00cf92000000ffff,0x00af9a000000ffff
    .quad 0x00cf92000000ffff,0x00affa000000ffff,0x00cff2000000ffff
gdt_end:
gdt_ptr:
    .word gdt_end-gdt-1
    .long gdt
user_payload:
    movw %cs,%dx
    movw %ss,%si
    movl $0x13579bdf,%eax
    syscall
user_after:
    ud2
user_end:
.section .bss,"aw",@nobits
.balign 4096
pml4: .skip 4096
pdpt: .skip 4096
pd0: .skip 4096
.balign 16
stack32: .skip 4096
stack32_top:
stack64: .skip 8192
stack64_top:
.balign 8
old_efer: .skip 8
old_star: .skip 8
old_lstar: .skip 8
old_fmask: .skip 8
desired_lstar: .skip 8

