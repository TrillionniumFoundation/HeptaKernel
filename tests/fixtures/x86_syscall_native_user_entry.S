/* Independent NON-HIA bootstrap and SYSCALL/#UD observer. HIA owns
 * ordered MSR initialization, IDTR load and terminal user entry. */
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
    sidt old_idtr(%rip)
    leaq ud_handler(%rip),%rax
    leaq idt+6*16(%rip),%rdi
    movw %ax,(%rdi)
    movw $0x18,2(%rdi)
    movb $0,4(%rdi)
    movb $0x8e,5(%rdi)
    shrq $16,%rax
    movw %ax,6(%rdi)
    shrq $16,%rax
    movl %eax,8(%rdi)
    movl $0,12(%rdi)
    leaq new_idtr(%rip),%rdi
    call hia_idtr_load
    leaq new_idtr(%rip),%rcx
    cmpq %rcx,%rax
    jne abort
    sidt current_idtr(%rip)
#ifdef HIA_TEST_IDTR_NOP
    movw old_idtr(%rip),%ax
    cmpw %ax,current_idtr(%rip)
    jne abort
    movq old_idtr+2(%rip),%rax
    cmpq %rax,current_idtr+2(%rip)
    jne abort
    leaq idt(%rip),%rax
    cmpq %rax,current_idtr+2(%rip)
    je abort
    movb $'D',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpw $4095,current_idtr(%rip)
    jne abort
    leaq idt(%rip),%rax
    cmpq %rax,current_idtr+2(%rip)
    jne abort
#endif
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
    movq old_efer(%rip),%rdx
    movq old_star(%rip),%rcx
    movq old_fmask(%rip),%r8
#ifdef HIA_TEST_STALE
    xorq $16,%rdi
#elif defined(HIA_TEST_STALE_EFER)
    xorq $1,%rdx
#elif defined(HIA_TEST_STALE_STAR)
    xorq $1,%rcx
#elif defined(HIA_TEST_STALE_FMASK)
    xorq $1,%r8
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
    /* Independent readback of every register. NOP mutations must stop
     * at the affected write, leaving SCE disabled and later MSRs intact. */
    get_msr 0xc0000080
    movq old_efer(%rip),%r8
#if defined(HIA_TEST_ACTIVE) || (!defined(HIA_TEST_STALE) && !defined(HIA_TEST_STALE_EFER) && !defined(HIA_TEST_STALE_STAR) && !defined(HIA_TEST_STALE_FMASK) && !defined(HIA_TEST_NONCANONICAL) && !defined(HIA_TEST_UNALIGNED) && !defined(HIA_TEST_NOP_STAGE))
    orq $1,%r8
#endif
    cmpq %r8,%rax
    jne abort
    get_msr 0xc0000081
#if (defined(HIA_TEST_NOP_STAGE) && HIA_TEST_NOP_STAGE >= 2) || (!defined(HIA_TEST_NOP_STAGE) && !defined(HIA_TEST_STALE) && !defined(HIA_TEST_STALE_EFER) && !defined(HIA_TEST_STALE_STAR) && !defined(HIA_TEST_STALE_FMASK) && !defined(HIA_TEST_NONCANONICAL) && !defined(HIA_TEST_UNALIGNED) && !defined(HIA_TEST_ACTIVE))
    movabsq $0x0000001800000000,%r8
#else
    movq old_star(%rip),%r8
#endif
    cmpq %r8,%rax
    jne abort
    get_msr 0xc0000084
#if (defined(HIA_TEST_NOP_STAGE) && HIA_TEST_NOP_STAGE >= 3) || (!defined(HIA_TEST_NOP_STAGE) && !defined(HIA_TEST_STALE) && !defined(HIA_TEST_STALE_EFER) && !defined(HIA_TEST_STALE_STAR) && !defined(HIA_TEST_STALE_FMASK) && !defined(HIA_TEST_NONCANONICAL) && !defined(HIA_TEST_UNALIGNED) && !defined(HIA_TEST_ACTIVE))
    movq $513,%r8
#else
    movq old_fmask(%rip),%r8
#endif
    cmpq %r8,%rax
    jne abort
    get_msr 0xc0000082
#if (defined(HIA_TEST_NOP_STAGE) && HIA_TEST_NOP_STAGE >= 1) || (!defined(HIA_TEST_NOP_STAGE) && !defined(HIA_TEST_STALE) && !defined(HIA_TEST_STALE_EFER) && !defined(HIA_TEST_STALE_STAR) && !defined(HIA_TEST_STALE_FMASK) && !defined(HIA_TEST_NONCANONICAL) && !defined(HIA_TEST_UNALIGNED) && !defined(HIA_TEST_ACTIVE))
    cmpq desired_lstar(%rip),%rax
#else
    cmpq old_lstar(%rip),%rax
#endif
    jne abort
#if defined(HIA_TEST_STALE) || defined(HIA_TEST_STALE_EFER) || defined(HIA_TEST_STALE_STAR) || defined(HIA_TEST_STALE_FMASK)
    cmpq $9,%r13
    jne abort
    movb $'S',%bl
    jmp restore
#elif defined(HIA_TEST_ACTIVE)
    cmpq $8,%r13
    jne abort
    movb $'E',%bl
    jmp restore
#elif defined(HIA_TEST_NOP_STAGE)
    cmpq $10,%r13
    jne abort
    movb $'N',%bl
    jmp restore
#elif defined(HIA_TEST_NONCANONICAL) || defined(HIA_TEST_UNALIGNED)
    cmpq $6,%r13
    jne abort
    movb $'B',%bl
    jmp restore
#else
    testq %r13,%r13
    jnz abort
    /* Terminal user transition is owned by the native HIA object. */
    movq $0x400000,%rdi
    movl $0x2b,%esi
    movl $3,%edx
    movq $0x700000,%rcx
    movl $0x33,%r8d
#ifdef HIA_TEST_BAD_IRET_FLAGS
    movl $0x3002,%edx
#endif
    call hia_user_iretq
    jmp abort
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
#ifdef HIA_TEST_IRET_TRAP_DELTA
    jmp abort
#endif
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
    jmp restore
ud_handler:
#ifdef HIA_TEST_IRET_TRAP_DELTA
    leaq hia_user_iretq(%rip),%rax
    addq $HIA_TEST_IRET_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpw $0x18,8(%rsp)
    jne abort
    leaq stack64_top(%rip),%rsp
#ifdef HIA_TEST_IRET_NOP
    movb $'N',%bl
#else
    movb $'T',%bl
#endif
    jmp restore
#else
    jmp abort
#endif
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
    /* Restore the original IDTR in the independent observer. */
    lidt old_idtr(%rip)
    sidt current_idtr(%rip)
    movw old_idtr(%rip),%ax
    cmpw %ax,current_idtr(%rip)
    jne abort
    movq old_idtr+2(%rip),%rax
    cmpq %rax,current_idtr+2(%rip)
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
.balign 16
new_idtr:
    .word 4095
    .quad idt
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
.balign 4096
idt: .skip 4096
.balign 16
old_idtr: .skip 16
current_idtr: .skip 16
