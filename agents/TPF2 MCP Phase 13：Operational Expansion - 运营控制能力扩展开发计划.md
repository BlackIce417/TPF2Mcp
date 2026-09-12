# TPF2 MCP Phase 13：Operational Expansion

## 0. Phase 13 定位

当前已经完成：

```text
Phase 9
Network Intelligence

Phase 10
Decision Support

Phase 11
Controlled Operations

Phase 12
Closed-Loop Task Orchestration
```

目前真实 POSTCONDITION_VERIFIED write capability：

```text
RENAME_LINE
```

这已经足够证明：

```text
Observe
→ Plan
→ Execute
→ Fresh Snapshot
→ Verify
→ Re-plan
```

整条架构成立。

因此 Phase 13 不再继续重点扩展通用 orchestration framework。

Phase 13 的核心目标是：

# 扩展真正有游戏意义的运营操作能力

目标能力：

```text
车辆购买
车辆出售

车辆分配至线路
车辆移出线路

线路停站调整

线路运营参数调整

线路创建/删除的 API 基础

站点/Terminal 查询增强
```

最终让 AI 能够开始：

```text
经营运输公司
```

而不仅仅：

```text
修改实体名字
```

---

# 1. Phase 13 总体路线

必须采用：

```text
API Discovery
↓
Minimal Live Probe
↓
Capability Registry
↓
OperationController
↓
Postcondition Verification
↓
Task Goal
↓
Closed-loop Live Test
```

不要：

```text
一次找到一堆 API
→ 全部直接注册 MCP tool
```

每一种操作必须独立完成 Live Verification。

---

# 2. Phase 13 优先级

按以下顺序推进：

## P0

```text
车辆信息增强
车辆购买
车辆出售
车辆分配线路
```

## P1

```text
线路停站 / stop sequence 管理
车辆从线路移出
车辆替换 / replacement
```

## P2

```text
线路运营参数
线路创建
线路删除
```

## P3

```text
站点相关操作
```

真正的道路/铁路建设、terrain geometry 暂不做。

---

# 3. 首先补齐 Vehicle Snapshot

当前如果 snapshot 中 vehicle 字段不足以支持写操作，先扩展。

Vehicle 至少必须稳定提供：

```text
vehicle_id

name

vehicle_type

transport_mode

line_id

depot_id

state

capacity

cargo_types

age

purchase_time / age proxy

condition

maintenance

replacement state
```

能确认多少就记录多少。

无法确认：

```text
UNAVAILABLE
```

禁止推断。

---

# 4. 增加 Vehicle Identity Stability Test

写操作依赖：

```text
vehicle_id
```

必须验证：

```text
同一辆车跨多个 snapshot
entity_id 是否稳定
```

Live evidence：

```text
vehicle-id-stability.json
```

至少连续采集：

```text
5 个 snapshot
```

确认：

```text
same physical vehicle
→ same entity id
```

---

# 5. Vehicle Capability Discovery

新增：

```text
collectors/vehicle_write_probe.lua
```

重点搜索 shipped scripts / API：

```text
api.cmd.make.*
api.cmd.sendCommand

game.interface.*

vehicle commands
depot commands
line commands
```

必须重点寻找这些语义：

```text
buy vehicle
sell vehicle

add vehicle
remove vehicle

set vehicle line

dispatch vehicle

send vehicle to depot

replace vehicle
```

不要只靠函数名猜含义。

---

# 6. API Discovery Artifact

生成：

```text
diagnostics/phase13-api-discovery/
    vehicle-write-api.json
    line-write-api.json
    station-write-api.json
```

格式：

```json
{
  "candidate": "...",
  "source": "...",
  "signature": "...",
  "semantic_guess": "...",
  "verification": "DISCOVERED_NOT_VERIFIED"
}
```

---

# 7. Capability Registry 扩展

目标增加：

```text
BUY_VEHICLE

SELL_VEHICLE

ASSIGN_VEHICLE_TO_LINE

REMOVE_VEHICLE_FROM_LINE

SEND_VEHICLE_TO_DEPOT

SET_LINE_STOPS

CREATE_LINE

DELETE_LINE
```

初始全部：

```text
DISCOVERED_NOT_VERIFIED
```

只有 Live 验证后才变：

```text
POSTCONDITION_VERIFIED
```

---

# 8. 第一核心能力：BUY_VEHICLE

优先确认购买车辆的真实 command API。

目标 MCP operation：

```text
BUY_VEHICLE
```

