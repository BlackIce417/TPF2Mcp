# 当前数据与调度能力：代码复核

复核日期：2026-09-25。依据为当前工作区源码（包含未提交修改）、现存 2026-09-18/19 实机记录和本次离线复现。本次未启动游戏、未注入 DLL、未改变控制配置，不能把源码版本视为当前已加载或已验收的游戏版本。

本文是当前能力入口。Phase 验收、早期探针和历史 JSON 保留其原始结果；它们不代表今天所有接口的能力，也不能用新结论改写历史证据。模块化设计中的目标协议不等于现有公共接口。

> 2026-10-12 整理补充：最新模块入口及验证结果见 [阶段成果与后续任务](PROJECT_PROGRESS.md)。原生速度规则已增加路径索引起止范围，但路径代次、方向和边内精确范围仍未贯通；下文“路径 occurrence 未完成”指完整身份与执行语义尚未完成。信号区间控制尚未接入间距算法。

## 结论

具备开发本地调度算法的数据和具体动作入口；尚不具备让外部算法可靠接管全部调度的完整闭环。单车限速、乘客改派、指定站台和进路代价现在均可作为带期限的外部目标提交、撤销并编译为原生租约，但本次新代码只完成离线测试和原生构建，未重新装载游戏实机验收。货物按类型改派、逐命令效果回执及联合站场优化仍有实质缺口。新区域 worker 仅影子协调，不执行游戏控制。

| 用户需求 | 当前代码/数据 | 接入判断 |
|---|---|---|
| 详细铁路与站台拓扑 | 三维节点、轨道曲线、限速、终端/站台边、长度来源、线路停站与备选站台 | 可作为基础数据；全网道路能力未在本次复核范围 |
| 候车/车载人数、货物类型和数量 | line_demand 按实体与 LINE_STOP_OD 分类；车站接口按有向起点聚合 | 可读并带质量信息；只覆盖已分配线路且不是最终目的地 |
| 单车指定区间限速 | 公共公里标命令、边集合配置、原生速度 Hook | 到期/撤销已贯通；精确边内范围、反向及跟驰制动仍需补齐 |
| 指定 L1→L2、类型和数量改派 | REASSIGN_OD 可提交有向乘客规则；实体类型进入原生规则 | 乘客目标可编译；货物按 cargo_id 仍主动拒绝，净迁移未逐命令验证 |
| 指定站台/进站路线 | ASSIGN_PLATFORM / SET_PATH_COST 可提交目标租约 | 可下发合法目标；尚无联合预约、实际路径关联验证和新版实机验收 |
| 车辆分配/编组调整 | 既有 Task 操作与运力策略，含购车、分配、出售、编组替换 | 可复用，须保留车型、站台和出库可达性检查 |

## 1. 数据的真实入口与口径

- Lua [line_demand.lua](../tpf2_mod/res/scripts/tpf2_mcp/collectors/line_demand.lua) 调用 getSimPersonsForLine / getSimCargosForLine，再读取 SIM_ENTITY_AT_VEHICLE / SIM_ENTITY_AT_TERMINAL。数量是被枚举实体的计数；不能自动解释成吨数。
- 通过 MCP get_line_demand / get_line_dispatch_state.demand 读取 waiting、onboard、vehicles、by_cargo、by_journey、journey_unknown、truncated 和 errors。Lua 实际每类上限限制为 100–50,000，默认 20,000；新车站接口按同一范围声明，旧线路/车辆入口仍接受 1–100,000，但 Lua 会自行收敛到该范围。
- LINE_STOP_OD 是当前线路的 lineStop0→lineStop1；不是全程换乘链、旅客最终建筑、货物最终消费者或尚未分配到线路的总需求。
- get_vehicle_dispatch_state 用上述 vehicles 计数拼接实际载荷；旧 SnapshotIndex.vehicle_operating_state 的 load_total 仍为空。两条读取路径不可混为一谈。
- get_station_dispatch_state.waiting 逐条采集接入线路，以有向 lineStop0 映射本站；循环线路在同站的多个停站序号会合并，同一线路不会重复计数。quality 明示截断、桥接失败和无法归属的候车量。它只覆盖已归属线路且已取得 OD 的实体；generic station_operating_state.waiting_total 仍保持空值。
- get_vehicle_dispatch_state 现在将 errors / UNAVAILABLE 传播为 availability.load=false，将 truncated 传播为 complete_load=false；不完整样本不计算 occupancy_ratio。原始计数在仅截断时仍是下界。
- SnapshotIndex 的 lines_by_station 已按“线路—车站”去重，循环线路重复停靠仍保留在线路 stops 中，但不会把车站接入线路数和需求聚合翻倍。
- 路网/站台数据同时含 ENGINE_OBSERVED 和 DERIVED 来源。现存铁路导出有 19,878 个节点、20,401 条边、86 个站条目和 46 条线路；这是一个保存的数据集，不是固定规模或完整覆盖所有运输方式的保证。
- 最新历史记录的车头快报墙钟平均约 0.416 秒、整列车体约 2.4 秒；0.2 秒是配置目标，不能宣称已达到。方向查询成功不等于读到实时信号灯色或获得可执行进路。

