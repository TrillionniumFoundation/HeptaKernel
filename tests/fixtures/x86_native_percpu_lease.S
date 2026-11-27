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
    cmpq $0x12345678,slab+64(%rip)
    jne abort
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
    /* Actual AP1 with count one, exact one-CPU layout: must refuse. */
    leaq slab(%rip),%rdi
    leaq slab+24576(%rip),%rsi
    movl $1,%edx
    leaq callback(%rip),%rcx
    movl $4,%r8d
    xorl %r9d,%r9d
    call f1
    testq %rax,%rax
    jne bad_id
    movq $1,ap_done(%rip)
    mfence
ap_idle:
    cli
    hlt
    jmp ap_idle

/* R13 own descriptor, R14 other descriptor, R15 own low. */
check_cpu:
    subq $8,%rsp
    movq %r13,%rax
    call set_gs
    xorl %r8d,%r8d
    xorl %r9d,%r9d
    call invoke
    cmpq %r13,%rax
    jne bad_id
    cmpq $1,24(%r13)
    jne bad_commit
    /* A duplicate acquire of the same generation cannot succeed. */
    xorl %r8d,%r8d
    xorl %r9d,%r9d
    call invoke
    testq %rax,%rax
    jne bad_stale
    cmpq $1,24(%r13)
    jne abort
    /* An odd token cannot acquire; a release must explicitly say release. */
    movl $1,%r8d
    xorl %r9d,%r9d
    call invoke
    testq %rax,%rax
    jne bad_op
    cmpq $1,24(%r13)
    jne abort
    movl $1,%r8d
    movl $1,%r9d
    call invoke
    cmpq %r13,%rax
    jne bad_id
    cmpq $2,24(%r13)
    jne bad_commit
    movl $1,%r8d
    movl $1,%r9d
    call invoke
    testq %rax,%rax
    jne bad_stale
    /* Reject a peer GS even with valid layout and a live expected token. */
    movq %r14,%rax
    call set_gs
    movl $2,%r8d
    xorl %r9d,%r9d
    call invoke
    testq %rax,%rax
    jne bad_gs
    movq %r13,%rax
    call set_gs
    /* Descriptor corruption must not consume the free generation. */
    leaq callback+1(%rip),%rax
    movq %rax,0(%r13)
    movl $2,%r8d
    xorl %r9d,%r9d
    call invoke
    testq %rax,%rax
    jne bad_callback
    cmpq $2,24(%r13)
    jne abort
    leaq callback(%rip),%rax
    movq %rax,0(%r13)
    /* Test-only injection, not a lifecycle reset API. */
    /* Final even token cannot acquire an unreleasable final odd token. */
    movq $-2,24(%r13)
    movq $-2,%r8
    xorl %r9d,%r9d
    call invoke
    testq %rax,%rax
    jne bad_wrap
    cmpq $-2,24(%r13)
    jne abort
    movq $-1,24(%r13)
    movq $-1,%r8
    movl $1,%r9d
    call invoke
    testq %rax,%rax
    jne bad_wrap
    cmpq $-1,24(%r13)
    jne abort
    movq $2,24(%r13)
    movl $2,%r8d
    xorl %r9d,%r9d
    call invoke
    cmpq %r13,%rax
    jne bad_id
    cmpq $3,24(%r13)
    jne bad_commit
    movl $3,%r8d
    movl $1,%r9d
    call invoke
    cmpq %r13,%rax
    jne bad_id
    cmpq $4,24(%r13)
    jne bad_commit
    addq $8,%rsp
    ret
bad_commit:
    movb $'C',%bl
    jmp reject
bad_stale:
    movb $'D',%bl
    jmp reject
bad_op:
    movb $'O',%bl
    jmp reject
bad_wrap:
    movb $'W',%bl
    jmp reject
set_gs:
    movq %rax,%rdx
    shrq $32,%rdx
    movl $0xc0000101,%ecx
    wrmsr
    ret
invoke:
    subq $8,%rsp
    leaq slab(%rip),%rdi
    leaq slab+45056(%rip),%rsi
    movl $2,%edx
    leaq callback(%rip),%rcx
    call f1
    addq $8,%rsp
    ret
callback:
    /* Not invoked by the subject; caller-supplied executable identity only. */
    ret
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
.balign 4096
slab: .skip 45056
