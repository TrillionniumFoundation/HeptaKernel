/* NON-HIA Multiboot and independent APIC/interrupt observer.
 * HIA f0/f1 calibrate, f2 derives counts, f3 arms, f4 EOIs, f5 stops.
 * Native f7/f8/f9/f10 own reference PIT; f11 composes the whole window. */
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

    inb $0x61,%al
    movb %al,saved_port61(%rip)
    andb $0xfc,%al
    outb %al,$0x61
    /* Invalid combined window budget must reject before changing gate. */
    movl $60000,%edi
    xorl %esi,%esi
    call f11
    cmpq $6,%rax
    jne abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
#ifndef HIA_TEST_COMPOSE_PIT_START_NOP
    /* Exhaustion after starting must actually stop, not leave a running gate. */
    movl $60000,%edi
    movl $1,%esi
    call f11
    cmpq $12,%rax
    jne abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
#endif
    movl $12000,%r15d
    call sample
#if defined(HIA_TEST_DIV_NOP) || defined(HIA_TEST_COUNT_NOP) || defined(HIA_TEST_BAD_BASE) || defined(HIA_TEST_STALE) || defined(HIA_TEST_STOP_COUNT_NOP) || defined(HIA_TEST_COMPOSE_PIT_START_NOP)
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
    /* Independent integer oracle, widened before arithmetic. HIA f3
     * computes the same period internally from the actual native samples. */
#ifdef HIA_TEST_LONG_PERIOD
    movl $24000,requested_ticks(%rip)
#else
    movl $12000,requested_ticks(%rip)
#endif
    movl short_native(%rip),%eax
    movl long_native(%rip),%edx
    leaq (%rdx,%rax,2),%rax
#ifdef HIA_TEST_LONG_PERIOD
    incq %rax
    shrq $1,%rax
#else
    addq $2,%rax
    shrq $2,%rax
#endif
    cmpq $1024,%rax
    jb abort
    cmpq $0x7fffffff,%rax
    ja abort
    movl %eax,expected_count(%rip)
    movl short_native(%rip),%edi
    movl long_native(%rip),%esi
    movl requested_ticks(%rip),%edx
    call f2
    cmpl expected_count(%rip),%eax
    jne abort
    /* Invalid calibration and unsupported period must have no writes. */
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    xorl %edx,%edx
    movl long_native(%rip),%ecx
    movl requested_ticks(%rip),%r8d
    call f3
    testq %rax,%rax
    jnz abort
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl short_native(%rip),%edx
    movl long_native(%rip),%ecx
    movl $11999,%r8d
    call f3
    testq %rax,%rax
    jnz abort
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    cmpl $0x10051,0x320(%r12)
    jne abort
    cmpl $0,0x3e0(%r12)
    jne abort
#ifdef HIA_TEST_INVALID_ONLY
    movb $'B',%bl
    jmp done
#endif
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl short_native(%rip),%edx
    movl long_native(%rip),%ecx
    movl requested_ticks(%rip),%r8d
    call f3
#ifdef HIA_TEST_PERIODIC_COUNT_NOP
    cmpq $15,%rax
    jne abort
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    cmpl $0x20051,0x320(%r12)
    jne abort
    cmpl $3,0x3e0(%r12)
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    movb $'N',%bl
    jmp done
#else
    movl expected_count(%rip),%ecx
    cmpq %rcx,%rax
    jne abort
    cmpl %ecx,0x380(%r12)
    jne abort
    cmpl $3,0x3e0(%r12)
    jne abort
    cmpl $0x20051,0x320(%r12)
    jne abort
    /* Outside ISR the native tick must reject without writing. */
    leaq native_ticks(%rip),%rdi
    xorq %rsi,%rsi
    movq saved_apic_msr(%rip),%rdx
    call f12
    cmpq $11,%rax
    jne abort
    cmpq $0,native_ticks(%rip)
    jne abort
    movq $0x11223344,tick_guard_lo(%rip)
    movq $0x55667788,tick_guard_hi(%rip)

#endif
    /* Independent observer bridge: actual two kernel stack contexts. */
    leaq schedule_word(%rip),%rdi
    movl $2,%esi
    movq saved_apic_msr(%rip),%rdx
    call f13
    cmpq $11,%rax
    jne abort
    cmpq $0,schedule_word(%rip)
    jne abort
    movq $0x76543210,schedule_guard_lo(%rip)
    movq $0x11223344,schedule_guard_hi(%rip)
    /* Preserve the supervisor's continuation in a separate synthetic frame. */
    movq %rsp,resume_rsp(%rip)
    leaq resume_frame(%rip),%rdi
    leaq task_done(%rip),%rax
    movq %rax,120(%rdi)
    movq $0x18,128(%rdi)
    movq $2,136(%rdi)
    movq %rsp,144(%rdi)
    movq $0x10,152(%rdi)
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
    movq %rdi,task0_frame(%rip)
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
    movq %rdi,task1_frame(%rip)
    movq $0x12345678,task1_stack(%rip)
    movq $0x23456789,task1_stack_top(%rip)

    movq task0_frame(%rip),%rdi
    /* Boot initialization: the currently running task has no parked frame. */
    movq $0,task0_frame(%rip)
    movq $0x5555,%r15
    call hia_restore_frame
    jmp abort