输入不要直接暴露复杂内部结构。

建议：

```json
{
  "depot_id": 1234,
  "vehicle_model_id": 5678,
  "count": 1
}
```

如果 TPF2 API 实际需要其他参数，则按真实 API 调整。

---

# 9. Vehicle Catalog

AI 买车之前必须知道：

```text
可以买什么
```

新增：

```text
get_vehicle_catalog
```

至少返回：

```text
model_id
name
transport_mode
capacity
cargo compatibility
purchase_price
running cost
availability
```

只返回实际能够读取到的字段。

---

# 10. Vehicle Catalog 必须区分

```text
ENGINE_VERIFIED
DERIVED
UNAVAILABLE
```

尤其：

```text
purchase_price
running_cost
```

不能自己硬编码网上的数据。

---

# 11. BUY_VEHICLE Proposal

例：

```json
{
  "operation_type": "BUY_VEHICLE",

  "target": {
    "depot_id": 123
  },

  "parameters": {
    "vehicle_model_id": 456,
    "count": 1
  }
}
```

preconditions：

```text
depot exists

model exists

model compatible with depot / mode

count valid

write capability verified

snapshot current
```

---

# 12. BUY_VEHICLE Postcondition

不能只验证：

```text
company vehicle_count + 1
```

因为游戏可能同时发生其他变化。

最好识别：

```text
new vehicle entity id
```

返回：

```json
{
  "new_vehicle_ids": [
    88001
  ]
}
```

验证依据：

```text
before vehicle IDs
vs
after vehicle IDs
```

---

# 13. 多车购买

Phase 13 首次实现不要真正一次 command 买 N 辆。

即使 MCP 输入：

```text
count = 3
```

也建议 Task 层拆为：

```text
BUY
verify
BUY
verify
BUY
verify
```

保持：

```text
one mutation per closed-loop step
```

---

# 14. SELL_VEHICLE

第二核心能力：

```text
SELL_VEHICLE
```

输入：

```json
{
  "vehicle_id": 88001
}
```

---

# 15. SELL_VEHICLE 必须标记 destructive

Capability：

```json
{
  "operation_type": "SELL_VEHICLE",
  "destructive": true,
  "supports_rollback": false
}
```

因此：

```text
AUTO_SAFE
```

绝对不能执行。

---

# 16. SELL_VEHICLE Preconditions

至少：

```text
vehicle exists

ownership verified

vehicle state compatible with sale

snapshot current

entity-state precondition matches
```

如果车辆在运行线路中不允许出售：

返回实际错误。

不要自动：

```text
remove line
→ depot
→ sell
```

除非 Task 明确规划这些步骤。

---

# 17. SELL_VEHICLE Postcondition

验证：

```text
vehicle_id no longer exists
```

同时记录：

```text
company vehicle count
balance before/after
```

但资金变化：

```text
只作为 observed delta
```

不要直接断言：

```text
sell price = balance delta
```

因为同时可能存在其他财务事件。

---

# 18. 第三核心能力：ASSIGN_VEHICLE_TO_LINE

这是 Phase 13 最重要的运营能力。

目标：

```text
ASSIGN_VEHICLE_TO_LINE
```

输入：

```json
{
  "vehicle_id": 88001,
  "line_id": 11833
}
```

---

# 19. Assignment Preconditions

验证：

```text
vehicle exists

line exists

transport mode compatible

vehicle not already on target line

ownership correct

target line usable
```

如果车辆需要先：

```text
leave depot
```

由实际 TPF2 API 决定。

不要伪造流程。

---

# 20. Assignment Verification

Fresh Snapshot：

```text
vehicle.line_id == target_line_id
```

如果 line snapshot 本身也有：

```text
vehicle_ids
```

则双向 cross-check：

```text
vehicle.line_id == line.id

AND

vehicle.id in line.vehicle_ids
```

如果两者不一致：

```text
POSTCONDITION_CONFLICT
```

---

# 21. REMOVE_VEHICLE_FROM_LINE

增加：

```text
REMOVE_VEHICLE_FROM_LINE
```

目标状态明确。

例如：

```text
line_id = null
```

或者：

```text
vehicle goes to depot
```

必须根据 TPF2 实际模型定义。

不能自己决定语义。

---

# 22. SEND_VEHICLE_TO_DEPOT

如果 API 独立存在，单独建 capability：

```text
SEND_VEHICLE_TO_DEPOT
```

不要混到：

```text
REMOVE_VEHICLE_FROM_LINE
```

里面。

---

