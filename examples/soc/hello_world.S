 #
 # Trivial code from: https://github.com/jfng/minerva-examples.
 #


	.section .rodata
str:
	.asciz "hello, world!\n"

	.section .text
	.global _start
_start:
	la a0, str
	la a1, _out

1:	lb t0, 0(a0)
	sb t0, 0(a1)
	addi a0, a0, 1
	bnez t0, 1b

2:	j 2b
