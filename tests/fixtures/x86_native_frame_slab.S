/* Independent NON-HIA Multiboot/AP startup and descriptor observer. */
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
    movl $5120,%ecx
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
    movl $pt0,%eax
    orl $3,%eax
    movl %eax,pd0
    movl $pt0,%edi
    movl $3,%eax
    movl $512,%ecx
2:  movl %eax,(%edi)
    movl $0,4(%edi)
    addl $4096,%eax
    addl $8,%edi
    loop 2b
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
    movabsq $APIC,%r12
    movl 0x20(%r12),%eax
    andl $0xff000000,%eax
    jnz abort
    movl $27,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    movq %rax,bsp_msr(%rip)
    movq %rax,%rcx
    andq $0xc00,%rcx
    cmpq $0x800,%rcx
    jne abort
    andq $-4096,%rax
    cmpq %r12,%rax
    jne abort
    /* PAT index 3 (PWT+PCD, large-page PAT=0) must be UC. */
    movl $1,%eax
    cpuid
    testl $0x10000,%edx
    jz abort
    movl $0x277,%ecx
    rdmsr
    shrl $24,%eax
    testl %eax,%eax
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

    leaq slab(%rip),%r13
    leaq callback(%rip),%rax
    movq %rax,0(%r13)
    movq %rax,32(%r13)
    leaq slab+8192(%rip),%rax
    movq %rax,8(%r13)
    leaq slab+24576(%rip),%rax
    movq %rax,16(%r13)
    leaq slab+28672(%rip),%rax
    movq %rax,40(%r13)
    leaq slab+45056(%rip),%rax
    movq %rax,48(%r13)
    movq $0,24(%r13)
    movq $0,56(%r13)
    movq $0x12345678,64(%r13)
    /* Both actual independent scheduler stack canaries. */
    leaq slab+8192(%rip),%rdi
    movl $64,%ecx
    movl $0x12345678,%eax
    rep stosq
    leaq slab+28672(%rip),%rdi
    movl $64,%ecx
    rep stosq
    /* Populate real hardware interrupt and invalid-opcode gates. */
    leaq irq_entry(%rip),%rax
    leaq idt+0x51*16(%rip),%rdi
    call set_gate
    leaq ud_handler(%rip),%rax
    leaq idt+6*16(%rip),%rdi
    call set_gate
    leaq pf_handler(%rip),%rax
    leaq idt+14*16(%rip),%rdi
    call set_gate
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
    movb $1,idt+14*16+4(%rip)
    leaq bsp_ist_top(%rip),%rax
    movq %rax,bsp_tss+36(%rip)
    movw $104,bsp_tss+102(%rip)
    leaq bsp_tss(%rip),%rax
    leaq gdt_bsp_tss(%rip),%rdi
    call set_tss
    leaq ap_ist_top(%rip),%rax
    movq %rax,ap_tss+36(%rip)
    movw $104,ap_tss+102(%rip)
    leaq ap_tss(%rip),%rax
    leaq gdt_ap_tss(%rip),%rdi
    call set_tss
    movw $0x20,%ax
    ltr %ax
#endif
    lidt idt_ptr(%rip)
    /* Warm both physical guard pages before the native two-leaf revocation.
     * This is before AP startup: no other CPU has cached these mappings. */
    movq $0x12345678,slab+4096(%rip)
    movq $0x76543210,slab+24576(%rip)
    leaq slab+4096(%rip),%r8
    leaq pt0(%rip),%rcx
    movq %r8,%rax
    shrq $12,%rax
    movq (%rcx,%rax,8),%r9
#ifdef HIA_STALE_FIRST
    movq %r8,%r9
    orq $3,%r9
#endif
#ifdef HIA_SECOND_ALIAS
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    movq %r8,%r10
    orq $3,%r10
    movq %r10,(%rcx,%rax,8)
    invlpg slab+24576(%rip)
    cmpq $0x12345678,slab+24576(%rip)
    jne abort
#endif
    leaq pml4(%rip),%rdi
    leaq pdpt(%rip),%rsi
    leaq pd0(%rip),%rdx
    call dual_guard
