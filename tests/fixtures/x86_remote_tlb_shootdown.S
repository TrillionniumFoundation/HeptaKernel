/* NON-HIA Multiboot, AP startup and independent interrupt observer.
 * f0 (IPI send), f1 (EOI), f2 (remote invalidation) are native HIA.
 * f3 publishes PTE; f4 publishes generation-tagged ACK by native CAS.
 * f5 consumes one completed generation on BSP, not page reclamation. */
.set TARGET_VA,0x40000000
.set OLD_VALUE,0x13579bdf
.set NEW_VALUE,0x2468ace0
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
    /* Independent 4KiB leaf at 1GiB; backing pages remain identity mapped. */
    movl $shoot_pd,%edi
    xorl %eax,%eax
    movl $2048,%ecx
    rep stosl
    movl $shoot_pd,%eax
    orl $3,%eax
    movl %eax,pdpt+8
    movl $shoot_pt,%eax
    orl $3,%eax
    movl %eax,shoot_pd
    movl $old_page,%eax
    orl $3,%eax
    movl %eax,shoot_pt
    movl $OLD_VALUE,old_page
    movl $0,old_page+4
    movl $NEW_VALUE,new_page
    movl $0,new_page+4
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
    /* One common IDT, independently installed before AP startup. */
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
    cmpq $OLD_VALUE,old_observed(%rip)
    jne abort
    /* Pending generation 2 = 4, completed = 5. BSP only initializes. */
    movq $4,shoot_ack(%rip)
    movq $0x11223344,ack_guard_lo(%rip)
    movq $0x55667788,ack_guard_hi(%rip)
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    movl $NEW_VALUE,%edx
    movl $NEW_VALUE,%ecx
    movl $0,%r8d
    call f4
    cmpq $6,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
    /* All malformed f5 inputs must be rejected before any CAS. */
    leaq shoot_ack+1(%rip),%rdi
    movl $2,%esi
    call f5
    cmpq $6,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    xorl %esi,%esi
    call f5
    cmpq $6,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    movabsq $0x8000000000000000,%rsi
    call f5
    cmpq $6,%rax
    jne abort
    xorq %rdi,%rdi
    movl $2,%esi
    call f5
    cmpq $6,%rax
    jne abort
    movl $0x40000000,%edi
    movl $2,%esi
    call f5
    cmpq $6,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
#ifndef HIA_TEST_CONSUME_CAS_NOP
    /* Pending generation cannot be consumed. The early-deletion
     * mutant must show a false success and the unchanged pending word. */
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    call f5
#ifdef HIA_TEST_CONSUME_PENDING_NOP
    testq %rax,%rax
    jnz abort
    cmpq $4,shoot_ack(%rip)
    jne abort
    cmpq $0x11223344,ack_guard_lo(%rip)
    jne abort
    cmpq $0x55667788,ack_guard_hi(%rip)
    jne abort
    movb $'U',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $9,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
#endif
#endif
    /* BSP must not be able to claim remote invalidation. */
    movl $TARGET_VA,%edi
    call f2
    cmpq $6,%rax
    jne abort
    /* Independent old-leaf readback. Native HIA must publish replacement. */
    leaq old_page(%rip),%rax
    movq shoot_pt(%rip),%rdx
    andq $-4096,%rdx
    cmpq %rax,%rdx
    jne abort
    movq shoot_pt(%rip),%rax
    movq %rax,old_pte(%rip)
    leaq shoot_pt+1(%rip),%rdi
    leaq old_page(%rip),%rsi
    leaq new_page(%rip),%rdx
    movq old_pte(%rip),%rcx
    call f3
    cmpq $6,%rax
    jne abort
    movq old_pte(%rip),%rax
    cmpq %rax,shoot_pt(%rip)
    jne abort
    leaq shoot_pt(%rip),%rdi
    leaq old_page(%rip),%rsi
    leaq new_page(%rip),%rdx
    movq old_pte(%rip),%rcx
    call f3
    testq %rax,%rax
    jnz abort
    leaq new_page(%rip),%rax
    orq $3,%rax
    cmpq %rax,shoot_pt(%rip)
#ifdef HIA_TEST_PTE_CAS_NOP
    je abort
    movq old_pte(%rip),%rax
    cmpq %rax,shoot_pt(%rip)
    jne abort
    movb $'J',%bl
    movl $0x11,%eax
    jmp finish
#else
    jne abort
