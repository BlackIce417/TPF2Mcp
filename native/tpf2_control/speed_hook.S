    .text
    .globl speed_hook_entry
    .def speed_hook_entry; .scl 2; .type 32; .endef
speed_hook_entry:
    movq %rsp, %r11
    subq $0x58, %rsp
    movq 0x28(%r11), %rax
    movq %rax, 0x20(%rsp)
    movq 0x30(%r11), %rax
    movq %rax, 0x28(%rsp)
    movq 0x38(%r11), %rax
    movq %rax, 0x30(%rsp)
    movq 0x40(%r11), %rax
    movq %rax, 0x38(%rsp)
    movq 0x48(%r11), %rax
    movq %rax, 0x40(%rsp)
    xorq %rax, %rax
    testq %rbp, %rbp
    jz 1f
    movq -0x80(%rbp), %rax
1:
    movq %rax, 0x48(%rsp)
    call speed_hook_c
    addq $0x58, %rsp
    ret