# 23. Vehicle Assignment Task

新增 Goal：

```text
ASSIGN_VEHICLE_TO_LINE_GOAL
```

satisfaction：

```text
vehicle.line_id == desired_line_id
```

完整闭环：

```text
Goal
→ observe vehicle
→ observe line
→ propose
→ execute
→ fresh snapshot
→ verify
→ COMPLETED
```

---

# 24. BUY_AND_ASSIGN Goal

在 BUY 和 ASSIGN 都验证后增加：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

这是 Phase 13 第一个真正有意义的 composite operational task。

流程：

```text
Select model
↓
BUY_VEHICLE
↓
Fresh Snapshot
↓
discover new vehicle ID
↓
re-plan
↓
ASSIGN_VEHICLE_TO_LINE
↓
Fresh Snapshot
↓
verify
↓
COMPLETED
```

---

# 25. 禁止预先猜 new vehicle ID

非常重要。

错误：

```text
buy
→ assume vehicle id
→ queue assignment
```

正确：

```text
buy
→ snapshot
→ detect new entity id
→ next step
```

这正是 Phase 12 orchestration 的用途。

---

# 26. Buy Goal

新增：

```text
BUY_VEHICLE_GOAL
```

satisfaction 不宜简单：

```text
vehicle count >= old + 1
```

Task 创建时保存：

```text
baseline vehicle ID set
```

完成条件：

```text
expected number of newly observed compatible vehicle entities
```

---

# 27. Sell Goal

新增：

```text
SELL_VEHICLE_GOAL
```

satisfaction：

```text
vehicle_id absent
```

destructive：

```text
MANUAL
```

---

# 28. Fleet Operational Summary

新增：

```text
get_fleet_profile
```

用于 AI 决策。

返回：

```text
total vehicles

vehicles by mode

vehicles by line

unassigned vehicles

vehicles in depot

capacity totals

vehicle age distribution

condition distribution
```

只能基于真实 snapshot。

---

# 29. Line Fleet Profile

新增：

```text
get_line_fleet_profile
```

输入：

```text
line_id
```

返回：

```text
vehicle_ids

vehicle count

model distribution

total capacity

average condition

unassigned/invalid state

headway/frequency if verified
```

---

# 30. 为 Phase 13 AI 买车建立最小决策支持

新增：

```text
compare_vehicle_models
```

只能比较可证实指标：

```text
capacity
purchase price
running cost
speed
cargo compatibility
availability
```

不要现在做：

```text
best ROI
expected profit
```

除非数据完整。

---

# 31. 推荐结果

例如：

```json
{
  "candidate_models": [],
  "comparison": {
    "capacity": {},
    "purchase_price": {}
  },
  "recommendation_status": "HEURISTIC"
}
```

AI 最终可据此选择车型。

---

# 32. 第四核心：线路 Stop Sequence

开始探测：

```text
SET_LINE_STOPS
```

或者 TPF2 实际对应 API。

目标：

```text
修改既有线路的 stop sequence
```

这是最终 AI 控制必须具备的能力。

---

# 33. 首先增强 Line Snapshot

Line 必须清楚表示：

```text
line_id

transport_mode

ordered stops
```

Stop 必须至少：

```text
station_id

terminal id if applicable

position/order

direction / edge if available
```

---

# 34. 不要只保存 station set

必须保存：

```text
ordered sequence
```

例如：

```text
A → B → C → D
```

而不是：

```text
{A,B,C,D}
```

因为修改线路依赖顺序。

---

# 35. Duplicate Stops

TPF2 线路可能存在：

```text
A → B → C → B → A
```

因此：

```text
station IDs 不能用 set 去重
```

必须保存原始 ordered sequence。

---

# 36. Stop Descriptor

建议：

```json
{
  "sequence": 0,

  "station_id": 123,

  "terminal_id": 4,

  "source_status": "ENGINE_VERIFIED"
}
```

---

# 37. SET_LINE_STOPS Operation

目标输入：

```json
{
  "line_id": 11833,

  "stops": [
    {},
    {},
    {}
  ]
}
```

但 MCP 应尽量让用户使用：

```text
station IDs
```

内部再转换真实 command structure。

---

# 38. Stop Validation

必须检查：

```text
station exists

transport mode compatible

minimum stop count

terminal selection valid

duplicate rules valid

line exists

sequence valid
```

---

# 39. SET_LINE_STOPS 风险级别

至少：

```text
destructive = false
```

但：

```text
operationally_disruptive = true
```

