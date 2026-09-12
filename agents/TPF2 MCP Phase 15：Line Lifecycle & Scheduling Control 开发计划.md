# TPF2 MCP Phase 15：Line Lifecycle & Scheduling Control

## 0. 当前实际状态

Phase 14 已经完成：

```text
BUY_VEHICLE
    Engine verified
    Controller supported
    Task supported

ASSIGN_VEHICLE_TO_LINE
    Engine verified
    Controller supported
    Task supported
```

并已经存在：

```text
BUY_VEHICLE_GOAL
ASSIGN_VEHICLE_TO_LINE_GOAL
BUY_AND_ASSIGN_VEHICLE_GOAL
EXPAND_LINE_WITH_VEHICLE_GOAL
```

Phase 14 同时建立：

```text
Operation Handler Registry
Capability 分层状态
Task runtime_context
persistent journals
```

但是当前仍缺：

```text
Phase 14 MCP-native Live acceptance
```

并且以下能力仍未验证：

```text
SELL_VEHICLE

REMOVE_VEHICLE_FROM_LINE

SEND_VEHICLE_TO_DEPOT

SET_LINE_STOPS

CREATE_LINE

DELETE_LINE

Scheduling Operations
```

Phase 15 的任务是：

# 完成线路与车辆生命周期控制

形成：

```text
Create
Configure
Staff
Operate
Reconfigure
Unstaff
Retire
```

完整运营闭环。

---

# 1. Phase 15 第一硬任务：补 Phase 14 MCP-native Live Acceptance

在任何新功能之前，必须证明：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

能够通过正常 MCP 路径执行。

禁止使用：

```text
tools/test-phase13-buy-live.py
tools/test-phase13-assign-live.py
```

作为 Phase 15 验收依据。

必须走：

```text
MCP
↓
TaskOrchestrator
↓
OperationController
↓
Handler
↓
Bridge
↓
Lua Dispatcher
↓
TPF2
```

---

# 2. Phase 14 Acceptance Case

专用测试存档。

执行：

```text
create_task(
    BUY_AND_ASSIGN_VEHICLE_GOAL
)
```

然后：

```text
continue #1
→ BUY_VEHICLE
```

要求：

```text
fresh snapshot
new vehicle ID discovered
runtime_context.new_vehicle_id populated
```

然后：

```text
continue #2
→ ASSIGN_VEHICLE_TO_LINE
```

要求：

```text
fresh snapshot
vehicle.line_id == target_line
```

最终：

```text
Task = COMPLETED
```

---

# 3. Acceptance Evidence

生成：

```text
diagnostics/phase15-live/
    phase14-mcp-native-buy-and-assign/
        task-created.json
        plan-before-buy.json
        buy-proposal.json
        buy-validation.json
        buy-command.json
        after-buy.json
        buy-verification.json
        runtime-context.json
        replan.json
        assign-proposal.json
        assign-command.json
        after-assign.json
        assign-verification.json
        task-completed.json
```

---

# 4. 必须验证 One Mutation Per Continue

确认：

```text
continue_task #1
```

只执行：

```text
BUY
```

而：

```text
continue_task #2
```

只执行：

```text
ASSIGN
```

任何一次：

```text
mutation_count > 1
```

都算失败。

---

# 5. 修复 Goal Capability 判定

当前 `goals.py` 主要根据：

```text
engine_verified
```

判断 Goal EXECUTABLE。

Phase 15 要改成：

```text
engine_verified
AND
controller_supported
AND
task_supported
```

如果：

```text
runtime_enabled = false
```

Goal 可以显示：

```text
EXECUTABLE_BUT_DISABLED
```

而不是错误地：

```text
BLOCKED
```

---

# 6. Goal Capability States

统一：

```text
PLAN_ONLY

ENGINE_ONLY

CONTROLLER_READY

TASK_READY

EXECUTABLE_BUT_DISABLED

EXECUTABLE

BLOCKED
```

---

# 7. 第二主线：REMOVE_VEHICLE_FROM_LINE

这是车辆生命周期的关键缺口。