task0_loop:
    cmpq $1048577,%rax
    jne abort
    cmpq $1048850,%rbx
    jne abort
    cmpq $1049123,%rcx
    jne abort
    cmpq $1049396,%rdx
    jne abort
    cmpq $1049669,%rsi
    jne abort
    cmpq $1049942,%rdi
    jne abort
    cmpq $1050215,%rbp
    jne abort
    cmpq $1050488,%r8
    jne abort
    cmpq $1050761,%r9
    jne abort
    cmpq $1051034,%r10
    jne abort
    cmpq $1051307,%r11
    jne abort
    cmpq $1051580,%r12
    jne abort
    cmpq $1051853,%r13
    jne abort
    cmpq $1052126,%r14
    jne abort
    cmpq $1052399,%r15
    jne frame_r15_mismatch
    cmpq $task0_stack_top,%rsp
    jne abort
    incq task0_progress(%rip)
    jmp task0_loop
task0_end:
task1_loop:
    cmpq $2097153,%rax
    jne abort
    cmpq $2097426,%rbx
    jne abort
    cmpq $2097699,%rcx
    jne abort
    cmpq $2097972,%rdx
    jne abort
    cmpq $2098245,%rsi
    jne abort
    cmpq $2098518,%rdi
    jne abort
    cmpq $2098791,%rbp
    jne abort
    cmpq $2099064,%r8
    jne abort
    cmpq $2099337,%r9
    jne abort
    cmpq $2099610,%r10
    jne abort
    cmpq $2099883,%r11
    jne abort
    cmpq $2100156,%r12
    jne abort
    cmpq $2100429,%r13
    jne abort
    cmpq $2100702,%r14
    jne abort
    cmpq $2100975,%r15
    jne abort
    cmpq $task1_stack_top,%rsp
    jne abort
    incq task1_progress(%rip)
    jmp task1_loop
task1_end:

task_done:
    movabsq $APIC,%r12
    cmpq resume_rsp(%rip),%rsp
    jne abort
    cmpq $0,handler_bad(%rip)
    jne abort
    cmpq $0x76543210,schedule_guard_lo(%rip)
    jne abort
    cmpq $0x11223344,schedule_guard_hi(%rip)
    jne abort
    cmpq $0x11223344,tick_guard_lo(%rip)
    jne abort
    cmpq $0x55667788,tick_guard_hi(%rip)
    jne abort
    cmpq $0x12345678,task0_stack(%rip)
    jne abort
    cmpq $0x23456789,task0_stack_top(%rip)
    jne abort
    cmpq $0x12345678,task1_stack(%rip)
    jne abort
    cmpq $0x23456789,task1_stack_top(%rip)
    jne abort