建议增加 capability 字段：

```text
risk_class
```

---

# 40. Operation Risk Class

Phase 13 正式引入：

```text
LOW
MEDIUM
HIGH
```

例：

```text
RENAME_LINE = LOW

ASSIGN_VEHICLE_TO_LINE = MEDIUM

SET_LINE_STOPS = MEDIUM

SELL_VEHICLE = HIGH

DELETE_LINE = HIGH
```

---

# 41. AUTO_SAFE 更新

AUTO_SAFE 只允许：

```text
risk_class == LOW
```

不再仅依赖：

```text
destructive == false
```

因为：

```text
SET_LINE_STOPS
```

虽然不是 destructive，但可能明显影响运营。

---

# 42. Modify Stops Goal

新增：

```text
SET_LINE_STOPS_GOAL
```

satisfaction：

```text
observed ordered stop sequence
==
desired ordered stop sequence
```

必须严格比较：

```text
order
terminal
duplicates
```

---

# 43. Stop Change Simulation

Phase 10 what-if 扩展支持：

```text
simulate_line_stop_change
```

可以重新计算：

```text
network topology
reachability
component structure
transfer relationships
```

在真正 SET_LINE_STOPS 之前作为 dry-run。

---

# 44. 强制 pre-execution simulation

对于：

```text
SET_LINE_STOPS
```

要求：

```text
simulation available
```

Proposal 中返回：

```text
topology delta
```

例如：

```text
component count
affected stations
transfer changes
```

---

# 45. 第五核心：Line Operational Parameters

Runtime Probe：

```text
frequency
rate
vehicle spacing
waiting time
stop duration
departure interval
```

必须先搞清 TPF2 的真实控制模型。

不要看到 UI 上有“频率”就假定存在：

```text
setFrequency()
```

---

# 46. 参数分类

如果 TPF2 线路运行频率实际上由：

```text
vehicle count
+
route length
+
vehicle behavior
```

自然产生，那么不要构造：

```text
SET_LINE_FREQUENCY
```

伪 operation。

应该让 AI：

```text
通过车辆数量和调度参数间接调整
```

---

# 47. 调度策略能力

实际 API 允许什么就开放什么。

候选：

```text
SET_LINE_WAITING_POLICY

SET_FULL_LOAD_POLICY

SET_MIN_LOAD

SET_MAX_WAIT

SET_STOP_BEHAVIOR
```

具体名称以真实 API 为准。

---

# 48. 不允许 API Semantic Guess

如果发现：

```text
setLineParam(id, 2, 5)
```

但不知道 2/5 含义：

```text
DISCOVERED_NOT_VERIFIED
```

不能开放。

---

# 49. Operation Argument Provenance

每一个 parameter 都要记录来源：

```json
{
  "name": "min_load",
  "meaning": "...",
  "source": "...",
  "verified": true
}
```

避免后面出现：

```text
API 找到了
但参数语义错了
```

---

# 50. Line Creation Discovery

Phase 13 要开始探测：

```text
CREATE_LINE
```

这是最终 AI 自主建线必需的基础。

但本阶段不强求能够建设轨道/道路。

---

# 51. Create Line 的定义

这里只是：

```text
创建 transport line entity
+
指定 existing stops
```

不是：

```text
建设新的 railway infrastructure
```

---

# 52. CREATE_LINE Preconditions

如果 API 可用：

```text
transport mode

minimum stop count

all stops exist

all stops compatible

route traversability
```

---

# 53. New Line Goal

只有 Live Verification 后开放：

```text
CREATE_LINE_GOAL
```

输入：

```json
{
  "transport_mode": "...",

  "stops": [
    ...
  ],

  "name": "..."
}
```

Task：

```text
create line
↓
fresh snapshot
↓
discover new line ID
↓
optional rename
↓
optional assign vehicles
```

---

# 54. 这将形成第一个完整运营任务

未来：

```text
CREATE_AND_STAFF_LINE_GOAL
```

流程：

```text
create line
↓
snapshot
↓
new line ID
↓
buy vehicle
↓
snapshot
↓
new vehicle ID
↓
assign vehicle
↓
snapshot
↓
verify line operational state
```

Phase 13 如果基础 API 都验证成功，可以实现。

否则留到 Phase 14/15。

---

# 55. DELETE_LINE

同时探测：

```text
DELETE_LINE
```

但：

```text
HIGH risk
destructive
no rollback guarantee
MANUAL only
```

本阶段即使 API 找到：