相关实现：[server.py](../mcp_server/src/tpf2_mcp/server.py)、[dispatch.py](../mcp_server/src/tpf2_mcp/dispatch.py)、[snapshot.py](../mcp_server/src/tpf2_mcp/snapshot.py)、[operational_telemetry.lua](../tpf2_mod/res/scripts/tpf2_mcp/collectors/operational_telemetry.lua)。

## 2. 单车区间限速

调用链：POST /api/dispatch-platform/commands → DispatchControlPlatform.submit → speed_rules → EngineeringControlSystem._speed_decisions → NativeLeaseWriter → speed_hook_c。也有 POST /api/control-system/config 的 edge_speed_rules；它是配置通道，不是完整的逐条指令队列。

已经具备单车/多车、边匹配、非零速度上限、原生租约到期和多限制取最小值。历史车辆 590896 的 1.2 km 区段实验有效，但旧样本中名义 60 km/h 实测约 61.2–61.5 km/h；当前源码增加 0.5 m/s 裕度，不等于新版本已完成速度精度验收。

公共 SET_SPEED_LIMIT 现在保存 expires_at 和 priority；控制周期会清除过期规则、停止续租，CANCEL_COMMAND 可按 command_id 删除待编译规则。显式规则不依赖自动 speed 策略开关。当前仍只接受 FORWARD，因为原生租约没有方向字段。

**仍存在的缺口：**

1. map_chainage_zone 用节点三维直线距离累计里程，不是曲线弧长。静态 route_edge_ids 来源于无向最短路、跨停站去重，且不自动加入末站回首站段，不是严格连续的车辆有向运行路径。
2. 映射虽生成 from_param/to_param，但 _speed_decisions 只传 edge_ids；原生 SpeedRule 不含方向和边内区间。请求长边的一小段会退化为整边/预览窗口匹配，反向命令当前被拒绝而非假装支持。
3. 预制动按前方约 24 个路径元素、固定 1.2 m/s² 和墙钟步长实施，并直接改写 MOVE_PATH 速度字段；不是基于真实车距、曲线距离、车辆制动模型及游戏倍速的跟驰控制。
4. 现已增加 SHADOW 间距策略：主控制帧合并实际 MOVE_PATH、1 Hz 完整车体、路径窗口和 brakeDecel；`train_spacing.py` 按三维曲线及路径 occurrence 计算前车车尾—后车车头净间距，并生成带 leader_id、间距、制动距离和路径索引范围的 `spacing_advisory`。重复边、反向列车、路径/车体/制动缺失和整列帧过期均有确定性拒绝路径。
5. 原生零速已被控制器拒绝；保护停车走官方 STOP_VEHICLE，但公共 PROTECTIVE_STOP 的 edge_ids 只作道岔冲突筛选，并不等待列车进入该区段才停车。最终实机停车—看门狗放行验收仍待完成。

