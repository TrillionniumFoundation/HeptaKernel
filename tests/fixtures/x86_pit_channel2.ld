/* Independent NON-HIA Multiboot loader, HIA object remains unmodified. */
OUTPUT_FORMAT(elf64-x86-64)
OUTPUT_ARCH(i386:x86-64)
ENTRY(_start)
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
    . = 0x100000;
    .multiboot ALIGN(4) : { KEEP(*(.multiboot)) } :text
    .text ALIGN(16) : { *(.text.boot) *(.text .text.*) } :text
    .rodata ALIGN(16) : { *(.rodata .rodata.*) } :text
    .data ALIGN(4096) : { *(.data .data.*) } :data
    .bss ALIGN(4096) (NOLOAD) : { *(.bss .bss.*) *(COMMON) } :data
    ASSERT(. < 0x400000, "observer overlaps probe page")
}
