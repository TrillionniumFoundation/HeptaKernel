/* SPDX-License-Identifier: GPL-2.0-only
 * Explicit NON-HIA transport and positive physical-memory observer.
 * Included by boot.S only in the dedicated E820 discovery fixtures.
 */
.set DISCOVERY_PAGES, 3
.set DISCOVERY_ALIGN, 0x100000

/* Build a caller-owned copy of all loader rows and the known exclusions.
 * Keep the original imported snapshot for the independent exact gate.
 */
discovery_choose64:
    subq $8, %rsp
    movq $ARENA_MIN, discovery_request(%rip)
    movq $ARENA_MAX, discovery_request+8(%rip)
    movq $DISCOVERY_PAGES, discovery_request+16(%rip)
    movq $DISCOVERY_ALIGN, discovery_request+24(%rip)
    movq e820_request+16(%rip), %rcx
    cmpq $124, %rcx                   /* reserve capacity for four exclusions */
    ja fail64
    leaq e820_request+24(%rip), %rsi
    leaq discovery_request+40(%rip), %rdi
    leaq (%rcx,%rcx,2), %rcx
    rep movsq

    leaq __kernel_start(%rip), %rax
    leaq __kernel_end(%rip), %rdx
    subq %rax, %rdx
    call discovery_append_reserved64
    movl boot_info(%rip), %eax
    movq $116, %rdx
    call discovery_append_reserved64
    movl boot_info(%rip), %ecx
    movl 48(%rcx), %eax
    movl 44(%rcx), %edx
    call discovery_append_reserved64
    movq e820_request+16(%rip), %rcx
    addq $3, %rcx
#ifdef HEPTAKERNEL_TEST_E820_DISCOVERY_RESERVED
    /* A caller-declared one-byte reservation is a positive search case. */
    movq $(ARENA_MIN+1), %rax
    movq $1, %rdx
    call discovery_append_reserved64
    incq %rcx
#endif
    movq %rcx, discovery_request+32(%rip)
    leaq discovery_request(%rip), %rdi
    imulq $24, %rcx, %rsi
    addq $40, %rsi
    leaq discovery_reply(%rip), %rdx
    movq $-1, (%rdx)
    movq $-1, 8(%rdx)
    movl $16, %ecx
    leaq discovery_unused(%rip), %r8
    movl $16, %r9d
    call e820_discovery_f0
    testl %eax, %eax
    jne fail64
    cmpq $0, discovery_reply(%rip)
    jne fail64
    movq discovery_reply+8(%rip), %rax
    cmpq $ARENA_MIN, %rax
    jb fail64
    cmpq $(ARENA_MAX-DISCOVERY_PAGES*PAGE_BYTES), %rax
    ja fail64
    testq $(DISCOVERY_ALIGN-1), %rax
    jnz fail64
    /* Publish exactly this selected base and extent to the original gate. */
    movq %rax, e820_request(%rip)
    movq $DISCOVERY_PAGES, e820_request+8(%rip)
    addq $8, %rsp
    ret

discovery_append_reserved64:
    movq %rax, (%rdi)
    movq %rdx, 8(%rdi)
    movl $2, 16(%rdi)
    movl $1, 20(%rdi)
    addq $24, %rdi
    ret

/* Run only after both original exact admission gates pass. */
discovery_probe64:
    movq e820_request(%rip), %rax
    movq %rax, discovery_pmm_request+16(%rip)
    movq $0, discovery_pmm_request(%rip)
    movq $DISCOVERY_PAGES, discovery_pmm_request+8(%rip)
    movq $1, discovery_pmm_request+24(%rip)    /* one reserved prefix page */
    call discovery_pmm_call64
    cmpq $2, discovery_reply+8(%rip)
    jne fail64

    movq $4, discovery_pmm_request(%rip)      /* ALLOC_RUN */
    movq $2, discovery_pmm_request+8(%rip)
    movq $1, discovery_pmm_request+16(%rip)   /* alignment in pages */
    movq $0, discovery_pmm_request+24(%rip)
    call discovery_pmm_call64
    movq discovery_reply+8(%rip), %rax
    movq e820_request(%rip), %rdx
    addq $PAGE_BYTES, %rdx
    cmpq %rdx, %rax
    jne fail64
    /* Write/read both returned identity-mapped frames, at identical offsets.
     * Confirm distinct storage and restore the original words afterwards.
     */
    movq (%rax), %r10
    movq PAGE_BYTES(%rax), %r11
    movabsq $0x8ef7d6c5b4a39281, %rdx
    movabsq $0x17e6d5c4b3a29180, %rcx
    movq %rdx, (%rax)
    movq %rcx, PAGE_BYTES(%rax)
    cmpq %rdx, (%rax)
    jne fail64
    cmpq %rcx, PAGE_BYTES(%rax)
    jne fail64
    movq %r10, (%rax)
    movq %r11, PAGE_BYTES(%rax)
    movq %rax, %r8
    leaq discovery_allocated_hex(%rip), %rdi
    call discovery_hex64
    movq e820_request(%rip), %r8
    leaq discovery_base_hex(%rip), %rdi
    call discovery_hex64
    leaq discovery_marker(%rip), %rsi
    call puts64
    movl $0x10, %eax
    jmp debug_exit64

discovery_pmm_call64:
    /* Keep stack alignment for the native call made by this wrapper. */
    subq $8, %rsp
    leaq discovery_pmm_request(%rip), %rdi
    movl $32, %esi
    leaq discovery_reply(%rip), %rdx
    movq $-1, (%rdx)
    movq $-1, 8(%rdx)
    movl $16, %ecx
    leaq allocator_state(%rip), %r8
    movl $STATE_BYTES, %r9d
    call f0
    testl %eax, %eax
    jne fail64
    cmpq $0, discovery_reply(%rip)
    jne fail64
    addq $8, %rsp
    ret

discovery_hex64:
    leaq discovery_digits(%rip), %rdx
    movl $16, %ecx
1:
    rolq $4, %r8
    movl %r8d, %eax
    andl $15, %eax
    movb (%rdx,%rax), %al
    stosb
    loop 1b
    ret

.pushsection .rodata, "a", @progbits
discovery_digits: .ascii "0123456789abcdef"
.popsection

.pushsection .data, "aw", @progbits
discovery_marker: .ascii "HEPTAKERNEL HIA E820 PHYSICAL PMM base="
discovery_base_hex: .ascii "0000000000000000"
.ascii " allocated="
discovery_allocated_hex: .ascii "0000000000000000"
.asciz "\r\n"
.popsection

.pushsection .bss, "aw", @nobits
.balign 16
discovery_request:     .skip (40 + 128 * 24)
discovery_pmm_request: .skip 32
discovery_reply:       .skip 16
discovery_unused:      .skip 16
.popsection
