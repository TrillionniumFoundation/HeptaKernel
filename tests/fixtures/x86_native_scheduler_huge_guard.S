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
    /* Split first identity-mapped 2 MiB into 512 supervisor RW leaves. */
    movl $pt0,%eax
    orl $3,%eax
    movl %eax,pd0
    movl $0,pd0+4
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
    /* Dedicated IST1 for page faults even when the scheduler stack is exhausted. */
    leaq fault_stack_top(%rip),%rax
    movq %rax,tss64+36(%rip)
    movw $104,tss64+102(%rip)
    leaq tss64(%rip),%rax
    leaq gdt_tss(%rip),%rdi
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
    movw $0x20,%ax
    ltr %ax
    leaq guard_pf_handler(%rip),%rax
    leaq idt+14*16(%rip),%rdi
    movw %ax,(%rdi)
    movw $0x18,2(%rdi)
    movb $1,4(%rdi)
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
    leaq scheduler_stack(%rip),%rax
    movq %rax,irq_dispatch_slot+8(%rip)
    leaq scheduler_stack_top(%rip),%rax
    movq %rax,irq_dispatch_slot+16(%rip)
    movq $0,irq_dispatch_slot+24(%rip)
#ifdef HIA_SCHED_BUSY
    movq $1,irq_dispatch_slot+24(%rip)
#endif
#ifdef HIA_SCHED_BAD_BOUNDS
    subq $8,irq_dispatch_slot+16(%rip)
#endif
#ifdef HIA_SCHED_ALIAS
    leaq task0_stack(%rip),%rax
    movq %rax,irq_dispatch_slot+8(%rip)
    leaq task0_stack_top(%rip),%rax
    movq %rax,irq_dispatch_slot+16(%rip)
