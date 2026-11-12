#pragma once

#include <Windows.h>
#include <stddef.h>
#include <stdint.h>

#define TPF2_IPC_MAGIC 0x32465054u
#define TPF2_IPC_VERSION 1u
#define TPF2_IPC_CONFIG_CAPACITY (384u * 1024u)
#define TPF2_IPC_STATUS_CAPACITY (64u * 1024u)
#define TPF2_IPC_MAPPING_NAME L"Local\\tpf2mcp_native_ipc_v1"
#define TPF2_IPC_CONFIG_EVENT_NAME L"Local\\tpf2mcp_native_config_v1"
#define TPF2_IPC_STATUS_EVENT_NAME L"Local\\tpf2mcp_native_status_v1"

struct Tpf2NativeIpc
{
    uint32_t magic;
    uint32_t version;
    uint32_t structure_size;
    uint32_t config_capacity;
    uint32_t status_capacity;
    volatile LONG config_sequence;
    volatile LONG config_length;
    volatile LONG status_sequence;
    volatile LONG status_length;
    uint32_t reserved[7];
    char config[TPF2_IPC_CONFIG_CAPACITY];
    char status[TPF2_IPC_STATUS_CAPACITY];
};

static_assert(offsetof(Tpf2NativeIpc, config) == 64, "IPC header layout changed");
static_assert(sizeof(Tpf2NativeIpc) == 64 + TPF2_IPC_CONFIG_CAPACITY + TPF2_IPC_STATUS_CAPACITY,
              "IPC mapping layout changed");
