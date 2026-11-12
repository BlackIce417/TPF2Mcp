# Controller 列车移动命令（实验接口）

沿用 Controller V2 共享内存命令环，Python 统一通过
`tpf2_mcp.native_ipc.ControllerCommandClient` 调用。MCP 适配层为
`mcp_server/src/tpf2_mcp/movement_mcp.py`，通过 `server.py` 向 stdio 和 HTTP 同时导出。

| 命令号 | 方法 | 行为 |
| --- | --- | --- |
| `0x0501` | `move_train_distance` | 沿当前引擎路径前进指定米数，以列车中心为基准，到点扣停 |
| `0x0502` | `move_train_route` | 替换为调用方给出的有序、有向引擎轨道子边序列，到指定子边内的位置扣停 |
| `0x0503` | `release_train_movement` | 解除接管；替换过路径时，先从当前位置重算原线路的路径 |
| `0x0504` | `get_train_movement` | 查询请求的实际执行状态 |

## 二进制布局

字段均为小端序，C++ 结构采用 `pack(1)`。命令环本身的 ABI 版本仍为 2。

`0x0501` 负载为 24 字节：

```text
uint64 movement_id
uint32 vehicle_id
float32 speed_mps
float32 distance_m
uint32 expires_in_seconds
```

`0x0502` 负载为 6176 字节：

```text
uint64 movement_id
uint32 vehicle_id
float32 speed_mps
uint32 expires_in_seconds
uint32 target_index
float32 target_offset_m
uint32 edge_count
edges[512] = { uint32 entity, int32 index, uint32 direction }
```

其中 `entity/index/direction` 对应原生 `transport::Path` 中的运输网络子边；
`direction` 必须为整数 0 或 1。这里不能使用简化拓扑图的边编号。
`target_offset_m` 沿该有向子边从入口开始计量，不是贝塞尔参数或 `position01`。

`0x0503`、`0x0504` 负载均为一个 8 字节的 `uint64 movement_id`。
命令环槽位的 `flags` 位 0 表示要求预检目标处的原线路恢复路径。
Python `move_train_route` 默认开启该位，并要求 Controller 声明
`movement_return_check` 能力；旧 DLL 缺少能力时直接报错。

## 执行与边界

IPC 返回成功只表示命令已受理。调用方须继续查询：

```text
PENDING -> APPLYING -> MOVING -> HELD
                           -> RESTORING -> RELEASED
校验失败 -> REJECTED
```

同一 `movement_id`、负载及 flags 重试不会重复执行；异参返回冲突。
每列车同时只允许一个活跃请求；不支持规则事务。

- 目前接管对象为已经在途的铁路车辆，不负责站台装卸和发车流程。
- 指定序列从采样时的列车中心所在子边开始，必须保留整列车前半段已经占用的路径。
  采样后跨入下一子边时可能被拒绝，调用方应重新读取路径。
- 目标后必须有容纳前半列车的继续轨道，并在末端保护子边之前多留 10 米。
- 原生轨道速度、技术最高速度和进路预留仍然有效；不能穿过其他列车占用的轨道。
  技术最高速度字段不会被修改。
- 默认在实际移动前，从目标处的假想车头路径预检原下一站是否可达。
  不可达返回 `NORMAL_ROUTE_UNREACHABLE_FROM_TARGET`，不修改车辆位置或路径。
- 显式设置 `require_resumable_route=False` 可选择任意目标。这需要调用方另行安排回程。
  恢复寻路失败时状态保持 `RESTORING/WAITING_FOR_NORMAL_ROUTE` 并扣停，不能将其当作已恢复运行。
- 看门狗时间包含行走与扣停，范围 5～600 秒。到期触发恢复，不保证不可达位置能自动脱困。
- 热卸载前必须完成恢复；仍有无法恢复的接管时，Controller 会拒绝卸载。

## 引擎调用约束

只在游戏更新线程操作引擎；命令线程只入队。路径提交位于游戏自己的
`BeginModification/EndModification` 批次中，使用原生组件通知处理预留和模型状态。
调用引擎期间释放命令锁，避免通知重入锁死。