#endif
    /* Reusing old PTE after successful publication must return stale. */
    leaq shoot_pt(%rip),%rdi
    leaq old_page(%rip),%rsi
    leaq new_page(%rip),%rdx
    movq old_pte(%rip),%rcx
    call f3
    cmpq $9,%rax
    jne abort
    leaq new_page(%rip),%rax
    orq $3,%rax
    cmpq %rax,shoot_pt(%rip)
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    /* Reset destination only, not send. The prior SIPI low vector is 8,
     * so deleting the native low-store cannot pass its vector readback. */
    movl $0,0x310(%r12)
    movl 0x310(%r12),%eax
    andl $0xff000000,%eax
    jnz abort
    movl 0x300(%r12),%eax
    andl $0xff,%eax
    cmpl $VEC,%eax
    je abort
    movq %r12,%rdi
    movq bsp_msr(%rip),%rsi
    movl $1,%edx
    movl $VEC,%ecx
#ifdef HIA_TEST_BAD_BASE
    incq %rdi
#elif defined(HIA_TEST_STALE)
    xorq $0x100,%rsi
#elif defined(HIA_TEST_BAD_DEST)
    xorl %edx,%edx
#elif defined(HIA_TEST_VECTOR)
    incl %ecx
#elif defined(HIA_TEST_DISABLED)
    movl $0xff,0xf0(%r12)
#endif
    call f0
#if defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_BAD_DEST) || defined(HIA_TEST_VECTOR)
    cmpq $6,%rax
    jne abort
    movb $'B',%bl
#elif defined(HIA_TEST_STALE)
    cmpq $9,%rax
    jne abort
    movb $'S',%bl
#elif defined(HIA_TEST_DISABLED)
    cmpq $10,%rax
    jne abort
    movb $'D',%bl
#elif defined(HIA_TEST_DEST_NOP)
    cmpq $14,%rax
    jne abort
    movb $'T',%bl
#elif defined(HIA_TEST_SEND_NOP)
    cmpq $13,%rax
    jne abort
    movb $'N',%bl
#else
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_EOI_NOP
    movb $'M',%bl
#else
    movb $'P',%bl
#endif
    movl $20000000,%ecx
wait_delivery:
    cmpq $1,interrupt_count(%rip)
    je observed
    pause
    decl %ecx
    jnz wait_delivery
    jmp abort
observed:
#endif
    /* Ask the actual AP execution loop to attest its own local IRR/ISR
     * after returning from the handler, not a BSP-made receipt. */
    mfence
    movq $1,probe_request(%rip)
    movl $20000000,%ecx
wait_probe:
    cmpq $1,probe_ack(%rip)
    je probed
    pause
    decl %ecx
    jnz wait_probe
    jmp abort
probed:
    cmpq $1,probe_cpu(%rip)
    jne abort
    cmpq $0,probe_pending(%rip)
    jne abort
    cmpq $0,handler_bad(%rip)
    jne abort
    cmpq $0x11223344,ack_guard_lo(%rip)
    jne abort
    cmpq $0x55667788,ack_guard_hi(%rip)
    jne abort
    cmpq $OLD_VALUE,pre_flush_observed(%rip)
    jne abort_pre
    cmpq $0,flush_status(%rip)
    jne abort
#ifdef HIA_TEST_FLUSH_NOP
    /* A stale translation must be observed immediately after the deleted
     * INVLPG. IRET or incidental replacement may subsequently evict it. */
    cmpq $OLD_VALUE,immediate_flush_observed(%rip)
    jne abort_immediate
    cmpq $4,shoot_ack(%rip)
    jne abort_ack
    cmpq $OLD_VALUE,post_flush_observed(%rip)
    je stale_after_return
    cmpq $NEW_VALUE,post_flush_observed(%rip)
    jne abort
    movb $'R',%bl
    jmp checked_post_return
stale_after_return:
    movb $'F',%bl
checked_post_return:
#elif defined(HIA_TEST_ACK_MISSING)
    cmpq $NEW_VALUE,immediate_flush_observed(%rip)
    jne abort_immediate
    cmpq $NEW_VALUE,post_flush_observed(%rip)
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
    movb $75,%bl
#elif defined(HIA_TEST_ACK_CAS_NOP)
    cmpq $NEW_VALUE,immediate_flush_observed(%rip)
    jne abort_immediate
    cmpq $NEW_VALUE,post_flush_observed(%rip)
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort_ack
    movb $'L',%bl
