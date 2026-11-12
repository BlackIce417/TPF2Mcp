# Loader → Lua 共享内存命令协议

命令由 `LoaderLuaCommandClient` 统一发送。Python 写入二进制命令号和 UTF-8 JSON 参数，
Loader 校验固定头，在 Lua 游戏更新回调中取出命令。游戏 API 只在该回调中调用。
不使用远程线程，不从 Loader 后台线程访问 Lua，不读写命令文件。

Windows x64 命名对象：

| 对象 | 名称 |
| --- | --- |
| 映射 | `Local\tpf2mcp_loader_cmd_v1` |
| 生产者互斥锁 | `Local\tpf2mcp_loader_cmd_mutex_v1` |
| 完成事件 | `Local\tpf2mcp_loader_cmd_reply_v1` |

固定头64字节，小端序，对应 Python `<IIIIIIIIQQQQ`：

| 偏移 | 类型 | 字段 |
| --- | --- | --- |
| 0 | uint32 | magic `0x434c4654` |
| 4 | uint32 | ABI版本1 |
| 8 | uint32 | 头长度64 |
| 12 | uint32 | 参数区容量16384 |
| 16 | uint32 | Loader宿主PID |
| 20 | uint32 | 状态：Idle=0 / Ready=1 / Taken=2 / Complete=3 / Rejected=4 / Cancelled=5（保留） |
| 24 | uint32 | opcode |
| 28 | uint32 | UTF-8参数长度 |
| 32 | uint64 | 本次传输序列（1..2^53−1） |
| 40 | uint64 | Unix毫秒截止时间 |
| 48 | uint64 | 完成序列 |
| 56 | uint64 | 保留0 |
| 64 | byte[16384] | 请求JSON |

| 命令号 | Lua业务 |
| --- | --- |
| `0x0001` | ping |
| `0x0002` | 读取停站/车辆控制状态 |
| `0x0003` | 刷新世界快照 |
| `0x0004` | 采集指定遥测分区 |
| `0x0101` | 修改线路停站策略 |
| `0x0102` | 站内扣停 |
| `0x0103` | 解除站内扣停 |
| `0x0104` | 临时停车 |
| `0x0105` | 恢复运行 |

`0x0004` 的 `section=line_demand` 接收 `line_id`、`maximum_entities`，查询线路已分配的旅客/货物需求；
`section=station_demand_lines` 接收 `station_id`，读取该站实时连接线路和停站向量。两者均为只读，不受写权限开关影响。

请求保留现有 schema_version/request_id/command/params，params 必须带 `_expected_session_id`。
Lua 复核命令号与业务名称、存档会话、目标前置状态及写权限；回执使用 Loader 数据总线固定键
`command-response.json`，必须匹配 request_id 和 session_id。

生产者互斥锁覆盖发送至接收回执的全过程，进程退出由 Windows 释放。
只有空闲或已结束的槽可重新写入，Ready/Taken 绝不覆盖。写参数后以最后一次对齐32位状态写发布 Ready，
Loader 用 InterlockedCompareExchange 接收。此实现限定 Windows x64。
已过期的 Ready 请求被拒绝；已经进入 Taken 的请求超时代表结果未知，不取消正在执行的 Lua。
业务 command_id 去重记录与传输序列相互独立，不能换一个 command_id 盲目重试。

Loader 通过已有 Lua 5.2 ABI 返回命令号和数值块，Lua 还原 UTF-8 参数，避免在私有 Lua ABI 中自行分配字符串或操作 GC。
Loader 只在 Lua 调用时消费请求，不额外启动调用 Lua 的线程。
游戏暂停、载入或结束期间不保证命令能执行，不能据收到请求就报告成功。

需 Loader ABI 3、Lua 命令协议2。Loader 随宿主常驻，升级需重启游戏；Controller 热重载不会替换 Loader。