#ifdef HIA_TEST_SWITCH_CAS_NOP
    cmpq $2,native_ticks(%rip)
    jne abort
    cmpq $0,schedule_word(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,task1_progress(%rip)
    jne abort
    cmpq $1,missing_schedule(%rip)
    jne abort
    movb $'X',%bl
#else
    cmpq $9,native_ticks(%rip)
    jne abort
    cmpq $8,schedule_word(%rip)
    jne abort
    cmpq $4,actual_switches(%rip)
    jne abort
    cmpq $4,txn_rollbacks(%rip)
    jne abort
    cmpq $4,native_owner_publications(%rip)
    jne abort
    cmpq $2,generation_replays(%rip)
    jne abort
    cmpq $4,active_task(%rip)
    jne abort
    cmpq $0,missing_schedule(%rip)
    jne abort
    cmpq $0,task0_progress(%rip)
    je abort
    cmpq $0,task1_progress(%rip)
    je abort
    cmpq $2,task0_departures(%rip)
    jne abort
    cmpq $2,task1_departures(%rip)
    jne abort
    cmpq $0,task0_frame(%rip)
    jne abort
    cmpq $task1_stack_top-160,task1_frame(%rip)
    jne abort
    movb $'P',%bl
#endif
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    movl expected_count(%rip),%edx
    call f5
    testq %rax,%rax
    jnz abort
    cmpl $0x30051,0x320(%r12)
    jne abort
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    /* Drain only a pending vector, using the separate masked handler path. */
    sti
    nop
    nop
    cli
    movq interrupt_count(%rip),%r13
    call pit_window
    cmpq %r13,interrupt_count(%rip)
    jne abort
    cmpq $0,handler_bad(%rip)
    jne abort
    movq native_ticks(%rip),%rax
    movq interrupt_count(%rip),%rcx
    subq drained_irqs(%rip),%rcx
    cmpq %rax,%rcx
    jne abort
    movq native_ticks(%rip),%rax
    cmpq %rax,captured_frames(%rip)
    jne abort
    movq $1,window_irqs(%rip)
    jmp done
done:
    movb saved_port61(%rip),%al
    outb %al,$0x61
    jmp verify_local
pit_window:
    subq $8,%rsp
    movl $60000,%edi
    movl $0x40000000,%esi
    sti
    call f11
    cli
    testq %rax,%rax
    jnz abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
    addq $8,%rsp
    ret
sample:
    /* Native PIT prepare before APIC arm; raw APIC reads remain independent. */
    subq $8,%rsp
    movl %r15d,%edi
    call f7
    addq $8,%rsp
    testq %rax,%rax
    jnz abort
    inb $0x61,%al
    testb $0x23,%al
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
    subq $8,%rsp
    call f8
    addq $8,%rsp
#ifdef HIA_TEST_COMPOSE_PIT_START_NOP
    cmpq $10,%rax
    jne abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    subq $8,%rsp
    call f1
    addq $8,%rsp
    cmpl $0,0x380(%r12)
    jne abort
    cmpl $0,0x390(%r12)
    jne abort
    movb $'G',%bl
    ret
#endif
    testq %rax,%rax
    jnz abort
    movl $0x40000000,%edi
    subq $8,%rsp
    call f9
    addq $8,%rsp
    testq %rax,%rax
    jnz abort
    movl 0x390(%r12),%r14d
    inb $0x61,%al
    andb $0x23,%al
    cmpb $0x21,%al
    jne abort
    subq $8,%rsp
    call f10
    addq $8,%rsp
    testq %rax,%rax
    jnz abort
    inb $0x61,%al
    testb $3,%al
    jnz abort
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
    cmpq $0,handler_bad(%rip)
    jne abort
#if defined(HIA_TEST_INVALID_ONLY) || defined(HIA_TEST_PERIODIC_COUNT_NOP) || defined(HIA_TEST_COMPOSE_PIT_START_NOP)
    cmpq $0,interrupt_count(%rip)
    jne abort
#else
    cmpq $0,window_irqs(%rip)
    je abort
#endif
    jmp restore
restore:
    movq saved_gs_base(%rip),%rax
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
    rdmsr
    shlq $32,%rdx
    orq %rdx,%rax
    cmpq saved_gs_base(%rip),%rax
    jne abort
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

/* Ordinary SysV frame-dispatch callback. The IDT points directly to
 * hia_irq_entry; all original GPR capture and IRETQ are native HIA.
 * These three pushes preserve the callback's own callee-saved ABI. */
.balign 16
irq_dispatch:
    pushq %rbp
    pushq %r12
    pushq %r13
    movq %rdi,%rbp
    movabsq $APIC,%r12
    incq interrupt_count(%rip)
    testl $VBIT,0x120(%r12)
    jz abort
    testl $0x10000,0x320(%r12)
    jz running_tick
    incq drained_irqs(%rip)
    jmp normal_eoi
running_tick:
    /* Verify the actual interrupted RIP and old RSP belong to active task. */
    testq $1,active_task(%rip)
    jnz check_task1
    movq 120(%rbp),%rax
    cmpq $task0_loop,%rax
    jb abort
    cmpq $task0_end,%rax
    jae abort
    cmpq $task0_stack_top,144(%rbp)
    jne abort
    jmp checked_frame
check_task1:
    testq $1,active_task(%rip)
    jz abort
    movq 120(%rbp),%rax
    cmpq $task1_loop,%rax
    jb abort
    cmpq $task1_end,%rax
    jae abort
    cmpq $task1_stack_top,144(%rbp)
    jne abort
checked_frame:
    cmpq $0x18,128(%rbp)
    jne abort
    cmpq $0x10,152(%rbp)
    jne abort
    testq $0x200,136(%rbp)
    jz abort
    testq $1,active_task(%rip)
    jz capture_task0
    jmp capture_task1
capture_task0:
    cmpq $1048577,112(%rbp)
    jne abort
    cmpq $1048850,104(%rbp)
    jne abort
    cmpq $1049123,96(%rbp)
    jne abort
    cmpq $1049396,88(%rbp)
    jne abort
    cmpq $1049669,80(%rbp)
    jne abort
    cmpq $1049942,72(%rbp)
    jne abort
    cmpq $1050215,64(%rbp)
    jne abort
    cmpq $1050488,56(%rbp)
    jne abort
    cmpq $1050761,48(%rbp)
    jne abort
    cmpq $1051034,40(%rbp)
    jne abort
    cmpq $1051307,32(%rbp)
    jne abort
    cmpq $1051580,24(%rbp)
    jne abort
    cmpq $1051853,16(%rbp)
    jne abort
    cmpq $1052126,8(%rbp)
    jne abort
#ifdef HIA_TEST_IRQ_SAVE_MUTANT
    cmpq $1052126,0(%rbp)
    jne abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $0,native_ticks(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'S',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $1052399,0(%rbp)
    jne abort
#endif
    jmp capture_checked
capture_task1:
    cmpq $2097153,112(%rbp)
    jne abort
    cmpq $2097426,104(%rbp)
    jne abort
    cmpq $2097699,96(%rbp)
    jne abort
    cmpq $2097972,88(%rbp)
    jne abort
    cmpq $2098245,80(%rbp)
    jne abort
    cmpq $2098518,72(%rbp)
    jne abort
    cmpq $2098791,64(%rbp)
    jne abort
    cmpq $2099064,56(%rbp)
    jne abort
    cmpq $2099337,48(%rbp)
    jne abort
    cmpq $2099610,40(%rbp)
    jne abort
    cmpq $2099883,32(%rbp)
    jne abort
    cmpq $2100156,24(%rbp)
    jne abort
    cmpq $2100429,16(%rbp)
    jne abort
    cmpq $2100702,8(%rbp)
    jne abort
    cmpq $2100975,0(%rbp)
    jne abort
    jmp capture_checked
capture_checked:
    incq captured_frames(%rip)
    leaq native_ticks(%rip),%rdi
    movq interrupt_count(%rip),%rsi
    decq %rsi
    movq saved_apic_msr(%rip),%rdx
    call f12
    movq interrupt_count(%rip),%rcx
    cmpq %rcx,native_ticks(%rip)
    jne abort
    andq $1,%rcx
    xorq $1,%rcx
    cmpq %rcx,%rax
    jne abort
    cmpq $9,native_ticks(%rip)
    je supervisor_eoi
    testq %rax,%rax
    jz normal_eoi
    /* Only HIA's returned quantum decision can enter the selector. */
    leaq schedule_word(%rip),%rdi
    movq native_ticks(%rip),%rsi
    incq %rsi
    movq saved_apic_msr(%rip),%rdx
    call f13
    cmpq $6,%rax
    jne abort
#ifndef HIA_TEST_SWITCH_CAS_NOP
    leaq schedule_word(%rip),%rdi
    movq native_ticks(%rip),%rsi
    addq $2,%rsi
    movq saved_apic_msr(%rip),%rdx
    call f13
    cmpq $9,%rax
    jne abort
#endif
    leaq schedule_word(%rip),%rdi
    movq native_ticks(%rip),%rsi
    movq saved_apic_msr(%rip),%rdx
    call f13
    movq native_ticks(%rip),%rcx
    shrq $1,%rcx
    andq $1,%rcx
    cmpq %rcx,%rax
    jne abort
#ifdef HIA_TEST_SWITCH_CAS_NOP
    cmpq $0,schedule_word(%rip)
    jne abort
    incq missing_schedule(%rip)
    jmp supervisor_eoi
#else
    movq native_ticks(%rip),%rcx
    cmpq %rcx,schedule_word(%rip)
    jne abort
    movq %rax,selected_task(%rip)
    leaq schedule_word(%rip),%rdi
    movq native_ticks(%rip),%rsi
    movq saved_apic_msr(%rip),%rdx
    call f13
    cmpq $9,%rax
    jne abort
    movq active_task(%rip),%rcx
    andq $1,%rcx
    cmpq selected_task(%rip),%rcx
    je abort
    /* Preserve original fixture controls in legacy mode. The new path
     * observes a composed HIA handoff before publishing active_task. */
#if defined(HIA_TEST_PARK_CAS_NOP) || defined(HIA_TEST_UNPARK_CAS_NOP)
    /* Independent progress oracle: each departing task made new progress. */
    testq $1,active_task(%rip)
    jnz save_task1
    movq task0_progress(%rip),%rcx
    cmpq task0_last_progress(%rip),%rcx
    jbe abort
    movq %rcx,task0_last_progress(%rip)
    incq task0_departures(%rip)
    leaq task0_frame(%rip),%rdi
    movq %rbp,%rsi
    leaq task0_stack+8(%rip),%rdx
    leaq task0_stack_top(%rip),%rcx
    call hia_publish_frame
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_PARK_CAS_NOP
    cmpq $0,task0_frame(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'V',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq %rbp,task0_frame(%rip)
    jne abort
    /* Duplicate publication must refuse without altering the parked frame. */
    leaq task0_frame(%rip),%rdi
    movq %rbp,%rsi
    leaq task0_stack+8(%rip),%rdx
    leaq task0_stack_top(%rip),%rcx
    call hia_publish_frame
    cmpq $9,%rax
    jne abort
    cmpq %rbp,task0_frame(%rip)
    jne abort
#endif
    jmp saved_frame
save_task1:
    movq task1_progress(%rip),%rcx
    cmpq task1_last_progress(%rip),%rcx
    jbe abort
    movq %rcx,task1_last_progress(%rip)
    incq task1_departures(%rip)
    leaq task1_frame(%rip),%rdi
    movq %rbp,%rsi
    leaq task1_stack+8(%rip),%rdx
    leaq task1_stack_top(%rip),%rcx
    call hia_publish_frame
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_PARK_CAS_NOP
    cmpq $0,task1_frame(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'V',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq %rbp,task1_frame(%rip)
    jne abort
    /* Duplicate publication must refuse without altering the parked frame. */
    leaq task1_frame(%rip),%rdi
    movq %rbp,%rsi
    leaq task1_stack+8(%rip),%rdx
    leaq task1_stack_top(%rip),%rcx
    call hia_publish_frame
    cmpq $9,%rax
    jne abort
    cmpq %rbp,task1_frame(%rip)
    jne abort
#endif
saved_frame:
    movq selected_task(%rip),%rax
    movq %rax,active_task(%rip)
    incq actual_switches(%rip)
    cmpq $0,%rax
    jne select_task1
    movq task0_frame(%rip),%r13
    leaq task0_frame(%rip),%rdi
    movq %r13,%rsi
    leaq task0_stack+8(%rip),%rdx
    leaq task0_stack_top(%rip),%rcx
    call hia_consume_frame
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_UNPARK_CAS_NOP
    cmpq %r13,task0_frame(%rip)
    jne abort
    cmpq $1,actual_switches(%rip)
    jne abort
    movb $'W',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $0,task0_frame(%rip)
    jne abort
    leaq task0_frame(%rip),%rdi
    movq %r13,%rsi
    leaq task0_stack+8(%rip),%rdx
    leaq task0_stack_top(%rip),%rcx
    call hia_consume_frame
    cmpq $9,%rax
    jne abort
    cmpq $0,task0_frame(%rip)
    jne abort
#endif
    jmp switch_eoi
select_task1:
    movq task1_frame(%rip),%r13
    leaq task1_frame(%rip),%rdi
    movq %r13,%rsi
    leaq task1_stack+8(%rip),%rdx
    leaq task1_stack_top(%rip),%rcx
    call hia_consume_frame
    testq %rax,%rax
    jnz abort
#ifdef HIA_TEST_UNPARK_CAS_NOP
    cmpq %r13,task1_frame(%rip)
    jne abort
    cmpq $1,actual_switches(%rip)
    jne abort
    movb $'W',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $0,task1_frame(%rip)
    jne abort
    leaq task1_frame(%rip),%rdi
    movq %r13,%rsi
    leaq task1_stack+8(%rip),%rdx
    leaq task1_stack_top(%rip),%rcx
    call hia_consume_frame
    cmpq $9,%rax
    jne abort
    cmpq $0,task1_frame(%rip)
    jne abort
#endif
    jmp switch_eoi
#else
    testq $1,active_task(%rip)
    jnz txn_from1
    movq task0_progress(%rip),%rcx
    cmpq task0_last_progress(%rip),%rcx
    jbe abort
    movq %rcx,task0_last_progress(%rip)
    incq task0_departures(%rip)
    leaq task0_frame(%rip),%rdi
    leaq task0_stack_top(%rip),%rdx
    leaq task1_frame(%rip),%rcx
    leaq task1_stack_top(%rip),%r9
    jmp txn_args
txn_from1:
    testq $1,active_task(%rip)
    jz abort
    movq task1_progress(%rip),%rcx
    cmpq task1_last_progress(%rip),%rcx
    jbe abort
    movq %rcx,task1_last_progress(%rip)
    incq task1_departures(%rip)
    leaq task1_frame(%rip),%rdi
    leaq task1_stack_top(%rip),%rdx
    leaq task0_frame(%rip),%rcx
    leaq task0_stack_top(%rip),%r9
txn_args:
    movq %rdi,txn_src_slot(%rip)
    movq %rdx,txn_src_top(%rip)
    movq %rcx,txn_dst_slot(%rip)
    movq %r9,txn_dst_top(%rip)
    /* Native dispatch chooses the actual slot from the live generation.
     * The independent observer's expected slot is retained only as an oracle. */
    leaq active_task(%rip),%rdi
    movq active_task(%rip),%rsi
    addq $2,%rsi
    leaq task0_frame(%rip),%rdx
    leaq task1_frame(%rip),%rcx
    call hia_select_parked_slot
#ifdef HIA_TEST_DISPATCH_CAS_NOP
    cmpq txn_dst_slot(%rip),%rax
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb  must refuse before either changes. */
    movq %rbp,%rsi
    movq %rdi,%rcx
    movq %r13,%r8
    call hia_switch_frames
    cmpq $6,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq %r13,(%rax)
    jne abort
#if !defined(HIA_TEST_TX_PARK_NOP) && !defined(HIA_TEST_TX_CONSUME_NOP)
    /* A well-shaped but stale destination pointer forces rollback. */
    movq txn_src_slot(%rip),%rdi
    movq %rbp,%rsi
    movq txn_src_top(%rip),%rdx
    movq txn_dst_slot(%rip),%rcx
    leaq -8(%r13),%r8
    movq txn_dst_top(%rip),%r9
    call hia_switch_frames
    cmpq $9,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq %r13,(%rax)
    jne abort
    incq txn_rollbacks(%rip)
#endif
#ifdef HIA_TEST_TX_MISSING
    /* Independently inject an absent target on the first handoff. */
    cmpq $0,actual_switches(%rip)
    jne abort
    movq txn_dst_slot(%rip),%rax
    movq $0,(%rax)
#endif
    movq txn_src_slot(%rip),%rdi
    movq %rbp,%rsi
    movq txn_src_top(%rip),%rdx
    movq txn_dst_slot(%rip),%rcx
    movq %r13,%r8
    movq txn_dst_top(%rip),%r9
    call hia_switch_frames
#ifdef HIA_TEST_TX_MISSING
    cmpq $9,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'T',%bl
    movl $0x11,%eax
    jmp finish
#else
    testq %rax,%rax
    jnz abort
    movq txn_src_slot(%rip),%rax
#ifdef HIA_TEST_TX_PARK_NOP
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    movb $'D',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq %rbp,(%rax)
    jne abort
#endif
    movq txn_dst_slot(%rip),%rax
#ifdef HIA_TEST_TX_CONSUME_NOP
    cmpq %r13,(%rax)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    movb $'C',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $0,(%rax)
    jne abort
#endif
    /* Check the native owner CAS independently. An injected missing park
     * or busy target happens only after both observer readbacks. */
    movq active_task(%rip),%rax
    movq %rax,txn_prior_owner(%rip)
#ifdef HIA_TEST_ACTIVE_NO_PARK
    movq txn_src_slot(%rip),%rax
    movq $0,(%rax)
#elif defined(HIA_TEST_ACTIVE_DST_BUSY)
    movq txn_dst_slot(%rip),%rax
    movq %r13,(%rax)
#else
#ifndef HIA_TEST_ACTIVE_CAS_NOP
    /* Same-task future generation and exhausted counter must refuse. */
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    addq $2,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    leaq active_task(%rip),%rdi
    movq $-1,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $6,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    /* Replay the previous same-parity generation after a complete task cycle. */
    cmpq $2,txn_prior_owner(%rip)
    jb no_generation_replay
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    subq $2,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    incq generation_replays(%rip)
#ifdef HIA_TEST_OWNER_GENERATION_REPLAY
    cmpq $2,active_task(%rip)
    jne abort
    cmpq $2,actual_switches(%rip)
    jne abort
    movb $'G',%bl
    movl $0x11,%eax
    jmp finish
#endif
no_generation_replay:
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    xorq $1,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
#endif
#endif
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
#ifdef HIA_TEST_ACTIVE_NO_PARK
    cmpq $9,%rax
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'H',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_ACTIVE_DST_BUSY)
    cmpq $9,%rax
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'B',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_ACTIVE_CAS_NOP)
    testq %rax,%rax
    jnz abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'U',%bl
    movl $0x11,%eax
    jmp finish
#else
    testq %rax,%rax
    jnz abort
    movq txn_prior_owner(%rip),%rax
    incq %rax
    cmpq %rax,active_task(%rip)
    jne abort
    andq $1,%rax
    cmpq selected_task(%rip),%rax
    jne abort
    /* The exact old owner cannot publish a second time. */
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    incq %rax
    cmpq %rax,active_task(%rip)
    jne abort
    andq $1,%rax
    cmpq selected_task(%rip),%rax
    jne abort
    incq native_owner_publications(%rip)
    incq actual_switches(%rip)
    jmp switch_eoi
#endif
#endif
#endif
#endif
supervisor_eoi:
    leaq resume_frame(%rip),%r13
    jmp switch_eoi
normal_eoi:
    movq %rbp,%r13
switch_eoi:
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    call f4
    testq %rax,%rax
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    /* Return selected original frame; the raw native gate validates and
     * restores it, not this callback. */
    movq %r13,%rax
    popq %r13
    popq %r12
    popq %rbp
    ret
frame_ud_handler:
#ifdef HIA_TEST_IRQ_IRET_NOP
    leaq hia_irq_entry(%rip),%rax
    addq $HIA_TEST_IRQ_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $1,captured_frames(%rip)
    jne abort
    cmpq $1,native_ticks(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'I',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_FRAME_IRET_NOP)
    leaq hia_restore_frame(%rip),%rax
    addq $HIA_TEST_FRAME_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    cmpq $0,task0_progress(%rip)
    jne abort
    movb $'R',%bl
    movl $0x11,%eax
    jmp finish
#else
    jmp abort
#endif
frame_r15_mismatch:
#ifdef HIA_TEST_FRAME_GPR_MUTANT
    cmpq $task0_stack_top,%rsp
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    cmpq $0,task0_progress(%rip)
    jne abort
    cmpq $0,task1_progress(%rip)
    jne abort
    movb $'Y',%bl
    movl $0x11,%eax
    jmp finish
#else
    jmp abort
#endif
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
task0_stack: .skip 16384
task0_stack_top: .skip 8
.balign 16
task1_stack: .skip 16384
task1_stack_top: .skip 8
.balign 16
resume_frame: .skip 160
resume_rsp: .skip 8
task0_frame: .skip 8
task1_frame: .skip 8
active_task: .skip 8
selected_task: .skip 8
task0_progress: .skip 8
task1_progress: .skip 8
task0_last_progress: .skip 8
task1_last_progress: .skip 8
task0_departures: .skip 8
task1_departures: .skip 8
actual_switches: .skip 8
missing_schedule: .skip 8
schedule_guard_lo: .skip 8
schedule_word: .skip 8
schedule_guard_hi: .skip 8

.balign 8
saved_gs_base: .skip 8
irq_dispatch_slot: .skip 8
captured_frames: .skip 8
.balign 8
txn_src_slot: .skip 8
txn_src_top: .skip 8
txn_dst_slot: .skip 8
txn_dst_top: .skip 8
txn_rollbacks: .skip 8
.balign 8
txn_prior_owner: .skip 8
native_owner_publications: .skip 8
generation_replays: .skip 8
L',%bl
    movl $0x11,%eax
    jmp finish
#else
    testq %rax,%rax
    jnz abort
    leaq active_task(%rip),%rdi
    movq active_task(%rip),%rsi
    leaq task0_frame(%rip),%rdx
    movq %rdx,%rcx
    call hia_select_parked_slot
    testq %rax,%rax
    jnz abort
    leaq active_task(%rip),%rdi
    movq active_task(%rip),%rsi
    leaq task0_frame(%rip),%rdx
    leaq task1_frame(%rip),%rcx
    call hia_select_parked_slot
    cmpq txn_dst_slot(%rip),%rax
    jne abort
    movq (%rax),%r13
    movq %rax,txn_dst_slot(%rip)
    testq %r13,%r13
    jz abort
    movq txn_src_slot(%rip),%rdi
    cmpq $0,(%rdi)
    jne abort
#endif
    /* Source/destination slot alias must refuse before either changes. */
    movq %rbp,%rsi
    movq %rdi,%rcx
    movq %r13,%r8
    call hia_switch_frames
    cmpq $6,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq %r13,(%rax)
    jne abort
#if !defined(HIA_TEST_TX_PARK_NOP) && !defined(HIA_TEST_TX_CONSUME_NOP)
    /* A well-shaped but stale destination pointer forces rollback. */
    movq txn_src_slot(%rip),%rdi
    movq %rbp,%rsi
    movq txn_src_top(%rip),%rdx
    movq txn_dst_slot(%rip),%rcx
    leaq -8(%r13),%r8
    movq txn_dst_top(%rip),%r9
    call hia_switch_frames
    cmpq $9,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq %r13,(%rax)
    jne abort
    incq txn_rollbacks(%rip)
#endif
#ifdef HIA_TEST_TX_MISSING
    /* Independently inject an absent target on the first handoff. */
    cmpq $0,actual_switches(%rip)
    jne abort
    movq txn_dst_slot(%rip),%rax
    movq $0,(%rax)
#endif
    movq txn_src_slot(%rip),%rdi
    movq %rbp,%rsi
    movq txn_src_top(%rip),%rdx
    movq txn_dst_slot(%rip),%rcx
    movq %r13,%r8
    movq txn_dst_top(%rip),%r9
    call hia_switch_frames
#ifdef HIA_TEST_TX_MISSING
    cmpq $9,%rax
    jne abort
    movq txn_src_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'T',%bl
    movl $0x11,%eax
    jmp finish
#else
    testq %rax,%rax
    jnz abort
    movq txn_src_slot(%rip),%rax
#ifdef HIA_TEST_TX_PARK_NOP
    cmpq $0,(%rax)
    jne abort
    movq txn_dst_slot(%rip),%rax
    cmpq $0,(%rax)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    movb $'D',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq %rbp,(%rax)
    jne abort
#endif
    movq txn_dst_slot(%rip),%rax
#ifdef HIA_TEST_TX_CONSUME_NOP
    cmpq %r13,(%rax)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    movb $'C',%bl
    movl $0x11,%eax
    jmp finish
#else
    cmpq $0,(%rax)
    jne abort
#endif
    /* Check the native owner CAS independently. An injected missing park
     * or busy target happens only after both observer readbacks. */
    movq active_task(%rip),%rax
    movq %rax,txn_prior_owner(%rip)
#ifdef HIA_TEST_ACTIVE_NO_PARK
    movq txn_src_slot(%rip),%rax
    movq $0,(%rax)
#elif defined(HIA_TEST_ACTIVE_DST_BUSY)
    movq txn_dst_slot(%rip),%rax
    movq %r13,(%rax)
#else
#ifndef HIA_TEST_ACTIVE_CAS_NOP
    /* Same-task future generation and exhausted counter must refuse. */
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    addq $2,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    leaq active_task(%rip),%rdi
    movq $-1,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $6,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    /* Replay the previous same-parity generation after a complete task cycle. */
    cmpq $2,txn_prior_owner(%rip)
    jb no_generation_replay
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    subq $2,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
    incq generation_replays(%rip)
#ifdef HIA_TEST_OWNER_GENERATION_REPLAY
    cmpq $2,active_task(%rip)
    jne abort
    cmpq $2,actual_switches(%rip)
    jne abort
    movb $'G',%bl
    movl $0x11,%eax
    jmp finish
#endif
no_generation_replay:
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    xorq $1,%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    cmpq %rax,active_task(%rip)
    jne abort
#endif
#endif
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
#ifdef HIA_TEST_ACTIVE_NO_PARK
    cmpq $9,%rax
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'H',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_ACTIVE_DST_BUSY)
    cmpq $9,%rax
    jne abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'B',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_ACTIVE_CAS_NOP)
    testq %rax,%rax
    jnz abort
    cmpq $0,active_task(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'U',%bl
    movl $0x11,%eax
    jmp finish
#else
    testq %rax,%rax
    jnz abort
    movq txn_prior_owner(%rip),%rax
    incq %rax
    cmpq %rax,active_task(%rip)
    jne abort
    andq $1,%rax
    cmpq selected_task(%rip),%rax
    jne abort
    /* The exact old owner cannot publish a second time. */
    leaq active_task(%rip),%rdi
    movq txn_prior_owner(%rip),%rsi
    movq txn_src_slot(%rip),%rdx
    movq %rbp,%rcx
    movq txn_dst_slot(%rip),%r8
    call hia_publish_owner
    cmpq $9,%rax
    jne abort
    movq txn_prior_owner(%rip),%rax
    incq %rax
    cmpq %rax,active_task(%rip)
    jne abort
    andq $1,%rax
    cmpq selected_task(%rip),%rax
    jne abort
    incq native_owner_publications(%rip)
    incq actual_switches(%rip)
    jmp switch_eoi
#endif
#endif
#endif
#endif
supervisor_eoi:
    leaq resume_frame(%rip),%r13
    jmp switch_eoi
normal_eoi:
    movq %rbp,%r13
switch_eoi:
    movq %r12,%rdi
    movq saved_apic_msr(%rip),%rsi
    call f4
    testq %rax,%rax
    jnz abort
    testl $VBIT,0x120(%r12)
    jnz abort
    /* Return selected original frame; the raw native gate validates and
     * restores it, not this callback. */
    movq %r13,%rax
    popq %r13
    popq %r12
    popq %rbp
    ret
frame_ud_handler:
#ifdef HIA_TEST_IRQ_IRET_NOP
    leaq hia_irq_entry(%rip),%rax
    addq $HIA_TEST_IRQ_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    cmpq $1,interrupt_count(%rip)
    jne abort
    cmpq $1,captured_frames(%rip)
    jne abort
    cmpq $1,native_ticks(%rip)
    jne abort
    cmpq $0,actual_switches(%rip)
    jne abort
    movb $'I',%bl
    movl $0x11,%eax
    jmp finish
#elif defined(HIA_TEST_FRAME_IRET_NOP)
    leaq hia_restore_frame(%rip),%rax
    addq $HIA_TEST_FRAME_TRAP_DELTA,%rax
    cmpq %rax,(%rsp)
    jne abort
    cmpq $0x18,8(%rsp)
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    cmpq $0,task0_progress(%rip)
    jne abort
    movb $'R',%bl
    movl $0x11,%eax
    jmp finish
#else
    jmp abort
#endif
frame_r15_mismatch:
#ifdef HIA_TEST_FRAME_GPR_MUTANT
    cmpq $task0_stack_top,%rsp
    jne abort
    cmpq $0,interrupt_count(%rip)
    jne abort
    cmpq $0,task0_progress(%rip)
    jne abort
    cmpq $0,task1_progress(%rip)
    jne abort
    movb $'Y',%bl
    movl $0x11,%eax
    jmp finish
#else
    jmp abort
#endif
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
task0_stack: .skip 16384
task0_stack_top: .skip 8
.balign 16
task1_stack: .skip 16384
task1_stack_top: .skip 8
.balign 16
resume_frame: .skip 160
resume_rsp: .skip 8
task0_frame: .skip 8
task1_frame: .skip 8
active_task: .skip 8
selected_task: .skip 8
task0_progress: .skip 8
task1_progress: .skip 8
task0_last_progress: .skip 8
task1_last_progress: .skip 8
task0_departures: .skip 8
task1_departures: .skip 8
actual_switches: .skip 8
missing_schedule: .skip 8
schedule_guard_lo: .skip 8
schedule_word: .skip 8
schedule_guard_hi: .skip 8

.balign 8
saved_gs_base: .skip 8
irq_dispatch_slot: .skip 8
captured_frames: .skip 8
.balign 8
txn_src_slot: .skip 8
txn_src_top: .skip 8
txn_dst_slot: .skip 8
txn_dst_top: .skip 8
txn_rollbacks: .skip 8
.balign 8
txn_prior_owner: .skip 8
native_owner_publications: .skip 8
generation_replays: .skip 8