#endif
    leaq irq_dispatch_slot(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr

    /* Warm the exact guard leaf, then revoke it using the HIA native CAS. */
    movq $0x55667788,scheduler_guard(%rip)
    leaq scheduler_guard(%rip),%r8
    movq %r8,%rax
    shrq $12,%rax
    leaq pt0(%rip),%rcx
    leaq (%rcx,%rax,8),%rax
    movq %rax,guard_leaf(%rip)
    movq (%rax),%r9
    movq %r9,guard_original(%rip)
    /* Guard admission must refuse an alternate VA mapping the same physical page. */
    leaq pt0+511*8(%rip),%rax
    movq (%rax),%r10
    movq %r10,alias_original(%rip)
    leaq scheduler_guard(%rip),%r10
    orq $3,%r10
    movq %r10,(%rax)
    invlpg (0x1ff000)
    cmpq $0x55667788,0x1ff000
    jne guard_bad
    call guard_args
    call hia_scheduler_guard
    cmpq $6,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    movq guard_original(%rip),%rdx
    cmpq %rdx,(%rax)
    jne guard_bad
    leaq pt0+511*8(%rip),%rax
    movq (%rax),%r10
    andq $-4096,%r10
    cmpq $scheduler_guard,%r10
    jne guard_bad
    movq alias_original(%rip),%r10
    movq %r10,(%rax)
    invlpg (0x1ff000)
    /* Genuine 2 MiB sibling alias of the low physical range. */
    movq pd0+8(%rip),%rax
    movq %rax,huge_original(%rip)
    movq $0x83,pd0+8(%rip)
    leaq scheduler_guard(%rip),%rax
    addq $0x200000,%rax
    invlpg (%rax)
    cmpq $0x55667788,(%rax)
    jne guard_bad
    call guard_args
    call hia_scheduler_guard
    cmpq $6,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    movq guard_original(%rip),%rdx
    cmpq %rdx,(%rax)
    jne guard_bad
    movq pd0+8(%rip),%rax
    andq $-2097152,%rax
    jne guard_bad
    movq huge_original(%rip),%rax
    movq %rax,pd0+8(%rip)
    leaq scheduler_guard(%rip),%rax
    addq $0x200000,%rax
    invlpg (%rax)
    call guard_args
    xorq $64,%r9
    call hia_scheduler_guard
    cmpq $9,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    movq guard_original(%rip),%rdx
    cmpq %rdx,(%rax)
    jne guard_bad
    call guard_args
    addq $8,%r8
    call hia_scheduler_guard
    cmpq $6,%rax
    jne guard_bad
    call guard_args
    leaq fault_stack(%rip),%rdi
    call hia_scheduler_guard
    cmpq $6,%rax
    jne guard_bad
    /* A fully valid-looking but unlinked leaf table must fail the parent walk. */
    leaq pt0(%rip),%rsi
    leaq fake_pt(%rip),%rdi
    movl $512,%ecx
    cld
    rep movsq
    call guard_args
    leaq fake_pt(%rip),%rcx
    call hia_scheduler_guard
    cmpq $6,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    movq guard_original(%rip),%rdx
    cmpq %rdx,(%rax)
    jne guard_bad
#ifndef HIA_GUARD_MAPPED
    /* Rewarm the original mapping after the independent alias probes. */
    cmpq $0x55667788,scheduler_guard(%rip)
    jne guard_bad
    call guard_args
    call hia_scheduler_guard
    testq %rax,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    cmpq $0,(%rax)
    jne guard_bad
    call guard_args
    call hia_scheduler_guard
    cmpq $9,%rax
    jne guard_bad
#endif
    movq guard_leaf(%rip),%rax
    movq 8(%rax),%rdx
    andq $-4096,%rdx
    cmpq $scheduler_stack,%rdx
    jne guard_bad
    testq $1,8(%rax)
    jz guard_bad
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
    /* All low 512 bytes are immutable canaries, including the original first qword. */
    movq $0x12345678,%rax
    leaq task0_stack(%rip),%rdi
    movl $64,%ecx
    rep stosq
    leaq task1_stack(%rip),%rdi
    movl $64,%ecx
    rep stosq
    leaq task2_stack(%rip),%rdi
    movl $64,%ecx
    rep stosq
    leaq scheduler_stack(%rip),%rdi
    movl $64,%ecx
    rep stosq
#ifdef HIA_SCHED_PRE_CANARY
    movq $0,scheduler_stack+504(%rip)
#endif
#ifdef HIA_STACK_CANARY_FAULT
    movq $0,task1_stack+504(%rip)
#endif

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
    cmpq $0,interrupt_count(%rip)
    je 1f
    cmpq $0,irq_dispatch_slot+24(%rip)
    jne scheduler_bad
1:
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
    cmpq $0,interrupt_count(%rip)
    je 1f
    cmpq $0,irq_dispatch_slot+24(%rip)
    jne scheduler_bad
1:
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
    cmpq $0,interrupt_count(%rip)
    je 1f
    cmpq $0,irq_dispatch_slot+24(%rip)
    jne scheduler_bad
1:
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
    cmpq $scheduler_stack_top-8,%rsp
    jne scheduler_bad
    cmpq $1,irq_dispatch_slot+24(%rip)
    jne scheduler_bad
#ifdef HIA_GUARD_OVERFLOW
    /* Intentional fault injection: consume stack to its exact lower bound. */
    leaq scheduler_stack(%rip),%rsp
guard_push:
    pushq %rax
    /* A mapped guard must reach this sentinel; no successful test can. */
    movb $'M',%bl
    movl $0x11,%eax
    jmp finish
#endif
    pushq %rbp
    pushq %r12
    pushq %r13
    pushq %r14
    pushq %r15
    movq %rdi,%rbp
    call verify_stack_canaries
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
    movq %r13,%r14
    movq %rbp,%r15
    movq owner_word(%rip),%rax
    movq %rax,prior_owner(%rip)
    movq $2,dispatch_reason(%rip)
    movabsq $0x800000000,%rax
    movq %rax,pre_exchange_ready(%rip)
    call rollback_compose_args
    call hia_stack_bounded
    cmpq $66,%rax
    jne bad_idle
    testl $VBIT,0x120(%r12)
    jz bad_eoi
    movq expected_ready(%rip),%rax
    movq %rax,pre_exchange_ready(%rip)
    call rollback_compose_args
    call hia_stack_bounded
    cmpq %rbp,%rax
    jne bad_idle
    movq %rax,native_return_frame(%rip)
    testl $VBIT,0x120(%r12)
    jnz bad_eoi
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
    movq native_return_frame(%rip),%r15
    jmp eoi
idle_choose:
    movq expected_ready(%rip),%rax
    movq %rax,pre_exchange_ready(%rip)
    movq owner_word(%rip),%rax
    movq %rax,prior_owner(%rip)
    movq actual_switches(%rip),%rdx
    leaq expected_sequence(%rip),%rcx
    movq (%rcx,%rdx,8),%r14
    leaq tops(%rip),%rax
    movq (%rax,%r14,8),%r15
    subq $160,%r15
    movq $0,dispatch_reason(%rip)
    cmpq $1,interrupt_count(%rip)
    je dispatch_args
    movq $1,dispatch_reason(%rip)
    cmpq $2,%r13
    jne dispatch_args
    movq $2,dispatch_reason(%rip)
dispatch_args:
    /* Bad ready alias and wrong expected target must not mutate ready or slots. */
    call rollback_compose_args
    leaq owner_word(%rip),%rax
    shlq $32,%rax
    movl %edx,%edx
    orq %rax,%rdx
    call hia_stack_bounded
    cmpq $65,%rax
    jne bad_idle
    call rollback_compose_args
    btcq $43,%rdi
    call hia_stack_bounded
    cmpq $65,%rax
    jne bad_idle
    movq pre_exchange_ready(%rip),%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    leaq slots(%rip),%rax
    cmpq $0,(%rax,%r13,8)
    jne bad_handoff
    cmpq %r15,(%rax,%r14,8)
    jne bad_handoff
    call rollback_compose_args
    cmpq $0,rollback_this_irq(%rip)
    jne unified_call
#ifndef HIA_DISPATCH_OWNER_REFUSE
    /* A stale but in-stack target triggers actual pre-frame refusal. */
    movabsq $0x800000000,%rax
    subq %rax,%rcx
#endif
unified_call:
#ifdef HIA_FRAME_CORRUPT_OFFSET
    cmpq $0,rollback_this_irq(%rip)
    je no_content_fault
    movq $HIA_FRAME_CORRUPT_VALUE,HIA_FRAME_CORRUPT_OFFSET(%r15)
no_content_fault:
#endif
    call hia_stack_bounded
#if defined(HIA_FAILSTOP_PARTIAL) || defined(HIA_FAILSTOP_UNKNOWN)
    jmp missing_trap
#endif
#ifdef HIA_FAILSTOP_EOI
    cmpq $71,%rax
    je missing_trap
#endif
#ifdef HIA_DISPATCH_PARTIAL
    cmpq $67,%rax
    jne bad_idle
    testl $VBIT,0x120(%r12)
    jz bad_eoi
    leaq slots(%rip),%rax
    cmpq $0,(%rax,%r13,8)
    jne bad_handoff
    cmpq %r15,(%rax,%r14,8)
    jne bad_handoff
    cmpq $0,owner_word(%rip)
    jne bad_owner
    movabsq $0x100000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movb $'Z',%bl
    jmp rejected
#endif
    cmpq $0,rollback_this_irq(%rip)
    jne unified_committed
    cmpq $69,%rax
    jne bad_idle
    testl $VBIT,0x120(%r12)
    jz bad_eoi
    leaq slots(%rip),%rax
    cmpq $0,(%rax,%r13,8)
    jne bad_handoff
    cmpq %r15,(%rax,%r14,8)
    jne bad_handoff
    movq prior_owner(%rip),%rax
    cmpq %rax,owner_word(%rip)
    jne bad_owner
    movq pre_exchange_ready(%rip),%rax
    movabsq $0x200000000,%rcx
    addq %rcx,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
#ifdef HIA_DISPATCH_OWNER_REFUSE
    movb $'V',%bl
    jmp rejected
#endif
    movq %rax,expected_ready(%rip)
    call compensate_mixed
    cmpq $66,%rax
    jne bad_idle
    incq rollback_this_irq(%rip)
    incq frame_rollbacks(%rip)
    jmp idle_choose
unified_committed:
#ifdef HIA_FRAME_CORRUPT_OFFSET
    /* A return on malformed content must never reach IRETQ. */
    cmpq $HIA_FRAME_CORRUPT_VALUE,HIA_FRAME_CORRUPT_OFFSET(%r15)
    jne abort
    movb $'N',%bl
    jmp rejected
#endif
#ifdef HIA_TERMINAL_EOI_FAIL
    cmpq $71,%rax
    jne bad_eoi
    testl $VBIT,0x120(%r12)
    jz bad_eoi
#else
    cmpq %r15,%rax
    jne bad_owner
    movq %rax,native_return_frame(%rip)
    testl $VBIT,0x120(%r12)
    jnz bad_eoi
#endif
    movq actual_switches(%rip),%rdx
    leaq expected_words(%rip),%rcx
    movq (%rcx,%rdx,8),%rax
    movabsq $0x200000000,%rcx
    addq %rcx,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movq %rax,expected_ready(%rip)
    xorq %rax,%rax
forward_committed:
    testq %rax,%rax
    jne bad_owner
    leaq slots(%rip),%rax
    cmpq %rbp,(%rax,%r13,8)
    jne bad_handoff
    cmpq $0,(%rax,%r14,8)
    jne bad_handoff
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
#ifdef HIA_TERMINAL_EOI_FAIL
    cmpq $1,actual_switches(%rip)
    jne bad_eoi
    movb $'E',%bl
    jmp rejected
#endif
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
rollback_compose_args:
    movq %r14,%rax
    shlq $11,%rax
    movq %r13,%rdi
    shlq $6,%rdi
    orq %rax,%rdi
    orq $3,%rdi
    movq dispatch_reason(%rip),%rax
    shlq $16,%rax
    orq %rax,%rdi
    shlq $32,%rdi
    leaq owner_word(%rip),%rax
    orq %rax,%rdi
    movq prior_owner(%rip),%rsi
    leaq ready_word(%rip),%rdx
    shlq $32,%rdx
    leaq slots(%rip),%rax
    orq %rax,%rdx
    movq %r15,%rcx
    shlq $32,%rcx
    orq %rbp,%rcx
    leaq tops(%rip),%rax
    movq (%rax,%r14,8),%r8
    shlq $32,%r8
    orq (%rax,%r13,8),%r8
    movq pre_exchange_ready(%rip),%r9
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
    movq %r15,native_return_frame(%rip)
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    call f4
    testq %rax,%rax
    jne abort
eoi:
    call verify_stack_canaries
    testl $VBIT,0x120(%r12)
    jnz abort
    movq native_return_frame(%rip),%rax
    cmpq %r15,%rax
    jne bad_owner
#ifdef HIA_SCHED_POST_CANARY
    movq $0,scheduler_stack+504(%rip)
#endif
#ifdef HIA_SCHED_BAD_SELECTED
    leaq scheduler_stack+1024(%rip),%rax
#endif
#ifdef HIA_SCHED_CORRUPT_SELECTED
    movq $HIA_SCHED_CORRUPT_VALUE,HIA_SCHED_CORRUPT_OFFSET(%rax)
#endif
#ifdef HIA_SCHED_RELEASE_STALE
    movq $2,irq_dispatch_slot+24(%rip)
#endif
    popq %r15
    popq %r14
    popq %r13
    popq %r12
    popq %rbp
    ret
task_done:
    cmpq $0,irq_dispatch_slot+24(%rip)
    jne scheduler_bad
    leaq scheduler_stack(%rip),%r10
    movl $64,%r11d
1:  cmpq $0x12345678,(%r10)
    jne scheduler_bad
    addq $8,%r10
    decl %r11d
    jnz 1b
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
guard_args:
    leaq pml4(%rip),%rdi
    leaq pdpt(%rip),%rsi
    leaq pd0(%rip),%rdx
    leaq pt0(%rip),%rcx
    leaq scheduler_guard(%rip),%r8
    movq guard_original(%rip),%r9
    ret
guard_bad:
    movb $'J',%bl
    movl $0x11,%eax
    jmp finish
guard_pf_handler:
#ifdef HIA_GUARD_OVERFLOW
    /* IST switched before the error frame is pushed. */
    cmpq $fault_stack,%rsp
    jb guard_bad
    cmpq $fault_stack_top,%rsp
    jae guard_bad
    cmpq $2,(%rsp)
    jne guard_bad
    cmpq $guard_push,8(%rsp)
    jne guard_bad
    cmpq $0x18,16(%rsp)
    jne guard_bad
    testq $0x200,24(%rsp)
    jnz guard_bad
    cmpq $scheduler_stack,32(%rsp)
    jne guard_bad
    movq %cr2,%rax
    cmpq $scheduler_stack-8,%rax
    jne guard_bad
    movq guard_leaf(%rip),%rax
    cmpq $0,(%rax)
    jne guard_bad
    cmpq $1,irq_dispatch_slot+24(%rip)
    jne guard_bad
    cmpq $0,interrupt_count(%rip)
    jne guard_bad
    cmpq $0,owner_word(%rip)
    jne guard_bad
    movabsq $APIC,%rax
    testl $VBIT,0x120(%rax)
    jz guard_bad
    movb $'Q',%bl
    movl $0x11,%eax
    jmp finish
#else
    jmp guard_bad
#endif
frame_ud_handler:
    call verify_stack_canaries
#ifdef HIA_NATIVE_STACK_TRAP_DELTA
    leaq hia_irq_entry(%rip),%rax
    addq $HIA_NATIVE_STACK_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpw $0x0b0f,(%rax)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    testq $0x200,16(%rsp)
    jnz abort
    cmpq $HIA_SCHED_EXPECT_BUSY,irq_dispatch_slot+24(%rip)
    jne abort
    cmpq $HIA_SCHED_EXPECT_CALLBACK,interrupt_count(%rip)
    jne abort
    movabsq $APIC,%r12
#if HIA_SCHED_EXPECT_CALLBACK == 0
    testl $VBIT,0x120(%r12)
    jz abort
    cmpq $0,owner_word(%rip)
    jne abort
#else
    testl $VBIT,0x120(%r12)
    jnz abort
    cmpq $33,owner_word(%rip)
    jne abort
    cmpq $scheduler_stack,%rsp
    jb abort
    cmpq $scheduler_stack_top,%rsp
    jae abort
#endif
    movb $'T',%bl
    jmp rejected
#else
#ifdef HIA_FRAME_CORRUPT_OFFSET
    leaq hia_stack_bounded(%rip),%rax
    subq $2,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    testq $0x200,16(%rsp)
    jnz abort
    movabsq $APIC,%r12
    testl $VBIT,0x120(%r12)
    jnz abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $33,owner_word(%rip)
    jne bad_owner
    cmpq $task0_stack_top-160,slots(%rip)
    jne bad_handoff
    cmpq $0,slots+8(%rip)
    jne bad_handoff
    cmpq $task2_stack_top-160,slots+16(%rip)
    jne bad_handoff
    movabsq $0x300000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    cmpq $0,progress+8(%rip)
    jne abort
    cmpq $0,progress+16(%rip)
    jne abort
    cmpq $1,frame_rollbacks(%rip)
    jne abort
    cmpq $HIA_FRAME_CORRUPT_VALUE,task1_stack_top-160+HIA_FRAME_CORRUPT_OFFSET(%rip)
    jne abort
    movb $'C',%bl
    jmp rejected
#elif defined(HIA_FAILSTOP_PARTIAL) || defined(HIA_FAILSTOP_UNKNOWN) || defined(HIA_FAILSTOP_EOI)
    leaq hia_stack_bounded(%rip),%rax
    addq $HIA_FAILSTOP_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    testq $0x200,16(%rsp)
    jnz abort
    movabsq $APIC,%r12
    testl $VBIT,0x120(%r12)
    jz abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,progress+8(%rip)
    jne abort
    cmpq $0,progress+16(%rip)
    jne abort
    cmpq $task2_stack_top-160,slots+16(%rip)
    jne bad_handoff
#ifdef HIA_FAILSTOP_PARTIAL
    cmpq $0,owner_word(%rip)
    jne bad_owner
    cmpq $0,slots(%rip)
    jne bad_handoff
    cmpq $task1_stack_top-160,slots+8(%rip)
    jne bad_handoff
    movabsq $0x100000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movb $'Z',%bl
#elif defined(HIA_FAILSTOP_UNKNOWN)
    cmpq $0,owner_word(%rip)
    jne bad_owner
    cmpq $task0_stack_top-160,slots(%rip)
    jne bad_handoff
    cmpq $0,slots+8(%rip)
    jne bad_handoff
    movabsq $0x100000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    movb $'U',%bl
#else
    cmpq $33,owner_word(%rip)
    jne bad_owner
    cmpq $task0_stack_top-160,slots(%rip)
    jne bad_handoff
    cmpq $0,slots+8(%rip)
    jne bad_handoff
    movabsq $0x300000001,%rax
    cmpq %rax,ready_word(%rip)
    jne bad_idle
    cmpq $1,frame_rollbacks(%rip)
    jne bad_idle
    movb $'E',%bl
#endif
    jmp rejected
#elif defined(HIA_IRQ_IRET_NOP)
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
#endif
missing_trap:
    call verify_stack_canaries
    movb $'N',%bl
    jmp rejected
verify_stack_canaries:
    leaq task0_stack(%rip),%r10
    movl $64,%r11d
1:  cmpq $0x12345678,(%r10)
    jne stack_bad
    addq $8,%r10
    decl %r11d
    jnz 1b
    leaq task1_stack(%rip),%r10
    movl $64,%r11d
2:  cmpq $0x12345678,(%r10)
    jne stack_bad
    addq $8,%r10
    decl %r11d
    jnz 2b
    leaq task2_stack(%rip),%r10
    movl $64,%r11d
3:  cmpq $0x12345678,(%r10)
    jne stack_bad
    addq $8,%r10
    decl %r11d
    jnz 3b
    ret
scheduler_bad:
    movb $'W',%bl
    jmp rejected
stack_bad:
    movb $'S',%bl
    jmp rejected
bad_eoi:
    movb $'Y',%bl
    jmp rejected
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
gdt_tss: .quad 0,0
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
pt0: .skip 4096
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
irq_dispatch_slot: .skip 32
.balign 4096
scheduler_guard: .skip 4096
scheduler_stack: .skip 16384
scheduler_stack_top:
.balign 4096
fault_stack: .skip 4096
fault_stack_top:
.balign 16
tss64: .skip 104
.balign 8
guard_leaf: .skip 8
guard_original: .skip 8
alias_original: .skip 8
huge_original: .skip 8
.balign 8
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

.balign 8
native_return_frame: .skip 8

.balign 4096
fake_pt: .skip 4096
