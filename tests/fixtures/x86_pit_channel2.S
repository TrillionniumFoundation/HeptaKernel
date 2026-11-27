/* NON-HIA independent PIT observer. The HIA subject owns PIT programming. */
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
    movq %rax,%rcx
    andq $0xc00,%rcx
    cmpq $0x800,%rcx
    jne abort
    andq $-4096,%rax
    movabsq $APIC,%r12
    cmpq %r12,%rax
    jne abort
    movl 0xf0(%r12),%eax
    movl %eax,old_svr(%rip)
    movl $0x1ff,0xf0(%r12)
    movl 0x320(%r12),%eax
    movl %eax,old_lvt(%rip)
    testl $0x10000,%eax
    jz abort
    movl 0x3e0(%r12),%eax
    movl %eax,old_div(%rip)
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    movl $0x10051,0x320(%r12)
    movl $3,0x3e0(%r12)
    cmpl $3,0x3e0(%r12)
    jne abort
    inb $0x61,%al
    movb %al,old_gate(%rip)
    andb $0xfc,%al
    outb %al,$0x61
    /* Give the independent oracle a known stopped mode-0 count, distinct
     * from both HIA counts. This also makes deleted writes observable. */
    movb $0xb0,%al
    outb %al,$0x43
    movb $0x37,%al
    outb %al,$0x42
    movb $0x49,%al
    outb %al,$0x42
    call latch_count
    cmpw $0x4937,%ax
    ja abort
    cmpw $0x3937,%ax
    jb abort
    movl $0,%edi
    call f0
    cmpq $6,%rax
    jne abort
    movl $1023,%edi
    call f0
    cmpq $6,%rax
    jne abort
    movl $60001,%edi
    call f0
    cmpq $6,%rax
    jne abort
    call latch_count
    cmpw $0x4937,%ax
    ja abort
    cmpw $0x3937,%ax
    jb abort
    xorq %rdi,%rdi
    call f2
    cmpq $6,%rax
    jne abort
    movl $1,%edi
    call f2
    cmpq $9,%rax
    jne abort
    call f3
    cmpq $9,%rax
    jne abort
    /* Speaker-on state is refused without changing count or speaker bit. */
    inb $0x61,%al
    orb $2,%al
    outb %al,$0x61
    movl $12000,%edi
    call f0
    cmpq $9,%rax
    jne abort
    call f1
    cmpq $9,%rax
    jne abort
    call f3
    cmpq $9,%rax
    jne abort
    inb $0x61,%al
    andb $3,%al
    cmpb $2,%al
    jne abort
    call latch_count
    cmpw $0x4937,%ax
    ja abort
    cmpw $0x3937,%ax
    jb abort
    inb $0x61,%al
    andb $0xfc,%al
    outb %al,$0x61
    movl $12000,%r15d
    call sample
#ifdef HIA_TEST_PIT_LOAD_NOP
    movb $'L',%bl
    jmp cleanup
#elif defined(HIA_TEST_PIT_START_NOP)
    movb $'S',%bl
    jmp cleanup
#elif defined(HIA_TEST_PIT_WAIT_NOP)
    movb $'W',%bl
    jmp cleanup
#elif defined(HIA_TEST_PIT_STOP_NOP)
    movb $'T',%bl
    jmp cleanup
#else
    movl %eax,short_elapsed(%rip)
    movl $24000,%r15d
    call sample
    movl %eax,long_elapsed(%rip)
    /* Compare independent elapsed APIC counts with widened arithmetic. */
    movl short_elapsed(%rip),%eax
    movl long_elapsed(%rip),%edx
    testq %rax,%rax
    jz abort
    testq %rdx,%rdx
    jz abort
    leaq (%rax,%rax,2),%rcx
    addq %rdx,%rdx
    cmpq %rcx,%rdx
    jb abort
    leaq (%rax,%rax,4),%rcx
    cmpq %rcx,%rdx
    ja abort
    movl short_elapsed(%rip),%eax
    call print_hex
    movb $':',%al
    outb %al,$0xe9
    movl long_elapsed(%rip),%eax
    call print_hex
    movb $':',%al
    outb %al,$0xe9
    movb $'P',%bl
    jmp cleanup
