# 原生列车遥测

高频车辆数据由 Controller 在现有 `TransportVehicleSystem::Update2` Hook 的原函数返回后读取，采集时始终持有 DetourManager 的调用保护。只读游戏内存，不修改车辆和路径，不添加车厢级 Hook，不将引擎指针交给后台线程。

## 采集与发布

- 位置、包围盒、速度、加速度、当前路径、方向、线路、停站状态和车厢归属直接读取当前 Engine 快照。
- 游戏时间直接读取 `GAME_TIME`，轨道/车型最大速度分别保留原有字段含义。
- 载荷读取 TransportVehicleSystem 的缓存和 SimEntityAtVehicleSystem 的计数、乘客实体集合，避免 Lua `getInfo` 的深拷贝和全局乘客扫描。
- `SIM_PERSON_AT_VEHICLE` 提供车厢索引，列车与车厢旅客数需要一致；货物采用游戏模型相同的 `clamp(total-offset, 0, capacity)` 分配公式。
- 多客舱车厢尚未验证座位到客舱的映射。实车还发现部分旅客缺少 `SIM_PERSON_AT_VEHICLE`，这时车厢人数沿用 v1 的未验证表示（0 且清除相应完整性标志），不阻塞其他数据；整列人数来自引擎载荷计数。
- Lua 只在会话开始、编组变化或出现未缓存货物资源时提供车型、重量和轨道限速资源种子。装载配置及容量变化由 DLL 直接重建载荷行，不触发 Lua 整批重采；名称仍走低频 `train-identities.json`。城市、产业、路网等资产仍按原来的按需策略采集。

原生路径按每次引擎更新采样，正常游戏速度下目标 5Hz；游戏暂停或更新速度下降时不承诺墙钟 5Hz。位置通道最多 2048 个车辆记录，列车二进制协议保持现有容量约定。

Controller 通过 Loader 的普通 C 导出调用发布函数；Loader 复用现有共享内存键值总线、双缓冲与通知事件。Python/MCP 的业务接口不变。

## 公开协议保持 v1

| 通道 | 内容 |
| --- | --- |
| `train-wrappers-v1.bin` | Header 72、TrainWrapper 220、VehiclePartWrapper 224、PassengerLoadEntry 12、FreightLoadEntry 24 字节 |
| `operational-telemetry-vehicle_positions.json` | 原有车辆位置、线路、状态、到站终端、方向和运动字段 |
| `operational-telemetry-train_footprints.json` | 原有包络和前后各 96 个路径子边窗口，保留 false 方向及重复边 |
| `native-telemetry-performance.json` | 当前存档会话、采样序号、耗时及失败状态 |

`source_status`、`probe_kind`、`session_id`、`simulation_clock` 等消费端依赖字段保留。静态种子的资源尾部只存在于私有 `native-train-seed.bin`，不会混入公开二进制帧。

## 生命周期

Lua 仅在模拟更新中传入会话和世界实体 ID。Loader 为每次换档分配 epoch，拒绝旧 epoch 的发布，并在新种子到达前禁止复用旧种子。GUI 加载回调不接管这个会话。

新 Controller 与 Loader 握手后，Lua 停止三个高频通道的采集，仅按请求生成静态种子。旧 Loader 尚未更新时仍维持现有 Lua 路径。编组不一致时请求新种子，不发布部分匹配的帧；原生读取失败不会把旧帧重新盖上新时间。

原生布局限定于已逆向的游戏版本（PE timestamp `0x675ABCC6`、SizeOfImage `0x46CE000`），沿用现有 Hook 安装的版本与函数签名检查。

Loader 具有进程生命周期，因此首次升级需要退出游戏后一起替换 Loader、Controller 和 Lua 文件。只重载存档无法替换已加载的 Loader。

## 验证

`tests/build-native-telemetry.cmd` 在独立进程内构造引擎快照与 Loader 总线桩，验证原生采样、货物分配、乘客归属、换档与旧写入拒绝。`test_native_telemetry_compat.py` 用现有生产 Python 解码器读取 C++ 生成的帧和 JSON。隔离测试不会创建真实游戏总线的映射。

2026-11-12 已安装并实车观察 20 秒：127 列列车、2209 节车体、234 个车辆位置，127 列包络完整；原生采集和发布耗时中位 31.3ms，约 4.94 次/墙钟秒，Lua 高频车体采集和元数据重采均为零次。54 项 Python/Lua 回归及 3 组原生测试通过，真实 HTTP MCP 列车快照可读取新帧。

当前存档有 9 列列车的旅客车厢归属未验证；整列人数可用。停放/入库等其他场景覆盖仍需后续专项验证。该存档的车站内部节点重叠问题已修复，全网拓扑与列车快照接口均已验证通过；这不代表物理连接图已经验证了所有合法进路。