间距算法已经可以在 SHADOW 中采集建议速度并做回放。`spacing_policy.armed_execution` 默认关闭，ARMED 还要求 `braking_verified`；原生方向/路径 occurrence/边内范围、保守制动下界和端到端延迟尚未实机标定。不能把当前限速器当作已验收的自动闭塞或防追尾控制器。

实现：[dispatch_platform.py](../mcp_server/src/tpf2_mcp/dispatch_platform.py)、[speed_zones.py](../mcp_server/src/tpf2_mcp/speed_zones.py)、[train_spacing.py](../mcp_server/src/tpf2_mcp/train_spacing.py)、[control_system.py](../mcp_server/src/tpf2_mcp/control_system.py)、[tpf2_control.c](../native/tpf2_control/tpf2_control.c)。

## 3. 客货强制改派

原生 cargo_assign_hook / person_assign_hook 在游戏调用分配函数时，把匹配源线路/站序的调用改为目标线路/站序。它不是收到命令后立即枚举并搬移现有候车队列的批处理器，也不承诺把在车实体搬到另一辆车。

历史证据：一名候车乘客从 483732:2→3 改为 25971:4→5，对应候车量 9→8、4→5。非零货物改派没有找到同等级实机样本。

**代码确认的缺口：**

1. REASSIGN_OD 已把有向源/目标线路、站序、数量和 PERSON 实体类型保存为带期限规则；旧 BALANCE_OD 仍只是自动策略开关。自动并行线路诊断也已保留 A→B 与 B→A 的方向，方向不一致时拒绝编译。
2. C 的 RoutingRule 已读取 entity_kind，客货 Hook 不再共用同一条规则；cargo_id 仍未贯通，因此公共 CARGO 请求主动失败，不能误称为按货物类型执行。
3. 剩余运力使用线路总有效容量减去该 OD 的在车数，班次时间用 headway_seconds；未按具体即将到站车辆、各区间和其他 OD 的占用做共同容量账本。不同 OD 可重复使用同一容量。
4. max_assignments 是匹配分配调用的计数上限，不是已核验的净迁移数量；未按 entity_id 去重。每组诊断只挑一个目标，亦非完整多目标分配执行。
5. person_assign_hook 在原函数返回后无条件累加 successes，未验证返回语义；控制器用全局计数增量记录 OD_REASSIGNMENT_NATIVE_VERIFIED。不能将此事件名称等同于特定命令、对象与数量已验证。
6. 需要明确触发重新分配的方式，以及后续游戏重算是否保持改派、实体数量守恒和完整行程有效性。

应先修方向、实体类型/货物类型过滤、逐对象回执和共享区间容量，再验收有界客流批量改派及独立货物案例。

实现：[timetable_planner.py](../mcp_server/src/tpf2_mcp/timetable_planner.py)、[capacity_allocator.py](../mcp_server/src/tpf2_mcp/capacity_allocator.py)、[control_system.py](../mcp_server/src/tpf2_mcp/control_system.py)、[tpf2_control.c](../native/tpf2_control/tpf2_control.c)。

## 4. 站台与进站进路

底层 station_hook_c 在游戏寻路调用中覆盖 assignedOnly / StationTerminal，有指定站台实机记录。path_cost_hook 在该调用的线程上下文中对匹配列车/边增加原生寻路代价，保留游戏候选路径生成；不是任意写入外部轨道路径。

ASSIGN_PLATFORM 和 SET_PATH_COST 现在保存外部目标并由下一控制周期编译显式租约；到期和 CANCEL_COMMAND 会停止续租。站台命令会核验车辆、线路/停站、接近且未锁定、目标属于停站方案，并且只有 fits_longest_assigned_train 明确为 true 才接受。原生站台覆盖失败会消费该次请求并让游戏下一次调用回到默认参数，避免坏目标无休止重试。

**仍存在的策略边界：**

- SET_PLATFORM_POLICY / SET_PATH_POLICY 仍只开启内置策略；具体目标使用 ASSIGN_PLATFORM / SET_PATH_COST。
- _station_decisions 在接近车站且未锁定时，按当前终端占用计数最小、再优先默认站台选取。没有完整的时空站台/咽喉联合预约。
- _path_decisions 对其他车辆占用边统一加固定代价（默认 300），不是预测清空时间、进路冲突和下游容纳空间的优化器。
- 原生代价命中统计不证明实际改变路径；控制周期没有逐命令比较目标路径与实际路径的验证分支。
- 锁定后任意改道、指定完整进路、长期吞吐改善均未完成本次可确认的验收。

