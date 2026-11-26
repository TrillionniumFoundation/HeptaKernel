/* Independent NON-HIA observer. Real HIA IRQ, ready exchange, frame handoff, owner publication and return. */
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
    leaq hia_irq_entry(%rip),%rax
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
    leaq frame_ud_handler(%rip),%rax
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
    lidt idt_ptr(%rip)
    /* Caller-owned BSP descriptor; only the raw native gate reads it. */
    movl $0xc0000101,%ecx
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    movq %rax,saved_gs_base(%rip)
    leaq irq_dispatch(%rip),%rax
    movq %rax,irq_dispatch_slot(%rip)
    leaq irq_dispatch_slot(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr

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


    /* Fixed test count, not a new clock calibration claim. */
    movq %rsp,resume_rsp(%rip)
    leaq resume_frame(%rip),%rdi
    leaq task_done(%rip),%rax
    movq %rax,120(%rdi)
    movq $0x18,128(%rdi)
    movq $2,136(%rdi)
    movq %rsp,144(%rdi)
    movq $0x10,152(%rdi)
    movq $2,ready_word(%rip)
    movq $2,expected_ready(%rip)
    movq $0x12345678,ready_before(%rip)
    movq $0x23456789,ready_after(%rip)
    movq $0x34567890,owner_before(%rip)
    movq $0x45678901,owner_after(%rip)
    leaq task0_stack_top-160(%rip),%rdi
    movq $1048577,112(%rdi)
    movq $1048850,104(%rdi)
    movq $1049123,96(%rdi)
    movq $1049396,88(%rdi)
    movq $1049669,80(%rdi)
    movq $1049942,72(%rdi)
    movq $1050215,64(%rdi)
    movq $1050488,56(%rdi)
    movq $1050761,48(%rdi)
    movq $1051034,40(%rdi)
    movq $1051307,32(%rdi)
    movq $1051580,24(%rdi)
    movq $1051853,16(%rdi)
    movq $1052126,8(%rdi)
    movq $1052399,0(%rdi)
    leaq task0_loop(%rip),%rax
    movq %rax,120(%rdi)
    movq $0x18,128(%rdi)
    movq $0x202,136(%rdi)
    leaq task0_stack_top(%rip),%rax
    movq %rax,144(%rdi)
    movq $0x10,152(%rdi)
    movq %rdi,slots+0(%rip)
    movq $0x12345678,task0_stack(%rip)
    movq $0x23456789,task0_stack_top(%rip)
    leaq task1_stack_top-160(%rip),%rdi
    movq $2097153,112(%rdi)
    movq $2097426,104(%rdi)
    movq $2097699,96(%rdi)
    movq $2097972,88(%rdi)
    movq $2098245,80(%rdi)
    movq $2098518,72(%rdi)
    movq $2098791,64(%rdi)
    movq $2099064,56(%rdi)
    movq $2099337,48(%rdi)
    movq $2099610,40(%rdi)
    movq $2099883,32(%rdi)
    movq $2100156,24(%rdi)
    movq $2100429,16(%rdi)
    movq $2100702,8(%rdi)
    movq $2100975,0(%rdi)
    leaq task1_loop(%rip),%rax
    movq %rax,120(%rdi)
    movq $0x18,128(%rdi)
    movq $0x202,136(%rdi)
    leaq task1_stack_top(%rip),%rax
    movq %rax,144(%rdi)
    movq $0x10,152(%rdi)
    movq %rdi,slots+8(%rip)
    movq $0x12345678,task1_stack(%rip)
    movq $0x23456789,task1_stack_top(%rip)
    leaq task2_stack_top-160(%rip),%rdi
    movq $3145729,112(%rdi)
    movq $3146002,104(%rdi)
    movq $3146275,96(%rdi)
    movq $3146548,88(%rdi)
    movq $3146821,80(%rdi)
    movq $3147094,72(%rdi)
    movq $3147367,64(%rdi)
    movq $3147640,56(%rdi)
    movq $3147913,48(%rdi)
    movq $3148186,40(%rdi)
    movq $3148459,32(%rdi)
    movq $3148732,24(%rdi)
    movq $3149005,16(%rdi)
    movq $3149278,8(%rdi)
    movq $3149551,0(%rdi)
    leaq task2_loop(%rip),%rax
    movq %rax,120(%rdi)
    movq $0x18,128(%rdi)
    movq $0x202,136(%rdi)
    leaq task2_stack_top(%rip),%rax
    movq %rax,144(%rdi)
    movq $0x10,152(%rdi)
    movq %rdi,slots+16(%rip)
    movq $0x12345678,task2_stack(%rip)
    movq $0x23456789,task2_stack_top(%rip)

    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl $2000000,%edx
    movl $4000000,%ecx
#ifdef HIA_LONG
    movl $24000,%r8d
#else
    movl $12000,%r8d
#endif
    call f3
#ifdef HIA_LONG
    cmpq $4000000,%rax
#else
    cmpq $2000000,%rax
#endif
    jne abort
    movl %eax,expected_count(%rip)
    movq slots(%rip),%rdi
    movq $0,slots(%rip)
    call hia_restore_frame
    jmp abort
task0_loop:
    cmpq $1048577,%rax
    jne bad_gpr
    cmpq $1048850,%rbx
    jne bad_gpr
    cmpq $1049123,%rcx
    jne bad_gpr
    cmpq $1049396,%rdx
    jne bad_gpr
    cmpq $1049669,%rsi
    jne bad_gpr
    cmpq $1049942,%rdi
    jne bad_gpr
    cmpq $1050215,%rbp
    jne bad_gpr
    cmpq $1050488,%r8
    jne bad_gpr
    cmpq $1050761,%r9
    jne bad_gpr
    cmpq $1051034,%r10
    jne bad_gpr
    cmpq $1051307,%r11
    jne bad_gpr
    cmpq $1051580,%r12
    jne bad_gpr
    cmpq $1051853,%r13
    jne bad_gpr
    cmpq $1052126,%r14
    jne bad_gpr
    cmpq $1052399,%r15
    jne bad_gpr
    cmpq $task0_stack_top,%rsp
    jne abort
    movq $1,idle_request0(%rip)
    incq progress+0(%rip)
    jmp task0_loop
task0_end:
task1_loop:
    cmpq $2097153,%rax
    jne bad_gpr
    cmpq $2097426,%rbx
    jne bad_gpr
    cmpq $2097699,%rcx
    jne bad_gpr
    cmpq $2097972,%rdx
    jne bad_gpr
    cmpq $2098245,%rsi
    jne bad_gpr
    cmpq $2098518,%rdi
    jne bad_gpr
    cmpq $2098791,%rbp
    jne bad_gpr
    cmpq $2099064,%r8
    jne bad_gpr
    cmpq $2099337,%r9
    jne bad_gpr
    cmpq $2099610,%r10
    jne bad_gpr
    cmpq $2099883,%r11
    jne bad_gpr
    cmpq $2100156,%r12
    jne bad_gpr
    cmpq $2100429,%r13
    jne bad_gpr
    cmpq $2100702,%r14
    jne bad_gpr
    cmpq $2100975,%r15
    jne bad_gpr
    cmpq $task1_stack_top,%rsp
    jne abort
    movq $1,idle_request1(%rip)
    incq progress+8(%rip)
    jmp task1_loop
task1_end:
task2_loop:
    cmpq $3145729,%rax
    jne bad_gpr
    cmpq $3146002,%rbx
    jne bad_gpr
    cmpq $3146275,%rcx
    jne bad_gpr
    cmpq $3146548,%rdx
    jne bad_gpr
    cmpq $3146821,%rsi
    jne bad_gpr
    cmpq $3147094,%rdi
    jne bad_gpr
    cmpq $3147367,%rbp
    jne bad_gpr
    cmpq $3147640,%r8
    jne bad_gpr
    cmpq $3147913,%r9
    jne bad_gpr
    cmpq $3148186,%r10
    jne bad_gpr
    cmpq $3148459,%r11
    jne bad_gpr
    cmpq $3148732,%r12
    jne bad_gpr
    cmpq $3149005,%r13
    jne bad_gpr
    cmpq $3149278,%r14
    jne bad_gpr
    cmpq $3149551,%r15
    jne bad_gpr
    cmpq $task2_stack_top,%rsp
    jne abort
    incq progress+16(%rip)
#ifndef HIA_IDLE_SKIP_HLT
    hlt
#else
    jmp task2_loop
#endif
idle_after_hlt:
    jmp task2_loop
task2_end:

.balign 16
irq_dispatch:
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq %rdi,%rbp
    movabsq $APIC,%r12
    testl $VBIT,0x120(%r12)
    jz abort
    cmpl $0x20051,0x320(%r12)
    jne abort
    incq interrupt_count(%rip)
    movq actual_switches(%rip),%rax
    shlq $5,%rax
    movq owner_word(%rip),%r13
    movq %r13,%rcx
    andq $-32,%rcx
    cmpq %rcx,%rax
    jne bad_owner
    andq $31,%r13
    cmpq $3,%r13
    jae bad_owner
    leaq slots(%rip),%rdx
    cmpq $0,(%rdx,%r13,8)
    jne bad_handoff
    leaq tops(%rip),%rdx
    movq (%rdx,%r13,8),%rax
    cmpq %rax,144(%rbp)
    jne abort
    subq $160,%rax
    cmpq %rax,%rbp
    jne abort
    leaq starts(%rip),%rdx
    movq 120(%rbp),%rax
    cmpq (%rdx,%r13,8),%rax
    jb abort
    leaq ends(%rip),%rdx
    cmpq (%rdx,%r13,8),%rax
    jae abort
    cmpq $0x18,128(%rbp)
    jne abort
    cmpq $0x10,152(%rbp)
    jne abort
    /* Each original register, not the observer's own registers. */
    movq %r13,%rax
    incq %rax
    shlq $20,%rax
    incq %rax
    leaq 112(%rbp),%rdx
    movq $15,%rcx
1:  cmpq %rax,(%rdx)
    jne bad_gpr
    subq $8,%rdx
    addq $273,%rax
    loop 1b
    leaq progress(%rip),%rdx
    movq (%rdx,%r13,8),%rax
    leaq last_progress(%rip),%rdx
    cmpq (%rdx,%r13,8),%rax
    jbe abort
    movq %rax,(%rdx,%r13,8)
    leaq departures(%rip),%rdx
    incq (%rdx,%r13,8)
    cmpq $6,interrupt_count(%rip)
    je supervisor_eoi
    ja abort
    /* First real IRQ preempts task0 without blocking it. */
    cmpq $1,interrupt_count(%rip)
    jne idle_second
    cmpq $0,%r13
    jne bad_idle
    jmp idle_choose
idle_second:
    cmpq $2,interrupt_count(%rip)
    jne idle_third
    cmpq $1,%r13
    jne bad_idle
    cmpq $1,idle_request1(%rip)
    jne bad_idle
    movq progress+8(%rip),%rax
    movq %rax,idle_blocked1(%rip)
    jmp idle_choose
idle_third:
    cmpq $3,interrupt_count(%rip)
    jne idle_wake
    cmpq $0,%r13
    jne bad_idle
    cmpq $1,idle_request0(%rip)
    jne bad_idle
    movq progress(%rip),%rax
    movq %rax,idle_blocked0(%rip)
    movq idle_blocked1(%rip),%rax
    cmpq %rax,progress+8(%rip)
    jne bad_idle
    jmp idle_choose
idle_wake:
    cmpq $4,interrupt_count(%rip)
    je idle_stay
    cmpq $5,interrupt_count(%rip)
    jne bad_idle
    cmpq $2,%r13
    jne bad_idle
    cmpq $idle_after_hlt,120(%rbp)
    jne bad_idle
    cmpq $2,progress+16(%rip)
    jne bad_idle
    movq idle_blocked0(%rip),%rax
    cmpq %rax,progress(%rip)
    jne bad_idle
    movq idle_blocked1(%rip),%rax
    cmpq %rax,progress+8(%rip)
    jne bad_idle
    movabsq $0x900000000,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    leaq ready_word(%rip),%rdi
    movq %rax,%rsi
    movq $3,%rdx
    xorq %rcx,%rcx
    movq $1,%r8
    call hia_publish_ready
    testq %rax,%rax
    jne bad_idle
    movabsq $0xa00000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movq %rax,expected_ready(%rip)
    jmp idle_choose
idle_stay:
    cmpq $2,%r13
    jne bad_idle
    cmpq $idle_after_hlt,120(%rbp)
    jne bad_idle
    cmpq $1,progress+16(%rip)
    jne bad_idle
    movq idle_blocked0(%rip),%rax
    cmpq %rax,progress(%rip)
    jne bad_idle
    movq idle_blocked1(%rip),%rax
    cmpq %rax,progress+8(%rip)
    jne bad_idle
    movabsq $0x900000000,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    cmpq %rax,expected_ready(%rip)
    jne bad_idle
    cmpq $98,owner_word(%rip)
    jne bad_idle
    leaq ready_word(%rip),%rdi
    movabsq $0x800000000,%rsi
    movq $3,%rdx
    movq %r13,%rcx
    movq $2,%r8
    call hia_reserved_policy
    cmpq $66,%rax
    jne bad_idle
    leaq ready_word(%rip),%rdi
    movq expected_ready(%rip),%rsi
    movq $3,%rdx
    movq %r13,%rcx
    movq $2,%r8
    call hia_reserved_policy
    cmpq $64,%rax
    jne bad_idle
    movabsq $0x900000000,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    cmpq $98,owner_word(%rip)
    jne bad_idle
    cmpq $task0_stack_top-160,slots(%rip)
    jne bad_idle
    cmpq $task1_stack_top-160,slots+8(%rip)
    jne bad_idle
    cmpq $0,slots+16(%rip)
    jne bad_idle
    cmpq $3,actual_switches(%rip)
    jne bad_idle
    incq idle_stays(%rip)
    movq %rbp,%r15
    jmp eoi
idle_choose:
    movq expected_ready(%rip),%rax
    movq %rax,pre_exchange_ready(%rip)
    leaq ready_word(%rip),%rdi
    movq expected_ready(%rip),%rsi
    movq $3,%rdx
    movq %r13,%rcx
    xorq %r8,%r8
    cmpq $1,interrupt_count(%rip)
    je reserved_call
    movq $1,%r8
    cmpq $2,%r13
    jne reserved_call
    movq $2,%r8
reserved_call:
    movq %r8,dispatch_reason(%rip)
    call hia_reserved_policy
    movq %rax,%r14
    movq actual_switches(%rip),%rdx
    leaq expected_sequence(%rip),%rcx
    cmpq (%rcx,%rdx,8),%r14
    jne bad_idle
    leaq expected_words(%rip),%rcx
    movq (%rcx,%rdx,8),%rax
    cmpq $0,rollback_this_irq(%rip)
    je compare_selected_word
    movabsq $0x200000000,%rcx
    addq %rcx,%rax
compare_selected_word:
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movq %rax,expected_ready(%rip)
compensation_done:
    /* HIA resolves the selected parked slot; independent observer checks it. */
    leaq tops(%rip),%rax
    movq (%rax,%r14,8),%r15
    subq $160,%r15
    leaq slots(%rip),%rdi
    movq $3,%rsi
    movq %r14,%rdx
    movq %r15,%rcx
    call hia_resolve_slot
    leaq slots(%rip),%rdx
    leaq (%rdx,%r14,8),%rdx
    cmpq %rdx,%rax
    jne bad_dispatch
    movq %rax,resolved_slot(%rip)
    /* Rejection of a stale frame and out-of-range index is independent. */
    leaq slots(%rip),%rdi
    movq $3,%rsi
    movq %r14,%rdx
    leaq 8(%r15),%rcx
    call hia_resolve_slot
    testq %rax,%rax
    jne bad_dispatch
    leaq slots(%rip),%rdi
    movq $3,%rsi
    movq $3,%rdx
    movq %r15,%rcx
    call hia_resolve_slot
    testq %rax,%rax
    jne bad_dispatch
    leaq slots(%rip),%rax
    leaq (%rax,%r13,8),%rdi
    movq %rbp,%rsi
    leaq tops(%rip),%rdx
    movq (%rdx,%r13,8),%rdx
    movq resolved_slot(%rip),%rcx
    movq (%rcx),%r15
    movq %r15,%r8
    leaq tops(%rip),%r9
    movq (%r9,%r14,8),%r9
    movq %r9,%rax
    subq $160,%rax
    cmpq %rax,%r15
    jne bad_handoff
    /* A valid in-stack but stale target must leave both slots unchanged. */
    call composed_forward_args
    subq $8,%r8
    call hia_bounded_frame_compose
    cmpq $9,%rax
    jne bad_handoff
    call composed_forward_args
    orq $65536,%rsi
    call hia_bounded_frame_compose
    cmpq $6,%rax
    jne bad_handoff
    call composed_forward_args
    /* A table crossing the 1 GiB extent must be rejected before access. */
    movq $1073741816,%rdi
    call hia_bounded_frame_compose
    cmpq $6,%rax
    jne bad_handoff
    leaq slots(%rip),%rax
    cmpq $0,(%rax,%r13,8)
    jne bad_handoff
    cmpq %r15,(%rax,%r14,8)
    jne bad_handoff
    movq expected_ready(%rip),%rax
    cmpq %rax,ready_word(%rip)
    jne bad_handoff
    call composed_forward_args
    call hia_bounded_frame_compose
    testq %rax,%rax
    jne bad_handoff
    leaq slots(%rip),%rax
    cmpq %rbp,(%rax,%r13,8)
    jne bad_handoff
    cmpq $0,(%rax,%r14,8)
    jne bad_handoff
    cmpq $0,rollback_this_irq(%rip)
    jne frame_rollback_done
    /* Exact stale owner refusal, then reverse under the original live owner. */
    movq owner_word(%rip),%rax
    movq %rax,prior_owner(%rip)
    addq $32,%rax
    movq %rax,prior_owner(%rip)
    call publish_owner
    cmpq $9,%rax
    jne bad_idle
    subq $32,prior_owner(%rip)
    movq prior_owner(%rip),%rax
    cmpq %rax,owner_word(%rip)
    jne bad_idle
    /* Stale owner, malformed topology, wrong departing ID and owner-stack
       alias must refuse before the actual combined reversal. */
    call guarded_reverse_args
    addq $32,%rsi
    call hia_guarded_reverse
    cmpq $9,%rax
    jne bad_idle
    call guarded_reverse_args
    btsq $48,%rdi
    call hia_guarded_reverse
    cmpq $6,%rax
    jne bad_idle
    call guarded_reverse_args
    btcq $38,%rdi
    call hia_guarded_reverse
    cmpq $6,%rax
    jne bad_idle
    call guarded_reverse_args
    shrq $32,%rdi
    shlq $32,%rdi
    orq %rbp,%rdi
    call hia_guarded_reverse
    cmpq $6,%rax
    jne bad_idle
    leaq slots(%rip),%rax
    cmpq %rbp,(%rax,%r13,8)
    jne bad_idle
    cmpq $0,(%rax,%r14,8)
    jne bad_idle
    call guarded_reverse_args
    call hia_guarded_reverse
    testq %rax,%rax
    jne bad_idle
    leaq slots(%rip),%rax
    cmpq $0,(%rax,%r13,8)
    jne bad_idle
    cmpq %r15,(%rax,%r14,8)
    jne bad_idle
    call guarded_reverse_args
    call hia_guarded_reverse
    cmpq $9,%rax
    jne bad_idle
    movq prior_owner(%rip),%rax
    cmpq %rax,owner_word(%rip)
    jne bad_idle
    movq expected_ready(%rip),%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    call compensate_mixed
    testq %rax,%rax
    jne bad_idle
    movq pre_exchange_ready(%rip),%rax
    movabsq $0x200000000,%rcx
    addq %rcx,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movq %rax,expected_ready(%rip)
    call compensate_mixed
    cmpq $66,%rax
    jne bad_idle
    movq expected_ready(%rip),%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    incq rollback_this_irq(%rip)
    incq frame_rollbacks(%rip)
    jmp idle_choose
frame_rollback_done:
    /* One native CAS publishes the new owner generation after handoff. */
    movq owner_word(%rip),%rax
    movq %rax,prior_owner(%rip)
owner_valid:
    call publish_owner
    testq %rax,%rax
    jne bad_owner
    movq actual_switches(%rip),%rax
    incq %rax
    shlq $5,%rax
    orq %r14,%rax
    cmpq %rax,owner_word(%rip)
    jne bad_owner
    /* The exact stale old owner may not publish again. */
    call publish_owner
    cmpq $9,%rax
    jne bad_owner
    movq actual_switches(%rip),%rax
    incq %rax
    shlq $5,%rax
    orq %r14,%rax
    cmpq %rax,owner_word(%rip)
    jne bad_owner
    /* All slots are now parked except selected, including blocked task 2. */
    leaq slots(%rip),%rax
    leaq tops(%rip),%rdx
    xorq %rcx,%rcx
slot_loop:
    cmpq %r14,%rcx
    je empty_slot
    movq (%rdx,%rcx,8),%rsi
    subq $160,%rsi
    cmpq %rsi,(%rax,%rcx,8)
    jne bad_handoff
    jmp next_slot
empty_slot:
    cmpq $0,(%rax,%rcx,8)
    jne bad_handoff
next_slot:
    incq %rcx
    cmpq $3,%rcx
    jb slot_loop
    incq actual_switches(%rip)
    movq $0,rollback_this_irq(%rip)
    jmp eoi
composed_forward_args:
    leaq slots(%rip),%rdi
    movq %r14,%rsi
    shlq $11,%rsi
    movq %r13,%rax
    shlq $6,%rax
    orq %rax,%rsi
    orq $3,%rsi
    movq %rbp,%rdx
    leaq tops(%rip),%rax
    movq (%rax,%r13,8),%rcx
    movq %r15,%r8
    movq (%rax,%r14,8),%r9
    ret
guarded_reverse_args:
    movq %r14,%rax
    shlq $11,%rax
    movq %r13,%rdi
    shlq $6,%rdi
    orq %rax,%rdi
    orq $3,%rdi
    shlq $32,%rdi
    leaq owner_word(%rip),%rax
    orq %rax,%rdi
    movq prior_owner(%rip),%rsi
    leaq slots(%rip),%rdx
    movq %rbp,%rcx
    movq %r15,%r8
    leaq tops(%rip),%rax
    movq (%rax,%r14,8),%r9
    shlq $32,%r9
    orq (%rax,%r13,8),%r9
    ret
guard_reverse:
    subq $8,%rsp
    leaq owner_word(%rip),%rdi
    movq prior_owner(%rip),%rsi
    leaq slots(%rip),%rdx
    movq $3,%rcx
    movq %rbp,%r8
    movq %r14,%r9
    call hia_guard_frame_rollback
    addq $8,%rsp
    ret
compensate_mixed:
    subq $8,%rsp
    leaq ready_word(%rip),%rdi
    movq pre_exchange_ready(%rip),%rsi
    movq $3,%rdx
    movq %r13,%rcx
    movq %r14,%r8
    movq dispatch_reason(%rip),%r9
    call hia_reserved_compensation
    addq $8,%rsp
    ret
publish_owner:
    /* Nested helper adjusts stack to ordinary SysV call alignment. */
    subq $8,%rsp
    leaq owner_word(%rip),%rdi
    movq prior_owner(%rip),%rsi
    leaq slots(%rip),%rdx
    movq $3,%rcx
    movq %rbp,%r8
    movq %r14,%r9
    call hia_publish_bounded_owner
    addq $8,%rsp
    ret
supervisor_eoi:
    leaq resume_frame(%rip),%r15
eoi:
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    call f4
    testq %rax,%rax
    jne abort
    testl $VBIT,0x120(%r12)
    jnz abort
    movq %r15,%rax
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    ret
task_done:
    cmpq resume_rsp(%rip),%rsp
    jne abort
    movabsq $APIC,%r12
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl expected_count(%rip),%edx
    call f5
    testq %rax,%rax
    jne abort
    cmpq $6,interrupt_count(%rip)
    jne bad_idle
    cmpq $1,idle_stays(%rip)
    jne bad_idle
    cmpq $4,actual_switches(%rip)
    jne bad_idle
    cmpq $4,frame_rollbacks(%rip)
    jne bad_idle
    cmpq $0,rollback_this_irq(%rip)
    jne bad_idle
    cmpq $128,owner_word(%rip)
    jne bad_idle
    movabsq $0xd00000000,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    cmpq $3,departures(%rip)
    jne bad_idle
    cmpq $1,departures+8(%rip)
    jne bad_idle
    cmpq $2,departures+16(%rip)
    jne bad_idle
    movq idle_blocked0(%rip),%rax
    cmpq %rax,progress(%rip)
    jbe bad_idle
    movq idle_blocked1(%rip),%rax
    cmpq %rax,progress+8(%rip)
    jne bad_idle
    cmpq $2,progress+16(%rip)
    jne bad_idle
    cmpq $0x12345678,ready_before(%rip)
    jne abort
    cmpq $0x23456789,ready_after(%rip)
    jne abort
    cmpq $0x34567890,owner_before(%rip)
    jne abort
    cmpq $0x45678901,owner_after(%rip)
    jne abort
    cmpq $0x12345678,task0_stack(%rip)
    jne abort
    cmpq $0x23456789,task0_stack_top(%rip)
    jne abort
    cmpq $0x12345678,task1_stack(%rip)
    jne abort
    cmpq $0x23456789,task1_stack_top(%rip)
    jne abort
    cmpq $0x12345678,task2_stack(%rip)
    jne abort
    cmpq $0x23456789,task2_stack_top(%rip)
    jne abort

    movl old_timer_div(%rip),%eax
    movl %eax,0x3e0(%r12)
    movl old_timer_lvt(%rip),%eax
    movl %eax,0x320(%r12)
    movq saved_gs_base(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
    movl old_tpr(%rip),%eax
    movl %eax,0x80(%r12)
    movl old_svr(%rip),%eax
    movl %eax,0xf0(%r12)
    movb old_pic1(%rip),%al
    outb %al,$0x21
    movb old_pic2(%rip),%al
    outb %al,$0xa1
    movb $'P',%bl
    movl $0x10,%eax
    jmp finish
frame_ud_handler:
#ifdef HIA_IRQ_IRET_NOP
    leaq hia_irq_entry(%rip),%rax
    addq $HIA_IRQ_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $1,actual_switches(%rip)
    jne abort
    cmpq $33,owner_word(%rip)
    jne abort
    movb $'R',%bl
    jmp rejected
#else
    jmp abort
#endif
bad_idle:
    movb $'I',%bl
    jmp rejected
bad_running_block:
    movb $'K',%bl
    jmp rejected
bad_frame_rollback:
    movb $'F',%bl
    jmp rejected
bad_compensation:
    movb $'C',%bl
    jmp rejected
bad_dispatch:
    movb $'D',%bl
    jmp rejected
bad_exchange:
    movb $'X',%bl
    jmp rejected
bad_handoff:
    movb $'H',%bl
    jmp rejected
bad_owner:
    movb $'O',%bl
    jmp rejected
bad_publish:
    movb $'B',%bl
    jmp rejected
bad_gpr:
    movb $'G',%bl
rejected:
    movl $0x11,%eax
    jmp finish
abort:
    movb $'A',%bl
    movl $0x12,%eax
    jmp finish
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

.balign 8
tops: .quad task0_stack_top,task1_stack_top,task2_stack_top
starts: .quad task0_loop,task1_loop,task2_loop
ends: .quad task0_end,task1_end,task2_end
expected_sequence: .quad 1,0,2,0
expected_words: .quad 0x100000001,0x400000000,0x700000000,0xb00000000
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

.balign 8
expected_count: .skip 4
requested_ticks: .skip 4
window_irqs: .skip 8

.balign 8
tick_guard_lo: .skip 8
native_ticks: .skip 8
tick_guard_hi: .skip 8
quantum_events: .skip 8
tick_missing: .skip 8
drained_irqs: .skip 8

.balign 16
.balign 16
task0_stack: .skip 16384
task0_stack_top: .skip 8
.balign 16
task1_stack: .skip 16384
task1_stack_top: .skip 8
.balign 16
task2_stack: .skip 16384
task2_stack_top: .skip 8

.balign 16
resume_frame: .skip 160
resume_rsp: .skip 8
slots: .skip 24
progress: .skip 24
last_progress: .skip 24
departures: .skip 24
saved_gs_base: .skip 8
irq_dispatch_slot: .skip 8
ready_before: .skip 8
ready_word: .skip 8
ready_after: .skip 8
expected_ready: .skip 8
owner_before: .skip 8
owner_word: .skip 8
owner_after: .skip 8
prior_owner: .skip 8
actual_switches: .skip 8
pre_exchange_ready: .skip 8
frame_rollbacks: .skip 8
compensations: .skip 8
ready_changes: .skip 8
owner_refusals: .skip 8

.balign 8
resolved_slot: .skip 8

.balign 8
block_request: .skip 8
blocked_progress: .skip 8

.balign 8
idle_request0: .skip 8
idle_request1: .skip 8
idle_blocked0: .skip 8
idle_blocked1: .skip 8

.balign 8
idle_stays: .skip 8

.balign 8
rollback_this_irq: .skip 8
dispatch_reason: .skip 8