#endif
sample:
    subq $8,%rsp
    movl %r15d,%edi
    call f0
#ifdef HIA_TEST_PIT_LOAD_NOP
    cmpq $10,%rax
    je 1f
    cmpq $11,%rax
    jne abort
1:  call latch_count
    movzwl %ax,%eax
    movl %r15d,%ecx
    subl $1024,%ecx
    cmpl %ecx,%eax
    jb 2f
    cmpl %r15d,%eax
    jbe abort
2:
    inb $0x61,%al
    testb $3,%al
    jnz abort
    addq $8,%rsp
    ret
#else
    testq %rax,%rax
    jnz abort
    call latch_count
    movzwl %ax,%eax
    cmpl %r15d,%eax
    ja abort
    movl %r15d,%ecx
    subl $1024,%ecx
    cmpl %ecx,%eax
    jb abort
    inb $0x61,%al
    testb $0x23,%al
    jnz abort
    movl $-1,0x380(%r12)
    movl 0x390(%r12),%r13d
    testl %r13d,%r13d
    jz abort
    call f1
#ifdef HIA_TEST_PIT_START_NOP
    cmpq $10,%rax
    jne abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
    movl $0,0x380(%r12)
    addq $8,%rsp
    ret
#else
    testq %rax,%rax
    jnz abort
    inb $0x61,%al
    andb $3,%al
    cmpb $1,%al
    jne abort
    /* One poll must time out before a 10/20 ms window. */
    movl $1,%edi
    call f2
#ifdef HIA_TEST_PIT_WAIT_NOP
    cmpq $9,%rax
    jne abort
    inb $0x61,%al
    andb $0x23,%al
    cmpb $1,%al
    jne abort
    call f3
    testq %rax,%rax
    jnz abort
    movl $0,0x380(%r12)
    addq $8,%rsp
    ret
#endif
    cmpq $12,%rax
    jne abort
    movl $0x40000000,%edi
    call f2
    testq %rax,%rax
    jnz abort
    movl 0x390(%r12),%r14d
    testl %r14d,%r14d
    jz abort
    cmpl %r13d,%r14d
    jae abort
    inb $0x61,%al
    andb $0x23,%al
    cmpb $0x21,%al
    jne abort
    call f3
#ifdef HIA_TEST_PIT_STOP_NOP
    cmpq $10,%rax
    jne abort
    inb $0x61,%al
    andb $3,%al
    cmpb $1,%al
    jne abort
#else
    testq %rax,%rax
    jnz abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
    movl $1,%edi
    call f2
    cmpq $9,%rax
    jne abort
#endif
    movl $0,0x380(%r12)
    cmpl $0,0x390(%r12)
    jne abort
    movl %r13d,%eax
    subl %r14d,%eax
    addq $8,%rsp
    ret
#endif
#endif
latch_count:
    movb $0x80,%al
    outb %al,$0x43
    inb $0x42,%al
    movb %al,%dl
    inb $0x42,%al
    movb %al,%dh
    movzwl %dx,%eax
    ret
print_hex:
    movl %eax,%edx
    movl $8,%ecx
1:  roll $4,%edx
    movb %dl,%al
    andb $15,%al
    cmpb $10,%al
    jb 2f
    addb $87,%al
    jmp 3f
2:  addb $48,%al
3:  outb %al,$0xe9
    loop 1b
    ret
cleanup:
    movb old_gate(%rip),%al
    outb %al,$0x61
    movl $0,0x380(%r12)
    movl old_div(%rip),%eax
    movl %eax,0x3e0(%r12)
    movl old_lvt(%rip),%eax
    movl %eax,0x320(%r12)
    movl old_svr(%rip),%eax
    movl %eax,0xf0(%r12)
    movl $0x10,%eax
    cmpb $'P',%bl
    je finish
    movl $0x11,%eax
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
.section .bss,"aw",@nobits
.balign 4096
pml4: .skip 4096
pdpt: .skip 4096
pd0: .skip 4096
pd3: .skip 4096
.balign 16
stack32: .skip 4096
stack32_top:
stack64: .skip 8192
stack64_top:
old_svr: .skip 4
old_lvt: .skip 4
old_div: .skip 4
short_elapsed: .skip 4
long_elapsed: .skip 4
old_gate: .skip 1