#ifdef HIA_STALE_FIRST
    cmpq $9,%rax
    jne abort
    cmpq $0x12345678,slab+4096(%rip)
    jne abort
    cmpq $0x76543210,slab+24576(%rip)
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    movq %rax,%rdx
    shrq $12,%rax
    orq $99,%rdx
    cmpq %rdx,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    movq %rax,%rdx
    shrq $12,%rax
    orq $99,%rdx
    cmpq %rdx,(%rcx,%rax,8)
    jne abort
    movb $'D',%bl
    jmp reject
#elif defined(HIA_PARTIAL_SECOND)
    cmpq $10,%rax
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    cmpq $0x76543210,slab+24576(%rip)
    jne abort
    movb $'T',%bl
    jmp reject
#elif defined(HIA_SECOND_ALIAS)
    cmpq $6,%rax
    jne abort
    cmpq $0x12345678,slab+4096(%rip)
    jne abort
    cmpq $0x12345678,slab+24576(%rip)
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    movq %rax,%rdx
    shrq $12,%rax
    orq $99,%rdx
    cmpq %rdx,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    movq (%rcx,%rax,8),%rdx
    andq $-4096,%rdx
    cmpq $slab+4096,%rdx
    jne abort
    movb $'J',%bl
    jmp reject
#else
    testq %rax,%rax
    jnz abort
#endif
    mfence
    /* Test-only AP startup. Copy an actual real-mode trampoline to the
     * fixed SIPI vector page and never credit it as HIA implementation. */
    leaq ap_trampoline(%rip),%rsi
    movl $0x8000,%edi
    movl $ap_trampoline_end-ap_trampoline,%ecx
    rep movsb
    mfence
    call wait_icr
    movl $0x01000000,0x310(%r12)
    movl $0xc500,0x300(%r12)
    call wait_icr
    movl $100000,%ecx
1:  pause
    loop 1b
    movl $0x01000000,0x310(%r12)
    movl $0x8500,0x300(%r12)
    call wait_icr
    movl $100000,%ecx
1:  pause
    loop 1b
    movl $0x01000000,0x310(%r12)
    movl $0x608,0x300(%r12)
    call wait_icr
    movl $20000000,%ecx
wait_ready:
    cmpq $1,ap_ready(%rip)
    je ready
    pause
    decl %ecx
    jnz wait_ready
    jmp abort
ready:
    cmpq $1,ap_identity(%rip)
    jne abort
#if defined(HIA_WRONG_AP) || defined(HIA_IST_AP) || defined(HIA_SLAB_AP) || defined(HIA_PRE_AP) || defined(HIA_POST_AP)
    movq $1,start_checks(%rip)
    mfence
    jmp bsp_wait_fault
bsp_wait_fault:
    pause
    jmp bsp_wait_fault
#endif
#ifndef HIA_SERIAL_NEGATIVE
    movq $1,start_checks(%rip)
    mfence
#endif
    leaq slab(%rip),%r13
    leaq slab+32(%rip),%r14
    leaq slab+8192(%rip),%r15
    call check_cpu
    movq $1,bsp_done(%rip)
#ifdef HIA_SERIAL_NEGATIVE
    movq $1,start_checks(%rip)
    mfence
#endif
    movl $20000000,%ecx
wait_done:
    cmpq $1,ap_done(%rip)
    je all_done
    pause
    decl %ecx
    jnz wait_done
    jmp abort
all_done:
    cmpq $1,bsp_done(%rip)
    jne abort
    cmpq $4,slab+24(%rip)
    jne abort
    cmpq $4,slab+56(%rip)
    jne abort
    cmpq $2,slab+1024(%rip)
    jne abort
    cmpq $2,slab+1056(%rip)
    jne abort
    cmpq $1,slab+3072(%rip)
    jne abort
    cmpq $1,slab+3080(%rip)
    jne abort
    cmpq $1,slab+3104(%rip)
    jne abort
    cmpq $1,slab+3112(%rip)
    jne abort
    cmpq $0x12345678,slab+64(%rip)
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+8192(%rip),%rdi
    leaq slab+28672(%rip),%rsi
    movl $64,%ecx
canary_check:
    cmpq $0x12345678,(%rdi)
    jne bad_stack
    cmpq $0x12345678,(%rsi)
    jne bad_stack
    addq $8,%rdi
    addq $8,%rsi
    loop canary_check
    movb $'P',%bl
    movl $0x10,%eax
    jmp finish
wait_icr:
    movl $2000000,%ecx
1:  testl $0x1000,0x300(%r12)
    jz 2f
    pause
    loop 1b
    jmp abort
