OUTPUT_FORMAT("elf32-littleriscv")
OUTPUT_ARCH("riscv")
ENTRY(_start)

SECTIONS
{
	. = ORIGIN(ram);

	/* Start of day code. */
	.init :
	{
		*(.init) *(.init.*)
	} > ram
	.text :
	{
		*(.text) *(.text.*)
	} > ram

	.rodata :
	{
		*(.rodata) *(.rodata.*)
	} > ram
	.sdata :
	{
		PROVIDE(__global_pointer$ = .);
		*(.sdata) *(.sdata.*)
	}
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