```text
可以只做到 capability discovery
```

不必强制 Live 删除。

---

# 56. Line Deletion Test

如果一定 Live Verify：

使用：

```text
专用测试存档
+
新建临时测试线路
```

流程：

```text
create test line
↓
verify
↓
delete same test line
↓
verify absence
```

不要删除已有真实线路做测试。

---

# 57. Station Rename

Phase 12 留下的：

```text
RENAME_STATION
DISCOVERED_NOT_VERIFIED
```

Phase 13 顺手完成。

这是低成本任务。

目标：

```text
POSTCONDITION_VERIFIED
```

---

# 58. RENAME_STATION Live Test

流程同 line：

```text
before
↓
rename station
↓
fresh snapshot
↓
verify
↓
restore
↓
verify
```

---

# 59. 不要让 Rename 占用 Phase 13 主线

Station rename 只是：

```text
cleanup / coverage
```

Phase 13 的主线必须仍然是：

```text
vehicle operations
+
line operations
```

---

# 60. Task Goal Registry 扩展

目标：

```text
BUY_VEHICLE_GOAL

SELL_VEHICLE_GOAL

ASSIGN_VEHICLE_TO_LINE_GOAL

REMOVE_VEHICLE_FROM_LINE_GOAL

BUY_AND_ASSIGN_VEHICLE_GOAL

SET_LINE_STOPS_GOAL

CREATE_LINE_GOAL
```

根据 capability 自动：

```text
EXECUTABLE
PARTIALLY_EXECUTABLE
PLAN_ONLY
BLOCKED
```

---

# 61. PARTIALLY_EXECUTABLE

Phase 13 需要正式支持。

例如：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

如果：

```text
BUY_VEHICLE verified

ASSIGN_VEHICLE_TO_LINE not verified
```

返回：

```json
{
  "status": "PARTIALLY_EXECUTABLE",

  "executable_steps": [
    "BUY_VEHICLE"
  ],

  "blocked_steps": [
    "ASSIGN_VEHICLE_TO_LINE"
  ]
}
```

但默认：

```text
不要开始执行
```

除非用户明确允许部分完成。

---

# 62. Default Atomic Intent

复合 Goal 默认：

```text
allow_partial = false
```

如果整套动作不能完成：

```text
BLOCKED_BEFORE_FIRST_MUTATION
```

避免：

```text
车买了
结果没法分配
```

---

# 63. 如果 allow_partial=true

才允许：

```text
PARTIALLY_COMPLETED
```

并明确指出：

```text
剩余未完成目标
```

---

# 64. Task Scope 扩展

Phase 12 只有：

```text
line_ids
operation_types
```

Phase 13 增加：

```text
vehicle_ids

station_ids

depot_ids

new_entity_budget
```

---

# 65. New Entity Budget

新增：

```text
max_new_vehicles

max_new_lines
```

例如默认：

```text
max_new_vehicles = 1

max_new_lines = 0
```

防止规划错误生成大量实体。

---

# 66. Spending Budget

为未来 AI 买车必须增加：

```text
max_spend
```

Task 可以限定：

```text
1000000
```

---

# 67. Spending Precondition

如果购买价格已 ENGINE_VERIFIED：

```text
expected_cost <= remaining_budget
```

否则：

```text
cannot verify spending budget
```

应该：

```text
BLOCKED
```

而不是忽略 budget。

---

# 68. Company Balance Guard

如果 company balance 已可靠读取：

购买前：

```text
company balance
```

只能作为：

```text
financial guard
```

例如：

```text
balance >= expected purchase price
```

如果存在贷款/credit 等复杂规则则记录 limitation。

---

# 69. AI 不允许把钱花光

增加：

```text
minimum_cash_reserve
```

例如 Goal policy 可设：

```text
minimum_cash_reserve = X
```

执行购买前检查。

---

# 70. Operation Impact Preview

对于 Vehicle Buy：

```text
cash cost
fleet count +1
```

对于 Assign：

```text
line vehicle count +1
```

对于 Sell：

```text
vehicle removed
```

对于 Stop Change：

```text
topology delta
```

统一：

```text
preview_operation_impact
```

---

# 71. Phase 13 Flagship Goal

本阶段真正的旗舰测试：

# BUY_AND_ASSIGN_VEHICLE_GOAL

这是第一次证明 AI 不只是“修改名字”。

Live Case：

```text
选取现有可运营线路 L

识别兼容 depot D

识别可购买 model M

BUY M at D
↓
fresh snapshot
↓
discover new vehicle V
↓
ASSIGN V to L
↓
fresh snapshot
↓
verify V.line_id == L
```