2:  ret
/* Independent AP trampoline. CS=0x800, DS=0 after reset below. The
 * descriptor is copied with the code; its 32-bit base names the original
 * GDT. Far jump is an explicit 32-bit offset into the linked observer. */
.balign 16
.code16
ap_trampoline:
    cli
    cld
    xorw %ax,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    movw $0x7ff0,%sp
    lgdtl 0x8000+(ap_trampoline_gdtr-ap_trampoline)
    movl %cr0,%eax
    orl $1,%eax
    movl %eax,%cr0
    ljmpl $0x08,$ap_protected32
ap_trampoline_gdtr:
    .word gdt_end-gdt-1
    .long gdt
ap_trampoline_end:
.code32
ap_protected32:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    movl $ap_stack32_top,%esp
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
    ljmp $0x18,$ap_long64
.code64
ap_long64:
    movw $0x10,%ax
    movw %ax,%ds
    movw %ax,%es
    movw %ax,%ss
    leaq ap_stack64_top(%rip),%rsp

    movabsq $APIC,%r12
    movl 0x20(%r12),%eax
    shrl $24,%eax
    cmpq $1,%rax
    jne abort
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
    movw $0x30,%dx
    ltr %dx
#endif
    lidt idt_ptr(%rip)
    movl $0x1ff,0xf0(%r12)
    movl $0,0x80(%r12)
    movq %rax,ap_identity(%rip)
    movq $1,ap_ready(%rip)
    mfence
ap_wait:
    cmpq $1,start_checks(%rip)
    je ap_check
    pause
    jmp ap_wait
ap_check:
    leaq slab+32(%rip),%r13
    leaq slab(%rip),%r14
    leaq slab+28672(%rip),%r15
    call check_cpu
    movq $1,ap_done(%rip)
    mfence
ap_idle:
    cli
    hlt
    jmp ap_idle

