OUTPUT_FORMAT("elf32-littleriscv")
OUTPUT_ARCH("riscv")
ENTRY(_start)

MEMORY
{
    rom : ORIGIN = 0x00000000, LENGTH = 0x00004000
    ram : ORIGIN = 0x00004000, LENGTH = 0x00004000
}

SECTIONS
{
	. = 0x00000000;

	/* Start of day code. */
	.init :
	{
		*(.init) *(.init.*)
	} > rom
	.text :
	{
		*(.text) *(.text.*)
	} > rom

	.rodata :
	{
		*(.rodata) *(.rodata.*)
	} > rom
	.sdata :
	{
		PROVIDE(__global_pointer$ = .);
		*(.sdata) *(.sdata.*)
	} > ram
	.data :
	{
		*(.data) *(.data.*)
	} > ram
	.bss :
	{
		*(.bss) *(.bss.*)
	} > ram

}

PROVIDE(__stack_top = ORIGIN(ram) + LENGTH(ram));