必须找到真实 TPF2 API。

重点扫描 shipped scripts：

```text
api.cmd.make.setLine
api.cmd.make.sendToDepot
api.cmd.make.removeVehicle
vehicle command helpers
```

不要猜：

```text
line = -1
line = nil
```

的语义。

---

# 8. REMOVE_VEHICLE_FROM_LINE 定义

它只表示：

```text
车辆不再属于当前线路
```

不等于：

```text
SELL
```

也不等于：

```text
SEND_TO_DEPOT
```

三者必须严格区分。

---

# 9. Live Test

选择：

```text
Phase 15 新购买的测试车辆
```

先：

```text
ASSIGN → Line
```

然后：

```text
REMOVE_VEHICLE_FROM_LINE
```

Fresh Snapshot：

```text
vehicle.line_id != old_line
```

如果实际 API 的结果是：

```text
line_id = null
```

记录实际语义。

---

# 10. REMOVE Handler

增加：

```text
operations/handlers/remove_vehicle_from_line.py
```

支持：

```text
validate_parameters
preconditions
command
postcondition
```

---

# 11. REMOVE Goal

新增：

```text
REMOVE_VEHICLE_FROM_LINE_GOAL
```

goal satisfaction：

```text
vehicle not assigned to specified line
```

---

# 12. 第三主线：SEND_VEHICLE_TO_DEPOT

如果 API 独立存在：

```text
SEND_VEHICLE_TO_DEPOT
```

单独实现。

不要把它塞进 REMOVE。

---

# 13. Depot Goal

新增：

```text
SEND_VEHICLE_TO_DEPOT_GOAL
```

但只有能从 snapshot 证明 depot state 后才标 EXECUTABLE。

如果只能证明：

```text
line_id cleared
```

而无法证明：

```text
vehicle actually in depot
```

则：

```text
postcondition = PARTIALLY_VERIFIED
```

---

# 14. Vehicle Lifecycle

Phase 15 建立明确生命周期模型：

```text
PURCHASED

UNASSIGNED

ASSIGNED

IN_SERVICE

REMOVED_FROM_LINE

GOING_TO_DEPOT

IN_DEPOT

SOLD
```

只对能证明的状态做语义映射。

其他保持：

```text
UNKNOWN
```

---

# 15. 第四主线：SELL_VEHICLE

Phase 15 必须继续寻找真实 API。

优先搜索：

```text
sellVehicle
removeVehicle
disposeVehicle
api.cmd.make.*
```

并追到：

```text
call signature
argument semantics
command callback
```

---

# 16. SELL 只能测试临时车辆

流程：

```text
BUY temp vehicle
↓
verify
↓
remove / depot if required
↓
SELL
↓
fresh snapshot
↓
vehicle ID absent
```

严禁出售存档已有车辆。

---

# 17. SELL Risk

必须：

```text
risk_class = HIGH
destructive = true
supports_rollback = false
AUTO_SAFE = forbidden
```

---

# 18. SELL Postcondition

最基本：

```text
vehicle_id absent from snapshot
```

如果还能读取：

```text
company balance
```

保存 before / after。

但继续禁止：

```text
balance delta == exact sale price
```

这种未经证明的推断。

---

# 19. SELL Goal

新增：

```text
SELL_VEHICLE_GOAL
```

必须：

```text
explicit approval
```

---

# 20. Vehicle Retirement Composite Goal

如果：

```text
REMOVE
SEND_TO_DEPOT
SELL
```

都完成验证，则新增：

```text
RETIRE_VEHICLE_GOAL
```

Planner 根据真实 API 要求规划：

```text
remove
↓
depot
↓
sell
```

或者实际必要流程。

---

# 21. 不要写死退役顺序

必须基于：

```text
API constraints
current state
```

动态决定。

---

# 22. 第五主线：真正解析 Line Stop Model

Phase 15 必须彻底搞清线路 Stops 的真实结构。

当前 collector 需要扩展到：

```text
line_id

ordered_stop_sequence
```

每个 stop 至少记录：