---

# 72. Live Test 完成后恢复测试状态

购买车辆是有实际经济副作用的。

如果：

```text
SELL_VEHICLE
```

已经验证：

测试结束：

```text
remove from line
↓
sell test vehicle
```

尽量恢复。

如果 Sell 尚未验证：

```text
使用独立专用存档
```

不要尝试伪 rollback。

---

# 73. Live Test 不能用用户主存档

所有 Phase 13 写验证：

```text
dedicated acceptance save
```

并在 manifest 中记录：

```text
save name
game version
mod version
```

---

# 74. BUY Live Evidence

目录：

```text
diagnostics/phase13-live/buy-vehicle/
```

包含：

```text
before.json
catalog-entry.json
proposal.json
validation.json
command.json
response.json
after.json
diff.json
verification.json
```

---

# 75. ASSIGN Live Evidence

```text
assign-vehicle/
    before.json
    proposal.json
    command.json
    after.json
    verification.json
```

---

# 76. BUY_AND_ASSIGN Live Evidence

```text
buy-and-assign-task/
    task-created.json
    step1-buy.json
    after-buy.json
    replan.json
    step2-assign.json
    after-assign.json
    task-completed.json
```

---

# 77. Stop Change Live Evidence

如果 API 成功：

```text
line-stop-change/
```

测试：

```text
existing sequence
↓
small reversible change
↓
verify
↓
restore
↓
verify
```

尽量使用：

```text
增加/移除一个已经兼容的测试 stop
```

---

# 78. Create Line Live Evidence

如果 API 成功：

只创建：

```text
temporary test line
```

在已有站点之间。

不要建设新基础设施。

---

# 79. Operation Journal Persistence

Phase 11/12 journal 主要内存化。

Phase 13 建议开始增加：

```text
persistent operation history
```

但只存 MCP 工作目录：

```text
runtime/operations.jsonl
```

用途：

```text
debug
crash recovery
idempotency recovery
```

---

# 80. Persistent Idempotency

这是 BUY/SELL 后必须考虑的问题。

如果 MCP server 重启：

内存中的：

```text
executed operation IDs
```

丢失可能导致重复购买。

因此 Phase 13 必须强化：

```text
idempotency across server restart
```

---

# 81. Lua 侧 idempotency 也需要考虑持久性

如果 Lua runtime 能安全保存：

```text
recent executed operation IDs
```

则增加。

否则至少 Python 侧：

```text
journal + postcondition verification
```

必须能够在 restart 后恢复。

---

# 82. Recover Pending Operations

新增：

```text
recover_operations
```

启动时扫描：

```text
SUBMITTED
EXECUTED
但没有 VERIFIED
```

的 operation。

只做：

```text
fresh snapshot
→ verify
```

禁止自动重复发送。

---

# 83. MCP Tool 扩展

目标：

```text
get_vehicle_catalog

get_fleet_profile

get_line_fleet_profile

compare_vehicle_models

get_operation_capabilities

preview_operation_impact
```

Operation 通用 tool 继续保留：

```text
propose_operation
validate_operation
execute_operation
```

不要给每种操作创建重复 executor。

---

# 84. 友好 MCP Wrapper

可以增加：

```text
propose_buy_vehicle

propose_sell_vehicle

propose_assign_vehicle_to_line

propose_set_line_stops
```

但内部：

```text
100% 转 OperationController
```

---

# 85. Task MCP Tools

继续使用：

```text
create_task
plan_task
continue_task
```

增加 goal types 即可。

不要为每一种 goal 复制一套 TaskOrchestrator。

---

# 86. Error Taxonomy 扩展

新增：

```text
VEHICLE_NOT_FOUND

VEHICLE_MODEL_NOT_FOUND

VEHICLE_MODE_INCOMPATIBLE

DEPOT_NOT_FOUND

DEPOT_INCOMPATIBLE

VEHICLE_ALREADY_ASSIGNED

VEHICLE_NOT_ASSIGNED

INSUFFICIENT_FUNDS

SPENDING_BUDGET_EXCEEDED

LINE_MODE_INCOMPATIBLE

INVALID_STOP_SEQUENCE

TERMINAL_NOT_FOUND

ROUTE_NOT_VALID

NEW_ENTITY_NOT_OBSERVED

AMBIGUOUS_NEW_ENTITY
```

---

# 87. AMBIGUOUS_NEW_ENTITY

