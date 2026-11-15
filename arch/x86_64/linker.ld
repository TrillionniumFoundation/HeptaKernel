/* SPDX-License-Identifier: GPL-2.0-only
 * Link non-HIA boot observer and unchanged HIA-generated ELF64 object.
 * objcopy may wrap the linked image as elf32-i386 for QEMU Multiboot loading;
 * this does not translate or alter the 64-bit HIA instruction bytes.
 */
OUTPUT_FORMAT(elf64-x86-64)
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)
PHDRS
{
    text PT_LOAD FLAGS(5);
    data PT_LOAD FLAGS(6);
}
SECTIONS
{
    . = 0x100000;
    __kernel_start = .;
    .multiboot ALIGN(4) : { KEEP(*(.multiboot)) } :text
    .text ALIGN(16) : { *(.text.boot) *(.text .text.*) } :text
    .rodata ALIGN(16) : { *(.rodata.boot) *(.rodata .rodata.*) } :text
    .data ALIGN(4096) : { *(.data .data.*) } :data
    .bss ALIGN(4096) (NOLOAD) :
    {
        __bss_start = .;
        *(.bss.boot) *(.bss .bss.*) *(COMMON)
        . = ALIGN(4096);
        __bss_end = .;
    } :data
    __kernel_end = .;
    /DISCARD/ : { *(.note.GNU-stack) *(.comment) *(.eh_frame*) }
    ASSERT(__kernel_end <= 0x400000,
           "kernel/static state/stack overlaps the physical test arena")
    ASSERT((__bss_end - __bss_start) % 4 == 0,
           "BSS zeroing requires a word-aligned extent")
}