恢复使用底层 `vehicle_util::def::SetPathToStation`，只提交 `MovePath`。
不得使用高层 `SetPathToStationDeferred` 冒充一次发车，否则可能改写站间发车时间历史。
世界身份来自仿真采集帧的 `session_id`；引擎快照指针和 GUI 的加载心跳均不能作为存档身份。

## 倒车实验接口

`ControllerCommandClient.reverse_train(vehicle_id, operation_id=...)` 经 Loader
共享内存的现有 `STOP_VEHICLE` 命令发送 `reverse_after_stop=true`。
Lua 业务模块 `operations/vehicle_reverse.lua` 先停车，确认速度接近零且
`userStopped=true` 后调用游戏 `api.cmd.make.reverseVehicle`；不手改坐标。
`get_train_direction` 返回 `WAITING_STOP / REVERSING / REVERSED / FAILED`。
游戏命令工厂可能是可调用 table，不能仅用 `type(...) == "function"` 判断。

成功换向后仍保持停车，120 秒停车看门狗仍然有效。恢复行走必须明确解除停车；
该动作可能重算路径、改变下一站索引，使旧的原生移动请求因路径变化退出。
换向成功不代表退路畅通，也不保证原线路已经恢复。实测能换向并退行，
退行方向存在其他列车时，游戏的原生占用保护仍会阻止继续移动。

实车已验证恢复流程：换向后提交有限长度的退行进路，到点确认整列车清出原道岔，
再换向并恢复正常运行。退行序列应收短到目标、前半列车余量及末端保护边；
逆向缺少顺向信号时，附带过长的后续路径会导致游戏尝试预留整个长区段，
使跟随退行的列车无法启动。不能把 `MOVING` 状态当作实际正在行走的证据，
还需确认实时速度和剩余距离持续变化。

## MCP 接口

| 工具 | 用途 |
| --- | --- |
| `get_train_movement_context` | 读取新鲜的车长、速度、停车状态、下一站及有向原生路径窗口 |
| `reverse_train` | 停车后换向；查询确认后仍保持手动停车 |
| `get_train_direction` | 查询该列车最近一次换向及 operation_id |
| `move_train_distance` | 沿当前朝向、当前路径定距移动，到点扣停 |
| `move_train_route` | 指定有向原生子边和目标位置，到点扣停 |
| `get_train_movement` | 查询受理、移动、扣停、恢复等实际执行状态和当前速度 |
| `release_train_movement` | 请求解除指定移动接管，须继续查询到 RELEASED |

列车通过 `display_name` 选择，重名时加 `vehicle_id`。
四个写工具均要求 `command_id`、`reason`，默认 `dry_run=true`。
实际执行时设置 `dry_run=false`，并提供精确的 `工具名大写:command_id` 确认串。
例如 `reverse_train` 的确认串为 `REVERSE_TRAIN:reverse-001`。
`release_train_movement` 用返回的 `movement_id` 定位请求，无须重新选择列车。

推荐顺序：先保存上下文，换向并查询到 REVERSED；通过现有 `resume_train`
解除手动停车，重新读取上下文，再提交定距或指定进路移动。确认到点 HELD、
整列车清出目标道岔后，才进行下一次换向。换向引起旧接管退出属于预期行为。

移动请求的 `movement_id` 在 MCP JSON 中一律为十进制字符串，避免64位整数精度丢失。
请求绑定当前存档及 Controller 实例；跨存档或 DLL 重载后不能继续使用旧句柄。
写命令日志保存在项目/Mod 的 `var/train-movement-commands`，先记意图再发送。
重复命令只返回历史回执，不重新换向；OUTCOME_UNKNOWN 必须查询核实，不能改新编号盲目重发。
工具调用参数、原因和句柄同时进入现有按启动时间命名的 MCP 审计日志。

MCP 的 `move_train_route` 默认 `require_resumable_route=false`，适用于需要自行安排回程的调车。
显式 true 才要求 DLL 具备 `movement_return_check`。这与底层 Python SDK 的默认值不同。
