/* NON-HIA isolated Multiboot observer. Only f0 is the HIA subject.
 * No production kernel, privilege authority or Linux ABI closure. */
.set MB_MAGIC, 0x1badb002
.set MB_FLAGS, 3
.section .multiboot,"a",@progbits
.balign 4
.long MB_MAGIC, MB_FLAGS, -(MB_MAGIC+MB_FLAGS)
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
    movl $pd0,%edi
    movl $0x83,%eax
    movl $512,%ecx
1:
    movl %eax,(%edi)
    movl $0,4(%edi)
    addl $0x200000,%eax
    addl $8,%edi
    loop 1b
    movl $pt,%eax
    orl $3,%eax
    movl %eax,pd0+16
    movl $0x400003,pt
    movl $0x80000000,pt+4
    movl %cr4,%eax
    orl $0x20,%eax
    movl %eax,%cr4
    movl $pml4,%eax
    movl %eax,%cr3
    movl $0xc0000080,%ecx
    rdmsr
    orl $0x900,%eax
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
long64:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    leaq stack64_top(%rip),%rsp
    leaq pf_handler(%rip),%rax
    leaq idt+14*16(%rip),%rdi
    movw %ax,(%rdi)
    movw $0x18,2(%rdi)
    movb $0,4(%rdi)
    movb $0x8e,5(%rdi)
    shrq $16,%rax
    movw %ax,6(%rdi)
    shrq $16,%rax
    movl %eax,8(%rdi)
    movl $0,12(%rdi)
    lidt idtr(%rip)
    /* Independently follow actual CR3 and hardware page-table pointers. */
    movq %cr3,%rax
    andq $-4096,%rax
    leaq pml4(%rip),%rdi
    cmpq %rdi,%rax
    jne abort
    movq (%rax),%rax
    andq $-4096,%rax
    leaq pdpt(%rip),%rdi
    cmpq %rdi,%rax
    jne abort
    movq (%rax),%rax
    andq $-4096,%rax
    leaq pd0(%rip),%rdi
    cmpq %rdi,%rax
    jne abort
    movq 16(%rax),%rax
    testq $0x80,%rax
    jnz abort
    andq $-4096,%rax
    leaq pt(%rip),%rdi
    cmpq %rdi,%rax
    jne abort
    /* Discover actual CPUID physical width and enabled NX/WP state. */
    movl $0x80000008,%eax
    cpuid
    andl $255,%eax
    movl %eax,%r14d
    orl $256,%r14d
    movl $0xc0000080,%ecx
    rdmsr
    testl $0x800,%eax
    jz abort
    movq %cr0,%rax
    testq $0x10000,%rax
    jz abort
    movq $0x400000,%rbx
    movabsq $0x123456789abcdef0,%r15
    movq %r15,(%rbx)
    cmpq %r15,(%rbx)
    jne abort
    /* CPU A/D must already be present before selecting the exact expected old. */
    movq pt(%rip),%r12
    movq %r12,%rax
    andq $0x63,%rax
    cmpq $0x63,%rax
    jne abort
    movq %r12,%r13
    subq $2,%r13
    leaq pt(%rip),%rdi
    movq %rbx,%rsi
    movq %r12,%rdx
    movq %r14,%rcx
#ifdef HIA_TEST_STALE
    xorq $0x20,%rdx
#endif
#ifdef HIA_TEST_BAD_CAPS
    andq $255,%rcx
#endif
#ifdef HIA_TEST_BAD_ADDRESS
    incq %rdi
#endif
    call f0
    /* Every unrelated PTE must remain untouched. */
    leaq pt+8(%rip),%rdi
    movl $511,%ecx
2:  cmpq $0,(%rdi)
    jne abort
    addq $8,%rdi
    loop 2b
#ifdef HIA_TEST_STALE
    cmpq $9,%rax
    jne abort
    cmpq %r12,pt(%rip)
    jne abort
    movb $'S',%bl
    jmp writable
#elif defined(HIA_TEST_BAD_CAPS)
    cmpq $8,%rax
    jne abort
    cmpq %r12,pt(%rip)
    jne abort
    movb $'C',%bl
    jmp writable
#elif defined(HIA_TEST_BAD_ADDRESS)
    cmpq $6,%rax
    jne abort
    cmpq %r12,pt(%rip)
    jne abort
    movb $'B',%bl
    jmp writable
#else
    testq %rax,%rax
    jnz abort
    cmpq %r13,pt(%rip)
    je changed
    /* LOCK CAS deleted: returned success without changing the real PTE. */
    cmpq %r12,pt(%rip)
    jne abort
    movb $'N',%bl
    jmp writable
changed:
    cmpq %r15,0x400000
    jne abort
#ifdef HIA_TEST_RESTORE
    /* Explicit observer bypass after the genuine HIA CAS. */
    movq %r12,pt(%rip)
    movq $0x400000,%rax
    invlpg (%rax)
    movb $'R',%bl
    jmp writable
#endif
    movq $1,armed(%rip)
    movabsq $0x0badf00dcafebeef,%rax
probe_write:
    movq %rax,0x400000
    jmp abort
#endif
#if defined(HIA_TEST_STALE) || defined(HIA_TEST_BAD_CAPS) || defined(HIA_TEST_BAD_ADDRESS)
probe_write:
    jmp abort
#endif
writable:
    movabsq $0x0badf00dcafebeef,%rax
    movq %rax,0x400000
    cmpq %rax,0x400000
    jne abort
    cmpq %r12,pt(%rip)
    jne abort
    movl $0x11,%eax
    jmp finish
pf_handler:
    cmpq $1,armed(%rip)
    jne abort
    cmpq $3,(%rsp)
    jne abort
    movq %cr2,%rax
    cmpq $0x400000,%rax
    jne abort
    leaq probe_write(%rip),%rax
    cmpq %rax,8(%rsp)
    jne abort
    cmpq %r13,pt(%rip)
    jne abort
    cmpq %r15,0x400000
    jne abort
    movb $'P',%bl
    movl $0x10,%eax
    jmp finish
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
gdt_end:
gdt_ptr:
    .word gdt_end-gdt-1
    .long gdt
idtr:
    .word 4096-1
    .quad idt
.section .bss,"aw",@nobits
.balign 4096
pml4: .skip 4096
pdpt: .skip 4096
pd0: .skip 4096
pt: .skip 4096
.balign 16
stack32: .skip 4096
stack32_top:
stack64: .skip 8192
stack64_top:
idt: .skip 4096
armed: .skip 8