```text
sequence_index

station_id

terminal_entity_id

terminal_index

stop_direction if available

raw descriptor
```

---

# 23. Preserve Raw Stop Descriptor

增加：

```text
raw
```

用于后续 API 对照。

因为 TPF2 的 stop 对象可能不是简单：

```text
station_id
```

---

# 24. Stop Sequence 必须允许重复

例如：

```text
A
B
C
B
A
```

必须保留。

不能：

```python
set(stops)
```

---

# 25. 找到 Line Creation/Modification Source

进行 shipped-source 深挖。

搜索：

```text
Line
TransportLine
LineComponent
createLine
removeLine
setLine
setStops
setLineStops
addLine
api.cmd.make
```

---

# 26. 不仅 grep 函数名

必须追：

```text
调用位置
传参数方式
构造的数据结构
```

输出：

```text
docs/line-command-source-trace.md
```

---

# 27. Line API Trace Artifact

至少记录：

```json
{
  "candidate": "...",
  "source_file": "...",
  "call_site": "...",
  "signature": "...",
  "arguments": [],
  "semantic_confidence": "...",
  "verification": "..."
}
```

---

# 28. 第六主线：CREATE_LINE

Phase 15 应优先于 `SET_LINE_STOPS` 尝试创建一条临时测试线路。

原因：

新建临时线路更适合后续：

```text
修改 stop
删除 line
```

测试。

---

# 29. CREATE_LINE 定义

Phase 15 只处理：

```text
使用现有 station/terminal
创建 line entity
```

不建设：

```text
new track
new road
new station
```

---

# 30. CREATE_LINE Operation

目标参数：

```json
{
  "transport_mode": "...",
  "stops": [
    {
      "station_id": 100,
      "terminal_id": 1
    },
    {
      "station_id": 200,
      "terminal_id": 0
    }
  ]
}
```

实际内部 payload 按真实 API。

---

# 31. CREATE Preconditions

至少：

```text
all station entities exist

all terminal descriptors valid

transport mode compatible

minimum stop count satisfied

snapshot current
```

---

# 32. CREATE Verification

before：

```text
line ID set
```

after：

```text
new line ID set
```

要求：

```text
exactly one expected new line
```

并进一步：

```text
new_line.ordered_stops == desired stops
```

---

# 33. Ambiguous New Line

如果一次命令后出现：

```text
multiple new line IDs
```

返回：

```text
AMBIGUOUS_NEW_ENTITY
```

不要任选。

---

# 34. CREATE_LINE Handler

增加：

```text
operations/handlers/create_line.py
```

---

# 35. CREATE_LINE Goal

新增：

```text
CREATE_LINE_GOAL
```

Task 完成：

```text
new line exists
+
stops verified
```

runtime_context：

```text
new_line_id
```

---

# 36. 第七主线：SET_LINE_STOPS

在 CREATE_LINE 可用后，用临时线路测试。

优先对测试线路做：

```text
A-B-C
→
A-C
```

避免改主存档线路。

---

# 37. SET_LINE_STOPS Operation

参数：

```json
{
  "line_id": 123,
  "stops": [...]
}
```

---

# 38. Precondition

记录：

```text
expected_old_stop_sequence
```

如果执行前实际 sequence 已变：

```text
PRECONDITION_CHANGED
```

拒绝。

---

# 39. Postcondition

严格比较：

```text
ordered sequence
terminal identity
duplicate stops
```

不能只比：

```text
station_count
```

---

# 40. Stop Mutation Diff

输出：

```json
{
  "removed": [],
  "added": [],
  "reordered": true,
  "before": [],
  "after": []
}
```

---

# 41. Stop Change Risk

```text
MEDIUM
MANUAL
```

---

# 42. SET_LINE_STOPS Goal

新增：

```text
SET_LINE_STOPS_GOAL
```

---

# 43. Phase 10 Simulation 联动

SET_LINE_STOPS Proposal 前运行：

```text
simulate_line_stop_change
```

如果现有 Phase 10 没有完全支持，需要补。

输出：

