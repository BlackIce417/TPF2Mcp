option casemap:none

EXTERN speed_hook_c:PROC
PUBLIC speed_hook_entry

.code
speed_hook_entry PROC
    mov r11, rsp
    sub rsp, 58h

    mov rax, qword ptr [r11 + 28h]
    mov qword ptr [rsp + 20h], rax
    mov rax, qword ptr [r11 + 30h]
    mov qword ptr [rsp + 28h], rax
    mov rax, qword ptr [r11 + 38h]
    mov qword ptr [rsp + 30h], rax
    mov rax, qword ptr [r11 + 40h]
    mov qword ptr [rsp + 38h], rax
    mov rax, qword ptr [r11 + 48h]
    mov qword ptr [rsp + 40h], rax

    xor rax, rax
    test rbp, rbp
    jz no_vehicle_pointer
    mov rax, qword ptr [rbp - 80h]
no_vehicle_pointer:
    mov qword ptr [rsp + 48h], rax

    call speed_hook_c
    add rsp, 58h
    ret
speed_hook_entry ENDP

END