可实现方向：外部算法联合选择合法站台/进路，锁定前预约并执行，比较实际走行路径与总延误；不能只以“空闲站台被选中”判定拥堵解决。

## 5. 公共接口、执行与区域模块

当前 HTTP 门面在 [web_app.py](../mcp_server/src/tpf2_mcp/web_app.py)。APPLY_TIMETABLE 同样只是启用内部运行图策略，并非应用请求里携带的任意计划。ACCEPTED / POLICY_ACCEPTED / EXECUTED 是现有返回标签，不等于游戏效果已验证。具体动作协议 Schema 已加入 protocol/dispatch/control-command.schema.json 和 control-result.schema.json。

公共门面对 command_id 做持久日志去重：同 ID 同内容返回 DUPLICATE，内容变化则拒绝；priority 和 expires_at 进入显式租约，CANCEL_COMMAND 可撤销四类待编译规则。尚未建立跨命令冲突仲裁、所有者隔离和 topology_id 作用域；省略 expires_at 时会生成新时间，因此需要重试的调用方应固定完整命令内容。能力 AVAILABLE 主要依据后端健康，不代表每项业务已验收。

官方 Lua 写开关与原生控制不是同一门禁：旧控制循环发布 native 租约检查 ARMED、读数据健康和 native_loaded，Lua 写开关用于官方命令。不能把 allow_write_operations=false 描述为所有原生通道的独立总禁用器；全系统还需 DISABLED 和原生租约清空。

[run-regional-dispatch.py](../tools/run-regional-dispatch.py) 与 [handover.py](../mcp_server/src/tpf2_mcp/dispatch_runtime/handover.py) 已有独立采集/快照/SQLite、影子预约与交接账本，但明确 game_write=false。新区域登记、接车或车尾出清记录不是游戏控制回执。

[modular-dispatch-design.md](modular-dispatch-design.md) 中 ASSIGN_PLATFORM、SET_PATH_COST、REASSIGN_OD、CANCEL_COMMAND 已进入当前门面；它们只表示目标被接受并等待控制周期编译，实际效果仍需查看控制事件和游戏后验状态。

旧 configure-capacity-routing.py / configure-station-assignment.py 是直接写单节 INI 的实验工具，缺少统一执行语义，可能与多租约控制器覆盖冲突，不能作为外部算法稳定接口。

## 6. 本次验证与后续顺序

本轮使用项目 Conda 环境运行全仓 351 项 Python 测试，341 项通过、10 项因需显式实机/环境条件而跳过；新增定向测试覆盖具体动作、到期/撤销、ARMED→SHADOW 立即清租约、OD 方向、未知站台长度、车站需求聚合、客货分类失败、采集截断传播。原生 DLL 与注入器已成功构建。`git diff --check` 无补丁错误，只有既有 CRLF 提示。

本轮没有启动游戏、替换已加载 DLL 或启用控制，因此新代码不能算新版实机验收。旧的五类离线反例中，到期丢失、反向 OD、未知站台长度、策略命令无法携带具体目标已修复；边内精确范围和 cargo_id 过滤仍未修复。

建议实现顺序：

1. 统一观测质量、同会话路网和实际有向路径；补车站候运聚合及方向化 OD。
2. 定义外部算法的具体动作契约，贯通目标、期限、租约所有权、幂等和撤销；抽离唯一执行者。
3. 先完成单车非零限速与站内扣停的闭环，再开发跟驰与联合站场优化。
4. 修复 OD 方向、货物类型过滤、容量账本、触发及逐实体回执后，再启用批量分流。
5. 对实际路径、净迁移量、延误和吞吐做限定实机验收；原生构建须按版本签名重新验证。

下一步应先把逐命令回执、货物 cargo_id 过滤和实际有向路径补齐，再开展受控实机验收。