如果 BUY 后发现：

```text
2 个新 vehicle id
```

但预计买：

```text
1
```

不能任选一个。

返回：

```text
AMBIGUOUS_NEW_ENTITY
```

Task：

```text
BLOCKED
```

---

# 88. Async Game State

某些 TPF2 command 可能不是即时生效。

因此 Verification 应允许：

```text
snapshot N+1
N+2
N+3
```

有限重试。

---

# 89. Verification Poll Budget

增加：

```text
max_verification_snapshots = 3
```

如果仍未达到：

```text
POSTCONDITION_NOT_MET
```

不要无限等。

---

# 90. 不使用 wall-clock sleep 作为成功依据

禁止：

```text
sleep 3 seconds
→ success
```

sleep 可以用于等待下一 game tick，但最终依据始终：

```text
observed snapshot
```

---

# 91. Line State Transition

车辆刚被分配后可能状态：

```text
heading to line
leaving depot
running
```

不要要求：

```text
立即 RUNNING
```

除非真实 API 保证。

Goal satisfaction 分两层：

```text
assignment satisfied
operational satisfied
```

---

# 92. ASSIGNMENT_VERIFIED

例如：

```text
vehicle.line_id == target
```

即可证明：

```text
assignment
```

---

# 93. LINE_OPERATIONAL

未来可以额外等待：

```text
vehicle entered service
```

但作为独立状态。

不要混淆。

---

# 94. Phase 13 Tests

新增：

```text
tests/phase13/
```

至少：

```text
test_vehicle_catalog.py

test_vehicle_operations.py

test_vehicle_assignment.py

test_fleet_profiles.py

test_vehicle_goals.py

test_buy_and_assign_task.py

test_stop_sequence.py

test_operation_recovery.py

test_spending_budget.py
```

---

# 95. Mock BUY Test

模拟：

before：

```text
vehicles = {1,2}
```

execute BUY：

```text
vehicles = {1,2,3}
```

验证：

```text
new_vehicle_ids = [3]
```

---

# 96. Ambiguous BUY Test

before：

```text
{1,2}
```

after：

```text
{1,2,3,4}
```

expected count：

```text
1
```

必须：

```text
AMBIGUOUS_NEW_ENTITY
```

---

# 97. Assignment Test

before：

```text
vehicle 3 line_id = null
```

after：

```text
vehicle 3 line_id = 40
```

返回：

```text
POSTCONDITION_VERIFIED
```

---

# 98. Sell Test

after：

```text
vehicle 3 absent
```

验证成功。

同时检查：

```text
HIGH risk cannot AUTO_SAFE
```

---

# 99. Spending Budget Test

expected price：

```text
500000
```

budget：

```text
400000
```

必须：

```text
SPENDING_BUDGET_EXCEEDED
```

且：

```text
executor calls = 0
```

---

# 100. Composite Task Test

BUY_AND_ASSIGN：

必须证明：

```text
execute count = 2
```

但：

```text
每次 continue_task <= 1
```

即：

```text
continue #1 → BUY
continue #2 → ASSIGN
```

---

# 101. Re-plan Test

BUY 后新 vehicle ID 直到新 snapshot 才知道。

验证 TaskPlan：

```text
Step 2
```

是基于新 Snapshot 创建的。

不是 Step 1 前提前生成。

---

# 102. Stop Order Test

验证：

```text
[A,B,C]
!=
[A,C,B]
```

以及：

```text
[A,B,A]
```

不能被去重。

---

# 103. Phase 13 Flagship MCP Demo

最终至少做到：

用户：

```text
给线路 11833 增加一辆兼容车辆。
```

系统：

```text
读取 line profile
↓
读取 compatible vehicle catalog
↓
生成车型候选
↓
用户/策略选择车型
↓
BUY
↓
fresh snapshot
↓
识别 new vehicle
↓
ASSIGN
↓
fresh snapshot
↓
POSTCONDITION_VERIFIED
```

这是 Phase 13 最重要的验收演示。

---

# 104. 如果只能完成部分 API

最低验收优先级：

```text
1. BUY_VEHICLE
2. ASSIGN_VEHICLE_TO_LINE
3. BUY_AND_ASSIGN_VEHICLE_GOAL
```

这三个优先于：

```text
station rename
line rename增强
更多统计接口
```

---

# 105. Phase 13 最低成功标准

至少完成：

```text
BUY_VEHICLE
+
ASSIGN_VEHICLE_TO_LINE
```

两项真实：