```text
component delta
reachability delta
transfer delta
```

---

# 44. 第八主线：DELETE_LINE

如果 CREATE_LINE 成功，应只删除：

```text
本阶段创建的临时测试 line
```

---

# 45. DELETE_LINE

必须：

```text
HIGH
destructive
MANUAL
no rollback guarantee
```

---

# 46. DELETE Verification

Fresh Snapshot：

```text
line ID absent
```

还要检查：

```text
assigned vehicles
```

如果删除 line 会自动影响车辆：

记录 observed side effects。

---

# 47. 不自动删除带车线路

precondition 建议：

```text
line.vehicle_ids empty
```

否则：

```text
LINE_NOT_EMPTY
```

除非未来明确支持：

```text
force_delete
```

Phase 15 不做 force。

---

# 48. 第九主线：Scheduling Model Discovery

这部分是最终 AI 调度所必需。

需要确认 TPF2 实际可控的：

```text
minimum load

maximum waiting time

full-load rules

terminal waiting policy

stop-specific behavior
```

---

# 49. 不以 UI 文本猜 API

必须：

```text
UI
↓
source trace
↓
component
↓
command API
```

---

# 50. Scheduling Source Map

输出：

```text
docs/scheduling-source-map.md
```

至少包含：

```text
UI control

data component

read path

write command

parameter semantics

verified state
```

---

# 51. 至少完成一个真实 Scheduling Parameter

Phase 15 标准验收要求至少拿下一个。

例如实际发现：

```text
minimum load
```

则实现：

```text
SET_MINIMUM_LOAD
```

---

# 52. 不做泛化 SET_SCHEDULE

每个真实参数独立 capability。

例如：

```text
SET_MINIMUM_LOAD

SET_MAX_WAIT_TIME

SET_FULL_LOAD_POLICY
```

---

# 53. Scheduling Handler

按 capability 单独 handler。

不要：

```text
set_any_line_param(key, value)
```

这种过度通用接口。

---

# 54. Scheduling Verification

必须：

```text
before
command
fresh snapshot
after
```

如果 UI 也可读取：

额外：

```text
UI_CROSS_VERIFIED
```

---

# 55. Scheduling Goal

例如：

```text
SET_MINIMUM_LOAD_GOAL
```

---

# 56. Phase 15 高层业务 Goal：EXPAND_LINE_CAPACITY

当前用户最终需要 AI 自己运营线路。

新增：

```text
EXPAND_LINE_CAPACITY_GOAL
```

第一版只做：

```text
add one compatible vehicle
```

---

# 57. 输入

```json
{
  "line_id": 531841,
  "delta_vehicles": 1
}
```

---

# 58. Planner

读取：

```text
line fleet
existing vehicle template
depot
```

生成：

```text
BUY
↓
ASSIGN
```

---

# 59. 不声称“最优增车”

这只是：

```text
operational action
```

不是：

```text
optimal decision
```

如果由 Phase 10 recommendation 触发：

标：

```text
HEURISTIC
```

---

# 60. SHRINK_LINE_CAPACITY Goal

如果 REMOVE 完成：

```text
SHRINK_LINE_CAPACITY_GOAL
```

默认：

```text
remove one vehicle from line
```

不卖车。

---

# 61. Explicit Sell Separation

必须保持：

```text
减少运力
!=
出售车辆
```

---

# 62. CREATE_AND_STAFF_LINE_GOAL

当：

```text
CREATE_LINE
BUY
ASSIGN
```

都可用后必须实现。

---

# 63. 流程

```text
CREATE_LINE
↓
Fresh Snapshot
↓
new_line_id
↓
BUY_VEHICLE
↓
Fresh Snapshot
↓
new_vehicle_id
↓
ASSIGN
↓
Fresh Snapshot
↓
COMPLETED
```

---

# 64. 三次 continue

必须：

```text
continue #1 → CREATE
continue #2 → BUY
continue #3 → ASSIGN
```

不能合并。

---

# 65. CREATE_AND_STAFF runtime_context

保存：