#else
    cmpq $NEW_VALUE,immediate_flush_observed(%rip)
    jne abort_immediate
    cmpq $NEW_VALUE,post_flush_observed(%rip)
    jne abort
    cmpq $5,shoot_ack(%rip)
    jne abort
#endif
#if defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_BAD_DEST) || defined(HIA_TEST_VECTOR) || defined(HIA_TEST_STALE) || defined(HIA_TEST_DISABLED) || defined(HIA_TEST_DEST_NOP) || defined(HIA_TEST_SEND_NOP)
    cmpq $0,interrupt_count(%rip)
    jne abort
#else
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $1,handler_cpu(%rip)
    jne abort
#ifdef HIA_TEST_EOI_NOP
    cmpq $13,eoi_status(%rip)
    jne abort
    cmpq $1,eoi_missing(%rip)
    jne abort
#else
    cmpq $0,eoi_status(%rip)
    jne abort
    cmpq $0,eoi_missing(%rip)
    jne abort
#endif
#endif
    /* Actual BSP consumption is separate from AP publication. No observer
     * writes the retirement word. A zero word is terminal for this fixture;
     * reuse needs a separate generation allocator/ownership protocol. */
#if defined(HIA_TEST_FLUSH_NOP) || defined(HIA_TEST_ACK_MISSING) || defined(HIA_TEST_ACK_CAS_NOP)
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    call f5
    cmpq $9,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
#else
#ifndef HIA_TEST_CONSUME_CAS_NOP
    leaq shoot_ack(%rip),%rdi
    movl $1,%esi
    call f5
    cmpq $9,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    movl $3,%esi
    call f5
    cmpq $9,%rax
    jne abort
    cmpq $5,shoot_ack(%rip)
    jne abort
#endif
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    call f5
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_CONSUME_CAS_NOP
    cmpq $5,shoot_ack(%rip)
    jne abort
    movb $'V',%bl
#else
    cmpq $0,shoot_ack(%rip)
    jne abort
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    call f5
    cmpq $9,%rax
    jne abort
    cmpq $0,shoot_ack(%rip)
    jne abort
#endif
#endif
    cmpq $0x11223344,ack_guard_lo(%rip)
    jne abort
    cmpq $0x55667788,ack_guard_hi(%rip)
    jne abort
    /* A mistakenly self-directed interrupt must be detected on BSP. */
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
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
    cmpq bsp_msr(%rip),%rax
    jne abort
    movl $0x10,%eax
    cmpb $'P',%bl
    je finish
    movl $0x11,%eax
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
    lidt idt_ptr(%rip)
    movabsq $APIC,%r12
    movl 0x20(%r12),%eax
    shrl $24,%eax
    cmpq $1,%rax
    jne abort
    movq %rax,ap_identity(%rip)
    movl $27,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    movq %rax,ap_msr(%rip)
    movq %rax,%rcx
    andq $0xc00,%rcx
    cmpq $0x800,%rcx
    jne abort
    andq $-4096,%rax
    cmpq %r12,%rax
    jne abort
    movl $0x1ff,0xf0(%r12)
    movl $0,0x80(%r12)
    testl $VBIT,0x220(%r12)
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    movl $TARGET_VA,%eax
    movq (%rax),%rax
    movq %rax,old_observed(%rip)
    mfence
    sti
    movq $1,ap_ready(%rip)
ap_loop:
    pause
    cmpq $1,probe_request(%rip)
    jne ap_loop
    cli
    movl 0x20(%r12),%eax
    shrl $24,%eax
    movq %rax,probe_cpu(%rip)
    movl 0x220(%r12),%eax
    orl 0x120(%r12),%eax
    andl $VBIT,%eax
    movq %rax,probe_pending(%rip)
    /* Only AP after IRET can publish successful completion. */
    movl $TARGET_VA,%eax
    movq (%rax),%rax
    movq %rax,post_flush_observed(%rip)
    /* AP must not be able to publish the BSP's PTE. */
    leaq shoot_pt(%rip),%rdi
    leaq old_page(%rip),%rsi
    leaq new_page(%rip),%rdx
    movq old_pte(%rip),%rcx
    call f3
    cmpq $6,%rax
    jne abort
    /* AP may publish an ACK but may not perform BSP-only consumption. */
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    call f5
    cmpq $6,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