```text
POSTCONDITION_VERIFIED
```

并成功完成：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

---

# 106. 次级成功目标

优先顺序：

```text
SELL_VEHICLE

REMOVE_VEHICLE_FROM_LINE

RENAME_STATION

SET_LINE_STOPS
```

---

# 107. Stretch Goal

如果时间足够：

```text
CREATE_LINE
```

基于：

```text
existing stations
```

完成 Live Verify。

---

# 108. Phase 13 不做

暂不做：

```text
build track

build road

build station

terraform

bridge/tunnel geometry

automatic path construction

bulldoze world infrastructure

full autonomous company control
```

---

# 109. 但必须为 Phase 14 留接口

Line / stop descriptor 不要写死成：

```text
station_id only
```

应为后续支持：

```text
newly constructed station IDs
```

预留。

---

# 110. 文档

新增：

```text
docs/PHASE13_OPERATIONAL_EXPANSION.md
```

包括：

```text
Vehicle catalog

Vehicle lifecycle

Buy/Sell

Assignment

Line stop model

Risk classification

Spending guard

Persistent idempotency

Operation recovery
```

---

# 111. README

增加：

```text
Phase 13 Operational Expansion
```

明确当前 capability matrix。

例如：

| Capability | Status |
|---|---|
| RENAME_LINE | POSTCONDITION_VERIFIED |
| RENAME_STATION | ... |
| BUY_VEHICLE | ... |
| SELL_VEHICLE | ... |
| ASSIGN_VEHICLE_TO_LINE | ... |
| SET_LINE_STOPS | ... |
| CREATE_LINE | ... |

只根据实际验证状态填写。

---

# 112. Evidence Manifest

最终：

```text
diagnostics/phase13-live/manifest.json
```

列出：

```text
POSTCONDITION_VERIFIED operations

DISCOVERED_NOT_VERIFIED operations

FAILED probes

game version

test save

write config restore status
```

---

# 113. 最终交付

生成：

```text
tpf2-mcp-phase13-operational-expansion.zip
```

必须包含：

```text
完整源码

Phase 13 API probes

Vehicle catalog

Fleet profiles

new operations

new goals

task orchestration integration

tests

Live evidence

PHASE13_OPERATIONAL_EXPANSION.md
```

---

# 114. Phase 13 验收标准

必须：

- Phase 12 原测试继续通过；
- 不破坏 RENAME_LINE write closed loop；
- vehicle ID 稳定性得到验证；
- 有真实 vehicle catalog；
- 找到车辆购买 API 或明确记录 probe failure；
- BUY_VEHICLE 完成 Live Verification；
- 能从 fresh snapshot 确认新 vehicle ID；
- 找到车辆线路分配 API；
- ASSIGN_VEHICLE_TO_LINE 完成 Live Verification；
- BUY_AND_ASSIGN_VEHICLE_GOAL 可闭环执行；
- 两步之间存在 fresh snapshot 和 re-plan；
- 不提前猜 new vehicle ID；
- 每个 continue 最多执行一个 mutation；
- SELL_VEHICLE 若开放必须 HIGH risk / MANUAL；
- 有 spending budget；
- 有 task entity scope；
- 有 persistent/recoverable operation journal；
- timeout 不直接重复购买；
- capability 只有 Live 验证后才能标 VERIFIED；
- 所有测试使用专用 save；
- 写配置结束后恢复 disabled；
- 最终产出：

```text
tpf2-mcp-phase13-operational-expansion.zip
```

---

# 115. 最终能力目标

Phase 13 完成后，应第一次达到：

```text
AI:
“我要给这条线路增加一辆车。”

MCP:
读取线路
↓
判断运输模式
↓
读取可购买车辆
↓
选择/比较车型
↓
购买车辆
↓
观察新车辆
↓
分配到线路
↓
观察线路
↓
确认操作完成
```

这才是第一个真正意义上的：

```text
TPF2 AI Operator
```

而不是通用 MCP 框架演示。

---

# 116. Phase 14 预告

Phase 13 完成后立即进入：

# Phase 14 — Line Creation & Infrastructure Planning

重点：

```text
AI 新建线路

AI 规划 station sequence

AI 选择站点

AI 建设新站

AI 规划铁路/道路 geometry

AI 创建线路

AI 配车

AI 调整停站

AI 形成完整新运输服务
```

Phase 13 需要把：

```text
vehicles
lines
stops
operations
task orchestration
```

这四层基础打牢，为 Phase 14 直接服务。