```json
{
  "new_line_id": 123,
  "new_vehicle_id": 456
}
```

只能来自 verified operation。

---

# 66. CREATE_AND_CONFIGURE_LINE_GOAL

如果 Scheduling/Stops 都完成，可进一步：

```text
CREATE
↓
SET_STOPS if required
↓
SET scheduling
↓
BUY
↓
ASSIGN
```

作为 stretch goal。

---

# 67. Operation Provenance

Phase 15 增加：

```text
operation_source
```

比如：

```text
USER_EXPLICIT
TASK_PLANNER
PLANNING_OPTION
RECOVERY
```

方便审计。

---

# 68. Recommendation != Authorization

即使：

```text
Phase 10 recommendation
```

产生任务，也不能自动当用户授权。

MEDIUM/HIGH operation：

```text
WAITING_FOR_APPROVAL
```

---

# 69. Persistent Task Recovery

当前已有 journal。

Phase 15 必须验证真正 restart recovery。

---

# 70. Recovery Live Test

场景：

```text
BUY submitted
↓
TPF2 executed
↓
MCP server terminated before verification
↓
restart
```

要求：

```text
read journal
↓
fresh snapshot
↓
identify new vehicle
↓
verify operation
```

绝不能重新 BUY。

---

# 71. Pending CREATE_LINE 同样处理

如果 server crash：

不能再 create 第二条线路。

---

# 72. Persistent Operation Identity

要求：

```text
operation_id
task_id
step_id
```

跨进程保持。

---

# 73. Exactly Once Semantic

无法保证 engine transaction exactly-once 时，目标是：

```text
effectively-once
```

依靠：

```text
idempotency ID
journal
snapshot postcondition
recovery
```

---

# 74. Capability Registry 再升级

Phase 15 Capability 增加：

```text
live_mcp_verified
```

因为：

```text
engine_verified
```

与：

```text
MCP product path verified
```

是两回事。

---

# 75. 示例

```json
{
  "operation_type": "BUY_VEHICLE",

  "engine_verified": true,

  "controller_supported": true,

  "task_supported": true,

  "live_mcp_verified": true,

  "runtime_enabled": false
}
```

---

# 76. Capability 总状态

可以派生：

```text
DISCOVERED

ENGINE_VERIFIED

PRODUCT_READY

RUNTIME_ENABLED
```

其中：

```text
PRODUCT_READY
```

要求：

```text
engine_verified
controller_supported
task_supported
live_mcp_verified
```

---

# 77. README Capability Matrix

使用：

| Operation | Engine | Controller | Task | Live MCP |
|---|---:|---:|---:|---:|
| BUY_VEHICLE | Yes | Yes | Yes | Yes |
| ASSIGN_VEHICLE_TO_LINE | Yes | Yes | Yes | Yes |
| REMOVE_VEHICLE_FROM_LINE | ... | ... | ... | ... |
| SELL_VEHICLE | ... | ... | ... | ... |
| CREATE_LINE | ... | ... | ... | ... |
| SET_LINE_STOPS | ... | ... | ... | ... |

---

# 78. Live Evidence 必须完整

禁止：

```text
docs says VERIFIED
```

但没有：

```text
before/after/command/verification
```

证据。

---

# 79. Tests

新增：

```text
tests/phase15/
```

至少：

```text
test_phase14_mcp_acceptance.py

test_remove_vehicle.py

test_send_to_depot.py

test_sell_vehicle.py

test_line_stop_model.py

test_create_line.py

test_set_line_stops.py

test_delete_line.py

test_scheduling.py

test_create_and_staff_line.py

test_persistent_recovery.py

test_capability_product_ready.py
```

---

# 80. Regression

跑：

```text
pytest -q
```

而不是只跑新测试。

最终记录：

```text
tests total
passed
failed
```

---

# 81. Artifact Hygiene

当前 Phase 14 zip 中仍包含大量：

```text
__pycache__
*.pyc
```

Phase 15 最终包必须清理。

加入 packaging exclusion：

```text
__pycache__/
*.pyc
.pytest_cache/
```

---