/* R13 own descriptor, R15 own low. Both CPUs deliver two actual self-IPIs. */
check_cpu:
    /* Independently provision trusted table root on both actual CPUs. */
    leaq slab(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000100,%ecx
    wrmsr
    movq %r13,%rax
#ifdef HIA_WRONG_BSP
    leaq slab+32(%rip),%rax
#endif
#ifdef HIA_WRONG_AP
    leaq slab(%rip),%rax
#endif
#ifdef HIA_WRONG_ROOT
    movq $0,%rax
    movq $0,%rdx
    movl $0xc0000100,%ecx
    wrmsr
    movq %r13,%rax
#endif
#ifdef HIA_PEER_BUSY
    cmpq $slab+32,%r13
    jne own_gs
    movq %r14,%rax
own_gs:
#endif
#ifdef HIA_SLAB_BSP
    leaq slab+28672(%rip),%rax
    movq %rax,8(%r13)
    leaq slab+45056(%rip),%rax
    movq %rax,16(%r13)
    movq %r13,%rax
#endif
#ifdef HIA_SLAB_AP
    leaq slab+8192(%rip),%rax
    movq %rax,8(%r13)
    leaq slab+24576(%rip),%rax
    movq %rax,16(%r13)
    movq %r13,%rax
#endif
#ifdef HIA_SLAB_ROOT
    leaq slab+32(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000100,%ecx
    wrmsr
    leaq slab+32(%rip),%rax
#endif
    call set_gs
    /* The raw frame must be 16-byte aligned; no call between STI/HLT. */
    pushq %rbp
    movq %rsp,2048(%r13)
    movl $1,%ebp
#ifdef HIA_RAW_BUSY
    movq $1,24(%r13)
#endif
#ifdef HIA_RAW_RETIRED
    movq $-2,24(%r13)
#endif
#ifdef HIA_LAST_CYCLE
    movq $-4,24(%r13)
    movabsq $0x7ffffffffffffffe,%rax
    movq %rax,1024(%r13)
#endif
irq_round:
    call wait_icr
    movl $0x40051,0x300(%r12)
    call wait_icr
    movabsq $0x1122334455667788,%rax
    movabsq $0x8877665544332211,%rbx
    movabsq $0x23456789abcdef01,%r8
    movabsq $0x13579bdf2468ace0,%r9
    movabsq $0x2468ace013579bdf,%r10
    movabsq $0xfedcba9876543210,%r11
#if defined(HIA_PRE_BSP) || defined(HIA_PRE_AP)
#ifdef HIA_PRE_BSP
    leaq slab+45056-1024(%rip),%rsp
#else
    leaq slab+24576-1024(%rip),%rsp
#endif
    movq %rsp,2048(%r13)
#endif
    sti
    hlt
irq_resume:
    cli
    movabsq $0x1122334455667788,%rcx
    cmpq %rcx,%rax
    jne bad_gpr
    movabsq $0x8877665544332211,%rcx
    cmpq %rcx,%rbx
    jne bad_gpr
    movabsq $0x23456789abcdef01,%rcx
    cmpq %rcx,%r8
    jne bad_gpr
    movabsq $0x13579bdf2468ace0,%rcx
    cmpq %rcx,%r9
    jne bad_gpr
    movabsq $0x2468ace013579bdf,%rcx
    cmpq %rcx,%r10
    jne bad_gpr
    movabsq $0xfedcba9876543210,%rcx
    cmpq %rcx,%r11
    jne bad_gpr
    cmpq %rsp,2048(%r13)
    jne bad_gpr
    movl $0xc0000101,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    cmpq %r13,%rax
    jne bad_live_gs
#ifdef HIA_LAST_CYCLE
    cmpq $-2,24(%r13)
    jne bad_lease
    movabsq $0x7fffffffffffffff,%rax
    cmpq %rax,1024(%r13)
    jne bad_count
#else
    leaq (%rbp,%rbp),%rax
    cmpq %rax,24(%r13)
    jne bad_lease
    cmpq %rbp,1024(%r13)
    jne bad_count
#endif
    testl $0x20000,0x120(%r12)
    jnz bad_eoi
#if defined(HIA_POST_BSP) || defined(HIA_POST_AP)
    cmpq $1,%rbp
    jne abort
    cmpq $2,24(%r13)
    jne abort
    cmpq $1,1024(%r13)
    jne abort
#ifdef HIA_POST_BSP
    leaq slab+45056-1024(%rip),%rdi
    cmpq $0,slab+56(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
#else
    leaq slab+24576-1024(%rip),%rdi
    cmpq $0,slab+24(%rip)
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
#endif
    cmpq $irq_resume,120(%rdi)
    jne abort
    cmpq %rsp,144(%rdi)
    jne abort
    movb $'N',%bl
    jmp reject
#endif
    incl %ebp
    cmpl $3,%ebp
    jne irq_round
#if defined(HIA_PROBE_BSP) || defined(HIA_PROBE_AP)
#ifdef HIA_PROBE_BSP
    cmpq $slab,%r13
#else
    cmpq $slab+32,%r13
#endif
    jne no_guard_probe
    leaq -4096(%r15),%rax
guard_probe:
    movq (%rax),%rcx
    movb $'M',%bl
    jmp reject
no_guard_probe:
#endif
    popq %rbp
    ret
pf_handler:
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
#ifdef HIA_IST_BSP
    cmpq $bsp_ist,%rsp
    jb abort
    cmpq $bsp_ist_top,%rsp
    jae abort
    cmpq $slab,%r12
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
    str %ax
    cmpw $0x20,%ax
    jne abort
#else
    cmpq $ap_ist,%rsp
    jb abort
    cmpq $ap_ist_top,%rsp
    jae abort
    cmpq $slab+32,%r12
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
    str %ax
    cmpw $0x30,%ax
    jne abort
#endif
    cmpq $2,(%rsp)
    jne abort
    cmpq $ist_guard_push,8(%rsp)
    jne abort
    cmpq $0x18,16(%rsp)
    jne abort
    testq $0x200,24(%rsp)
    jnz abort
    movq 8(%r12),%rax
    cmpq %rax,32(%rsp)
    jne abort
    subq $8,%rax
    movq %cr2,%rcx
    cmpq %rax,%rcx
    jne abort
    leaq pt0(%rip),%rcx
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
    movabsq $APIC,%rcx
    testl $0x20000,0x120(%rcx)
    jz abort
    movl 0x20(%rcx),%eax
    shrl $24,%eax
#ifdef HIA_IST_BSP
    testl %eax,%eax
    jne abort
    movb $'Q',%bl
#else
    cmpl $1,%eax
    jne abort
    movb $'U',%bl
#endif
    jmp reject
#elif defined(HIA_PROBE_BSP) || defined(HIA_PROBE_AP)
    cmpq $0,(%rsp)
    jne abort
    cmpq $guard_probe,8(%rsp)
    jne abort
    movq %cr2,%rax
    leaq -4096(%r15),%rcx
    cmpq %rcx,%rax
    jne abort
    cmpq $4,24(%r13)
    jne abort
    cmpq $2,1024(%r13)
    jne abort
    movabsq $APIC,%rcx
    testl $0x20000,0x120(%rcx)
    jnz abort
    movl 0x20(%rcx),%eax
    shrl $24,%eax
#ifdef HIA_PROBE_BSP
    testl %eax,%eax
    jne abort
    movb $'F',%bl
#else
    cmpl $1,%eax
    jne abort
    movb $'H',%bl
#endif
    jmp reject
#else
    jmp abort
#endif
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
set_tss:
    movw $103,(%rdi)
    movw %ax,2(%rdi)
    shrq $16,%rax
    movb %al,4(%rdi)
    movb $0x89,5(%rdi)
    movb $0,6(%rdi)
    movb %ah,7(%rdi)
    shrq $16,%rax
    movl %eax,8(%rdi)
    movl $0,12(%rdi)
    ret
#endif
set_gs:
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
    ret
set_gate:
    movw %ax,0(%rdi)
    movw $0x18,2(%rdi)
    movb $0,4(%rdi)
    movb $0x8e,5(%rdi)
    shrq $16,%rax
    movw %ax,6(%rdi)
    shrq $16,%rax
    movl %eax,8(%rdi)
    movl $0,12(%rdi)
    ret
/* Independent observation only: verify stack switch, saved frame and ABI,
 * then tail-call the HIA callback. No EOI or IRET in this observer. */
callback:
#if defined(HIA_SLAB_BSP) || defined(HIA_SLAB_AP)
    /* Own GS and own lease, but a corrupted descriptor points at peer stack.
       Only the deliberately mutated low-binding branch may reach here. */
#ifdef HIA_SLAB_BSP
    cmpq $slab,%r12
    jne abort
    cmpq $slab+28672,%r13
    jne abort
    cmpq $slab+45056,%r14
    jne abort
    cmpq $1,slab+24(%rip)
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
#else
    cmpq $slab+32,%r12
    jne abort
    cmpq $slab+8192,%r13
    jne abort
    cmpq $slab+24576,%r14
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
    cmpq $1,slab+56(%rip)
    jne abort
#endif
    leaq -8(%r14),%rax
    cmpq %rax,%rsp
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    movb $'N',%bl
    jmp reject
#endif
#if defined(HIA_WRONG_BSP) || defined(HIA_WRONG_AP)
    /* Reached only if native binding is disabled: observe wrong peer's
     * actual acquired lease and scheduler stack before any HIA callback. */
#ifdef HIA_WRONG_BSP
    cmpq $slab+32,%r12
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
    cmpq $1,slab+56(%rip)
    jne abort
#else
    cmpq $slab,%r12
    jne abort
    cmpq $1,slab+24(%rip)
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
#endif
    leaq -8(%r14),%rax
    cmpq %rax,%rsp
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    movb $'N',%bl
    jmp reject
#endif
    leaq -8(%r14),%rax
    cmpq %rax,%rsp
    jne bad_stack
    movq 1024(%r12),%rax
    leaq 1(%rax,%rax),%rax
    cmpq %rax,24(%r12)
    jne bad_lease
    leaq 160(%rdi),%rax
    cmpq 2048(%r12),%rax
    jne bad_stack
    cmpq $irq_resume,120(%rdi)
    jne bad_stack
#if defined(HIA_PRE_BSP) || defined(HIA_PRE_AP)
#ifdef HIA_PRE_BSP
    leaq slab+45056-1024-160(%rip),%rax
    cmpq $slab,%r12
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
#else
    leaq slab+24576-1024-160(%rip),%rax
    cmpq $slab+32,%r12
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
#endif
    cmpq %rax,%rdi
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $0,1024(%r12)
    jne abort
    movb $'N',%bl
    jmp reject
#endif
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
#ifdef HIA_IST_BSP
    cmpq $slab,%r12
#else
    cmpq $slab+32,%r12
#endif
    jne abort
    movq %rsp,%rbx
    movq 8(%r12),%rsp
    movabsq $0x1267fedc4598ab03,%rax
ist_guard_push:
    pushq %rax
    cmpq %rax,(%rsp)
    jne abort
    movq %rbx,%rsp
    movb $'O',%bl
    jmp reject
#endif
#ifdef HIA_PEER_BUSY
    /* BSP is genuinely inside the acquired scheduler stack. Release AP to
     * deliver a real IRQ against this same descriptor, and do not leave. */
    cmpq $slab,%r12
    jne abort
    movq $1,3072(%r12)
    movq $1,start_checks(%rip)
    mfence
    movl $40000000,%ecx
peer_busy_wait:
    pause
    decl %ecx
    jnz peer_busy_wait
    jmp bad_overlap
#endif
#ifndef HIA_SERIAL_NEGATIVE
    /* First IRQ: each observes its peer holding the raw lease before either
     * may leave. Actual simultaneous independent scheduler-stack residency. */
    cmpq $0,1024(%r12)
    jne barrier_done
    leaq slab(%rip),%rax
    cmpq %rax,%r12
    jne peer_found
    addq $32,%rax
peer_found:
    movq $1,3072(%r12)
    mfence
    movl $40000000,%ecx
wait_peer_entry:
    cmpq $1,3072(%rax)
    je peer_entered
    pause
    decl %ecx
    jnz wait_peer_entry
    jmp bad_overlap
peer_entered:
    cmpq $1,24(%rax)
    jne bad_overlap
    movq $1,3080(%r12)
    mfence
    movl $40000000,%ecx
wait_peer_observed:
    cmpq $1,3080(%rax)
    je barrier_done
    pause
    decl %ecx
    jnz wait_peer_observed
    jmp bad_overlap
barrier_done:
#endif
#ifdef HIA_WRONG_GS
    /* Inject the peer GS only AFTER entry has acquired its own stack. */
    leaq slab+32(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
#endif
    leaq slab(%rip),%rsi
    leaq slab+45056(%rip),%rdx
    movl $2,%ecx
    leaq callback(%rip),%r8
#if defined(HIA_POST_BSP) || defined(HIA_POST_AP)
    /* Use the original native callback to commit the epoch and EOI.
       Then deliberately copy its valid selected frame into the idle peer's
       actual scheduler stack, with every byte (including RSP) unchanged. */
    subq $8,%rsp
    call f1
    addq $8,%rsp
    testq %rax,%rax
    jz abort
    movq %rax,3200(%r12)
    movq %rax,%rsi
#ifdef HIA_POST_BSP
    leaq slab+45056-1024(%rip),%rdi
#else
    leaq slab+24576-1024(%rip),%rdi
#endif
    movq %rdi,%rax
    movl $20,%ecx
    rep movsq
    ret
#elif defined(HIA_POST_GS) || defined(HIA_STALE_RELEASE)
    subq $8,%rsp
    call f1
    addq $8,%rsp
    testq %rax,%rax
    jz abort
#ifdef HIA_POST_GS
    movq %rax,%rsi
    leaq slab+32(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
    movq %rsi,%rax
#endif
#ifdef HIA_STALE_RELEASE
    movq $3,24(%r12)
#endif
    ret
#else
    jmp f1
#endif
ud_handler:
    /* Reject only a genuine native UD2, not an unrelated exception. */
    movq (%rsp),%rax
    cmpq $irq_entry,%rax
    jb abort
    cmpq $irq_entry_end,%rax
    jae abort
    cmpw $0x0b0f,(%rax)
    jne abort
    /* Exact raw native trap site, independent lease/epoch/ISR readback. */
#if defined(HIA_PRE_BSP) || defined(HIA_PRE_AP) || defined(HIA_POST_BSP) || defined(HIA_POST_AP)
#if defined(HIA_PRE_BSP) || defined(HIA_PRE_AP)
    cmpq $irq_frame_pre_trap,%rax
    jne abort
#ifdef HIA_PRE_BSP
    leaq slab+45056-1024-160(%rip),%rax
    cmpq $slab,%r12
    jne abort
    cmpq $slab+28672,%rsp
    jb abort
    cmpq $slab+45056,%rsp
    jae abort
#else
    leaq slab+24576-1024-160(%rip),%rax
    cmpq $slab+32,%r12
    jne abort
    cmpq $slab+8192,%rsp
    jb abort
    cmpq $slab+24576,%rsp
    jae abort
#endif
    cmpq %rax,%rdi
    jne abort
    cmpq $0,24(%r12)
    jne abort
    cmpq $0,1024(%r12)
    jne abort
    movabsq $APIC,%rcx
    testl $0x20000,0x120(%rcx)
    jz abort
    movb $'D',%bl
#else
    cmpq $irq_frame_post_trap,%rax
    jne abort
#ifdef HIA_POST_BSP
    leaq slab+45056-1024(%rip),%rax
    cmpq $slab,%r12
    jne abort
    cmpq $slab+8192,%rsp
    jb abort
    cmpq $slab+24576,%rsp
    jae abort
#else
    leaq slab+24576-1024(%rip),%rax
    cmpq $slab+32,%r12
    jne abort
    cmpq $slab+28672,%rsp
    jb abort
    cmpq $slab+45056,%rsp
    jae abort
#endif
    cmpq %rax,%r15
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $1,1024(%r12)
    jne abort
    movq 3200(%r12),%rsi
    movq %r15,%rdi
    movl $20,%ecx
    repe cmpsq
    jne abort
    cmpq $irq_resume,120(%r15)
    jne abort
    movabsq $APIC,%rcx
    testl $0x20000,0x120(%rcx)
    jnz abort
    movb $'F',%bl
#endif
    movabsq $APIC,%rcx
    movl 0x20(%rcx),%eax
    shrl $24,%eax
#if defined(HIA_PRE_AP) || defined(HIA_POST_AP)
    cmpl $1,%eax
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
#else
    testl %eax,%eax
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
#endif
    leaq slab+8192(%rip),%rdi
    movl $64,%ecx
1:  cmpq $0x12345678,(%rdi)
    jne abort
    addq $8,%rdi
    loop 1b
    leaq slab+28672(%rip),%rdi
    movl $64,%ecx
2:  cmpq $0x12345678,(%rdi)
    jne abort
    addq $8,%rdi
    loop 2b
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
#elif defined(HIA_WRONG_BSP) || defined(HIA_WRONG_AP) || defined(HIA_WRONG_ROOT) || defined(HIA_SLAB_BSP) || defined(HIA_SLAB_AP) || defined(HIA_SLAB_ROOT)
#ifdef HIA_WRONG_ROOT
    cmpq $irq_root_trap,%rax
#elif defined(HIA_SLAB_ROOT)
    cmpq $irq_slab_root_trap,%rax
#elif defined(HIA_SLAB_BSP) || defined(HIA_SLAB_AP)
    cmpq $irq_slab_low_trap,%rax
#else
    cmpq $irq_binding_trap,%rax
#endif
    jne abort
    cmpq $0,slab+24(%rip)
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
    cmpq $0,slab+1024(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
    cmpq $0,slab+3072(%rip)
    jne abort
    cmpq $0,slab+3104(%rip)
    jne abort
#if defined(HIA_WRONG_AP) || defined(HIA_SLAB_AP)
    cmpq $ap_stack64,%rsp
    jb abort
    cmpq $ap_stack64_top,%rsp
    jae abort
#else
    cmpq $stack64,%rsp
    jb abort
    cmpq $stack64_top,%rsp
    jae abort
#endif
    movabsq $APIC,%rcx
    movl 0x20(%rcx),%eax
    shrl $24,%eax
#if defined(HIA_WRONG_AP) || defined(HIA_SLAB_AP)
    cmpl $1,%eax
#else
    cmpl $0,%eax
#endif
    jne abort
    leaq slab+8192(%rip),%rdi
    movl $64,%ecx
1:  cmpq $0x12345678,(%rdi)
    jne abort
    addq $8,%rdi
    loop 1b
    leaq slab+28672(%rip),%rdi
    movl $64,%ecx
2:  cmpq $0x12345678,(%rdi)
    jne abort
    addq $8,%rdi
    loop 2b
    leaq pt0(%rip),%rcx
    leaq slab+4096(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    leaq slab+24576(%rip),%rax
    shrq $12,%rax
    cmpq $0,(%rcx,%rax,8)
    jne abort
    movb $'D',%bl
#elif defined(HIA_PEER_BUSY)
    cmpq $irq_busy_trap,%rax
    jne abort
    cmpq $slab,%r12
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $0,1024(%r12)
    jne abort
    cmpq $1,3072(%r12)
    jne abort
    cmpq $0,slab+56(%rip)
    jne abort
    cmpq $0,slab+1056(%rip)
    jne abort
    cmpq $ap_stack64,%rsp
    jb abort
    cmpq $ap_stack64_top,%rsp
    jae abort
    movabsq $APIC,%rcx
    movl 0x20(%rcx),%eax
    shrl $24,%eax
    cmpl $1,%eax
    jne abort
    movb $'Q',%bl
#elif defined(HIA_RAW_BUSY)
    cmpq $irq_busy_trap,%rax
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $0,1024(%r12)
    jne abort
    movb $'B',%bl
#elif defined(HIA_RAW_RETIRED) || defined(HIA_LAST_CYCLE)
    cmpq $irq_retired_trap,%rax
    jne abort
    cmpq $-2,24(%r12)
    jne abort
#ifdef HIA_LAST_CYCLE
    movabsq $0x7fffffffffffffff,%rcx
    cmpq %rcx,1024(%r12)
    jne abort
    movb $'W',%bl
#else
    cmpq $0,1024(%r12)
    jne abort
    movb $'R',%bl
#endif
#elif defined(HIA_POST_GS)
    cmpq $irq_post_gs_trap,%rax
    jne abort
    cmpq $1,24(%r12)
    jne abort
    cmpq $1,1024(%r12)
    jne abort
    movb $'X',%bl
#elif defined(HIA_STALE_RELEASE)
    cmpq $irq_release_trap,%rax
    jne abort
    cmpq $3,24(%r12)
    jne abort
    cmpq $1,1024(%r12)
    jne abort
    movb $'L',%bl
#else
    jmp abort
#endif
    movabsq $APIC,%rax
#if defined(HIA_POST_GS) || defined(HIA_STALE_RELEASE) || defined(HIA_POST_BSP) || defined(HIA_POST_AP)
    testl $0x20000,0x120(%rax)
    jnz abort
#else
    testl $0x20000,0x120(%rax)
    jz abort
#endif
    jmp reject
bad_live_gs:
    movb $'Y',%bl
    jmp reject
bad_overlap:
    movb $'V',%bl
    jmp reject
bad_stack:
    movb $'S',%bl
    jmp reject
bad_gpr:
    movb $'G',%bl
    jmp reject
bad_count:
    movb $'C',%bl
    jmp reject
bad_eoi:
    movb $'E',%bl
    jmp reject
bad_id:
    movb $'I',%bl
    jmp reject
bad_gs:
    movb $'G',%bl
    jmp reject
bad_callback:
    movb $'B',%bl
    jmp reject
bad_low:
    movb $'L',%bl
    jmp reject
bad_top:
    movb $'T',%bl
    jmp reject
bad_lease:
    movb $'E',%bl
    jmp reject
bad_range:
    movb $'R',%bl
reject:
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
1:  cli
    hlt
    jmp 1b
.section .rodata,"a",@progbits
.balign 8
gdt:
    .quad 0,0x00cf9a000000ffff,0x00cf92000000ffff,0x00af9a000000ffff
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
gdt_bsp_tss: .quad 0,0
gdt_ap_tss: .quad 0,0
#endif
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
pt0: .skip 4096
idt: .skip 4096
.balign 16
stack32: .skip 4096
stack32_top:
stack64: .skip 8192
stack64_top:
ap_stack32: .skip 4096
ap_stack32_top:
ap_stack64: .skip 8192
ap_stack64_top:
.balign 8
bsp_msr: .skip 8
ap_msr: .skip 8
ap_identity: .skip 8
ap_ready: .skip 8
interrupt_count: .skip 8
handler_cpu: .skip 8
handler_bad: .skip 8
eoi_status: .skip 8
eoi_missing: .skip 8
probe_request: .skip 8
probe_cpu: .skip 8
probe_pending: .skip 8
probe_ack: .skip 8
old_svr: .skip 4
old_tpr: .skip 4
old_pic1: .skip 1
old_pic2: .skip 1
.balign 8
start_checks: .skip 8
bsp_done: .skip 8
ap_done: .skip 8
#if defined(HIA_IST_BSP) || defined(HIA_IST_AP)
.balign 16
bsp_tss: .skip 104
ap_tss: .skip 104
.balign 4096
bsp_ist: .skip 4096
bsp_ist_top:
ap_ist: .skip 4096
ap_ist_top:
#endif
.balign 4096
slab: .skip 45056