#ifndef HIA_TEST_ACK_MISSING
#if !defined(HIA_TEST_FLUSH_NOP) && !defined(HIA_TEST_ACK_CAS_NOP)
    /* Before publication, old/future generations, bad alignment and
     * nonzero flush status must not complete the pending slot. */
    leaq shoot_ack+1(%rip),%rdi
    movl $2,%esi
    movl $NEW_VALUE,%edx
    movl $NEW_VALUE,%ecx
    movl $0,%r8d
    call f4
    cmpq $6,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    movl $NEW_VALUE,%edx
    movl $NEW_VALUE,%ecx
    movl $9,%r8d
    call f4
    cmpq $6,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    movl $1,%esi
    movl $NEW_VALUE,%edx
    movl $NEW_VALUE,%ecx
    movl $0,%r8d
    call f4
    cmpq $9,%rax
    jne abort
    leaq shoot_ack(%rip),%rdi
    movl $3,%esi
    movl $NEW_VALUE,%edx
    movl $NEW_VALUE,%ecx
    movl $0,%r8d
    call f4
    cmpq $9,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort
#endif
    /* Actual independent observations; no assembly completion store. */
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    movq immediate_flush_observed(%rip),%rdx
    movq post_flush_observed(%rip),%rcx
    movq flush_status(%rip),%r8
    call f4
#ifdef HIA_TEST_FLUSH_NOP
    cmpq $6,%rax
    jne abort
    cmpq $4,shoot_ack(%rip)
    jne abort_ack
#else
    testq %rax,%rax
    jnz abort
#ifndef HIA_TEST_ACK_CAS_NOP
    cmpq $5,shoot_ack(%rip)
    jne abort_ack
    /* Duplicate completion must return stale. */
    leaq shoot_ack(%rip),%rdi
    movl $2,%esi
    movq immediate_flush_observed(%rip),%rdx
    movq post_flush_observed(%rip),%rcx
    movq flush_status(%rip),%r8
    call f4
    cmpq $9,%rax
    jne abort
    cmpq $5,shoot_ack(%rip)
    jne abort_ack
#endif
#endif
#endif
    mfence
    movq $1,probe_ack(%rip)
    sti
ap_idle:
    hlt
    jmp ap_idle
/* NON-HIA interrupt entry/return, native HIA handles EOI. */
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
    movl 0x20(%r12),%eax
    shrl $24,%eax
    movq %rax,handler_cpu(%rip)
    cmpq $1,%rax
    jne handler_fail
    incq interrupt_count(%rip)
    testl $VBIT,0x120(%r12)
    jz handler_fail
    movl $TARGET_VA,%eax
    movq (%rax),%rax
    movq %rax,pre_flush_observed(%rip)
    /* Reject a different address, then invalidate the admitted page. */
    movl $(TARGET_VA+4096),%edi
    call f2
    cmpq $6,%rax
    jne handler_fail
    movl $TARGET_VA,%edi
    call f2
    movq %rax,flush_status(%rip)
    testq %rax,%rax
    jnz handler_fail
    /* Observe before EOI/IRET, without introducing a second invalidation. */
    movl $TARGET_VA,%eax
    movq (%rax),%rax
    movq %rax,immediate_flush_observed(%rip)
    movq %r12,%rdi
    movq ap_msr(%rip),%rsi
    call f1
    movq %rax,eoi_status(%rip)
#ifdef HIA_TEST_EOI_NOP
    cmpq $13,%rax
    jne handler_fail
    testl $VBIT,0x120(%r12)
    jz handler_fail
    movq $1,eoi_missing(%rip)
    /* Independent cleanup of intentionally mutated HIA object. */
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
abort_pre:
    movb $'B',%bl
    jmp abort_code
abort_immediate:
    movb $'I',%bl
    jmp abort_code
abort_ack:
    movb $'C',%bl
    jmp abort_code
abort:
    movb $'A',%bl
abort_code:
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
shoot_pd: .skip 4096
shoot_pt: .skip 4096
old_page: .skip 4096
new_page: .skip 4096
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
old_observed: .skip 8
pre_flush_observed: .skip 8
immediate_flush_observed: .skip 8
post_flush_observed: .skip 8
flush_status: .skip 8
ack_guard_lo: .skip 8
shoot_ack: .skip 8
ack_guard_hi: .skip 8
old_pte: .skip 8
old_svr: .skip 4
old_tpr: .skip 4
old_pic1: .skip 1
old_pic2: .skip 1