# 82. 这次强制清理

最终 ZIP 不得包含：

```text
__pycache__
.pyc
temporary test artifacts
```

---

# 83. Phase 15 Live Test A

MCP-native：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

必须通过。

这是硬验收。

---

# 84. Live Test B

如果 REMOVE API 找到：

```text
new test vehicle
↓
assign
↓
remove
↓
verify
```

---

# 85. Live Test C

如果 SELL API 找到：

```text
buy temporary
↓
sell temporary
↓
verify absent
```

---

# 86. Live Test D

CREATE_LINE：

使用：

```text
existing A
existing B
```

创建临时 line。

---

# 87. Live Test E

SET_LINE_STOPS：

只操作 D 中创建的临时 line。

---

# 88. Live Test F

DELETE_LINE：

只删除 D 创建的 line。

---

# 89. Live Test G

一个 scheduling parameter：

修改：

```text
temporary line
```

然后恢复原值。

---

# 90. Phase 15 Flagship Demo

如果 CREATE + BUY + ASSIGN 成功：

用户：

```text
“用现有站点 A 和 B 建一条线路，并给它配一辆和线路 X 相同的车。”
```

MCP：

```text
validate A/B
↓
CREATE_LINE
↓
fresh snapshot
↓
new line ID
↓
select X vehicle template
↓
BUY
↓
fresh snapshot
↓
new vehicle ID
↓
ASSIGN
↓
fresh snapshot
↓
verify
↓
Task COMPLETED
```

---

# 91. Phase 15 标准验收

必须：

1. Phase 14 MCP-native BUY_AND_ASSIGN Live Test 成功；
2. `live_mcp_verified` capability 状态落地；
3. BUY/ASSIGN 正式变成 PRODUCT_READY；
4. 至少找到并验证一个新的车辆生命周期 operation；
5. Line stop raw/ordered model 明确；
6. CREATE_LINE 或 SET_LINE_STOPS 至少一个 POSTCONDITION_VERIFIED；
7. 至少一个 scheduling parameter 有明确 source trace；
8. 所有操作仍走 Controller；
9. one mutation per continue 不变量保持；
10. persistent recovery 测试通过；
11. 完整 pytest 回归通过；
12. ZIP 清除 `__pycache__` / `.pyc`。

---

# 92. 优秀验收

目标：

```text
BUY_VEHICLE
ASSIGN_VEHICLE_TO_LINE
REMOVE_VEHICLE_FROM_LINE
SELL_VEHICLE
CREATE_LINE
SET_LINE_STOPS
```

全部：

```text
PRODUCT_READY
```

并至少一个：

```text
Scheduling Capability
```

达到：

```text
ENGINE_VERIFIED
```

或：

```text
PRODUCT_READY
```

---

# 93. Phase 15 不做

不要开始：

```text
铺轨 geometry

修道路

建设 station

terraform

bridge planning

tunnel planning

bulldoze infrastructure

全自动地图优化
```

---

# 94. Phase 16 才进入 Infrastructure Construction

Phase 16：

# Infrastructure & Station Construction

目标：

```text
查询可建设位置

站点 placement

station construction

track/road segment construction

geometry validation

terrain/collision handling

connect stations

CREATE_LINE

SET_STOPS

BUY

ASSIGN
```

---

# 95. Phase 15 最终交付物

生成：

```text
tpf2-mcp-phase15-line-lifecycle.zip
```

必须包含：

```text
源码

operation handlers

goal handlers

line stop model

line API source trace

scheduling source trace

persistent recovery

unit tests

full regression result

Live MCP evidence

PHASE15_LINE_LIFECYCLE.md
```

---

# 96. 最终目标

Phase 15 完成后，AI 应至少能稳定完成：

```text
现有线路：
增加车辆
移除车辆
必要时出售车辆
调整停站
调整至少一种真实调度策略
```

并尽量达到：

```text
新建 existing-station line
↓
给新线路购买车辆
↓
分配车辆
↓
验证线路成立
```

这时再进入 Phase 16 建站/铺线，技术路线才是完整的。