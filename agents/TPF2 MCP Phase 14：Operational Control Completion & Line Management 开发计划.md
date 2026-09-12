# TPF2 MCP Phase 14：Operational Control Completion & Line Management

## 0. 当前状态

当前 Phase 13 已真实完成两个 TPF2 Engine 写操作：

```text
BUY_VEHICLE
POSTCONDITION_VERIFIED

ASSIGN_VEHICLE_TO_LINE
POSTCONDITION_VERIFIED
```

实际验证：

```text
buyVehicle(...)
↓
fresh snapshot
↓
new vehicle id = 1747376
```

以及：

```text
setLine(vehicle, line, 0)
↓
fresh snapshot
↓
vehicle.line_id == target line
```

因此底层 API 已经证明可行。

但是当前架构仍存在：

```text
Engine Write Capability
        ↓
       GAP
        ↓
OperationController
        ↓
TaskOrchestrator
```

Phase 14 第一目标就是消除这个 GAP。

---

# 1. Phase 14 总目标

本阶段完成：

```text
Verified Engine Command
↓
Operation Capability
↓
OperationController
↓
Task Goal
↓
Closed-loop Execution
```

随后继续扩展：

```text
SELL_VEHICLE

REMOVE_VEHICLE_FROM_LINE

SEND_VEHICLE_TO_DEPOT

SET_LINE_STOPS

CREATE_LINE

线路调度策略
```

最终形成：

```text
AI Fleet + Line Operator
```

---

# 2. Phase 14 第一优先事项：修复 Capability 状态模型

当前：

```python
BUY_VEHICLE:
    verified=True
    available=False
```

这是一个合理的 Phase 13 中间状态，但 Phase 14 必须拆清楚概念。

建议 Capability 改为：

```text
discovered
engine_verified
controller_supported
task_supported
enabled
```

不要继续使用模糊：

```text
available
verified
```

---

# 3. 推荐 Capability Schema

例如：

```json
{
  "operation_type": "BUY_VEHICLE",

  "discovered": true,

  "engine_verified": true,

  "controller_supported": true,

  "task_supported": true,

  "runtime_enabled": false,

  "risk_class": "MEDIUM",

  "source_status": "POSTCONDITION_VERIFIED"
}
```

这样可以准确表达：

```text
API 是否存在
API 是否实测
Python 是否支持
Task 是否支持
当前是否允许执行
```

---

# 4. Capability State Machine

统一：

```text
UNKNOWN
↓
DISCOVERED
↓
ENGINE_VERIFIED
↓
CONTROLLER_SUPPORTED
↓
TASK_SUPPORTED
↓
RUNTIME_ENABLED
```

其中：

```text
RUNTIME_ENABLED
```

不是永久状态，只代表当前配置。

---

# 5. 清理遗留注释

当前：

```python
"""Proposal-first controller. It is intentionally unable to write to TPF2 yet."""
```

已经错误。

Phase 14 必须审计：

```text
controller
tasks
README
docs
```

删除所有“尚不能写游戏”的历史描述。

---

# 6. OperationController 重构

当前 Controller 对：

```text
RENAME_LINE
```

存在大量硬编码。

Phase 14 要改成：

```text
operation handlers registry
```

---

# 7. Operation Handler

新增：

```text
operations/handlers/
```

建议：

```text
base.py

rename_line.py

buy_vehicle.py

assign_vehicle.py

sell_vehicle.py

line_stops.py

create_line.py
```

统一接口：

```python
class OperationHandler:
    validate_parameters()
    resolve_target()
    build_preconditions()
    expected_effect()
    build_command()
    verify_postcondition()
```

---

# 8. Controller 不再判断具体 operation_type

禁止：

```python
if operation_type == "RENAME_LINE":
    ...
elif operation_type == ...
```

改成：

```text
handler = registry.get(operation_type)
```

---

# 9. 第一项正式接入：BUY_VEHICLE

Phase 13 已经验证 engine API。

Phase 14 将其真正接入：

```text
OperationController
```

---

# 10. BUY_VEHICLE 参数模型

Phase 13 使用：

```text
existing vehicle transportVehicleConfig
```

作为配置来源。

Phase 14 第一版允许：

```json
{
  "depot_id": 626601,
  "source_vehicle_id": 7656
}
```

含义：

```text
购买一辆与 source_vehicle 相同 TransportVehicleConfig 的新车
```

这是当前最可信的方式。

---

# 11. 不急着虚构 Vehicle Catalog

当前：

```text
price/catalog semantic
```

尚未验证。

因此 Phase 14 初期不应该声称：

```text
完整车型商店 catalog
```

优先实现：

```text
clone-compatible purchase
```

即：

```text
根据现有车辆 transportVehicleConfig 买同型车
```

---

# 12. 后续再增加真正 Vehicle Catalog

如果能够可靠读取：

```text
vehicle construction menu
model repository
availability
price
```

再扩展：

```text
vehicle_model_id
```

购买模式。

---

# 13. BUY_VEHICLE Proposal

示例：

```json
{
  "operation_type": "BUY_VEHICLE",

  "target": {
    "depot_id": 626601
  },

  "parameters": {
    "source_vehicle_id": 7656
  }
}
```

---

# 14. BUY Preconditions

必须：

```text
depot exists

source vehicle exists

transportVehicleConfig readable

vehicle/depot transport mode compatible

snapshot current

write enabled

BUY_VEHICLE allowlisted
```

---

# 15. BUY Verification

Phase 13 方法保留：

```text
before vehicle ID set
↓
execute
↓
fresh snapshot
↓
after vehicle ID set
```

计算：

```text
new_ids = after - before
```

必须：

```text
len(new_ids) == 1
```

否则：

```text
NEW_ENTITY_NOT_OBSERVED

或

AMBIGUOUS_NEW_ENTITY
```

---

# 16. Operation Result 保存 discovered entity

结果：

```json
{
  "new_entities": [
    {
      "entity_type": "VEHICLE",
      "entity_id": 1747376
    }
  ]
}
```

Task 后续直接消费这个结果。

---

# 17. 第二项正式接入：ASSIGN_VEHICLE_TO_LINE

参数：

```json
{
  "vehicle_id": 1747376,
  "line_id": 531841,
  "stop_index": 0
}
```

---

# 18. ASSIGN Preconditions

必须：

```text
vehicle exists

line exists

vehicle not already assigned to target line

snapshot current
```

如果 transport mode 可可靠确认：

增加：

```text
mode compatible
```

否则：

```text
UNKNOWN
```

不要伪验证。

---

# 19. ASSIGN Verification

必须双重验证：

```text
vehicle.line_id == line_id
```

如果 line.vehicle_ids 可用：

同时：

```text
vehicle_id in line.vehicle_ids
```

---

# 20. 双源冲突

如果：

```text
vehicle.line_id == target
```

但：

```text
vehicle not in line.vehicle_ids
```

返回：

```text
POSTCONDITION_CONFLICT
```

不要判成功。

---

# 21. BUY_VEHICLE Goal

正式增加：

```text
BUY_VEHICLE_GOAL
```

goal：

```json
{
  "depot_id": 626601,
  "source_vehicle_id": 7656,
  "count": 1
}
```

---

# 22. Satisfaction

Task 保存 baseline：

```text
vehicle ID set
```

完成条件：

```text
exactly one expected newly observed vehicle
```

---

# 23. ASSIGN_VEHICLE_TO_LINE Goal

正式增加：

```text
ASSIGN_VEHICLE_TO_LINE_GOAL
```

满足：

```text
vehicle.line_id == desired line
```

---

# 24. Phase 14 核心 Composite Goal

必须完成：

# BUY_AND_ASSIGN_VEHICLE_GOAL

这是 Phase 14 最重要验收目标。

---

# 25. BUY_AND_ASSIGN 逻辑

输入：

```json
{
  "depot_id": 626601,

  "source_vehicle_id": 7656,

  "target_line_id": 531841
}
```

---

# 26. Step 1

```text
BUY_VEHICLE
```

执行：

```text
buy
↓
fresh snapshot
↓
discover new vehicle ID
```

例如：

```text
1747376
```

---

# 27. Step 2 必须运行时生成

根据 Step 1 结果：

```text
vehicle_id = discovered new ID
```

再生成：

```text
ASSIGN_VEHICLE_TO_LINE
```

严禁 Step 1 之前生成 Step 2 的 vehicle_id。

---

# 28. Task Context

Phase 14 给 Task 增加：

```text
runtime_context
```

例如：

```json
{
  "new_vehicle_id": 1747376
}
```

用于后续步骤。

---

# 29. runtime_context 只能来自 verified result

禁止 Planner 写：

```text
new_vehicle_id = predicted
```

必须来源：

```text
POSTCONDITION_VERIFIED operation result
```

---

# 30. BUY_AND_ASSIGN Completion

最终验证：

```text
new vehicle exists
AND
new vehicle line_id == target_line_id
```

Task：

```text
COMPLETED
```

---

# 31. 每个 continue_task 仍只允许一个 mutation

必须保持 Phase 12 不变量：

```text
continue #1
→ BUY

continue #2
→ ASSIGN
```

不能：

```text
一个 continue
→ BUY + ASSIGN
```

---

# 32. TaskPlanner 改造成 Multi-Step Goal Planner

目前 TaskPlanner 基本 rename-only。

Phase 14 增加：

```text
goal handlers
```

---

# 33. Goal Handler

建议：

```text
tasks/goals/
```

例如：

```text
rename.py
vehicle_purchase.py
vehicle_assignment.py
buy_and_assign.py
line_management.py
```

统一：

```python
is_satisfied()
plan_next_step()
scope()
capability_status()
```

---

# 34. 不预生成完整未来 Plan

Task Plan 只展示：

```text
likely remaining steps
```

但下一真实 operation：

```text
只生成当前一步
```

---

# 35. 第三项：SELL_VEHICLE

Phase 13：

```text
DISCOVERED_NOT_VERIFIED
```

Phase 14 必须继续查 shipped scripts/API。

优先查：

```text
api.cmd.make.sellVehicle
```

或相关 vehicle command。

具体以实际代码为准。

---

# 36. SELL live test

只对：

```text
Phase 14 专门购买的测试车辆
```

执行。

不要出售现有存档原有车辆。

---

# 37. Live 流程

```text
BUY test vehicle
↓
verify new ID
↓
SELL same ID
↓
fresh snapshot
↓
verify ID absent
```

---

# 38. SELL Capability

成功后：

```text
engine_verified = true
risk_class = HIGH
destructive = true
supports_rollback = false
```

必须：

```text
MANUAL
```

---

# 39. REMOVE_VEHICLE_FROM_LINE

优先确认：

```text
setLine(vehicle, invalid/null line?)
```

或者官方实际 API。

不能猜 null/-1 语义。

---

# 40. 独立区分

```text
REMOVE_VEHICLE_FROM_LINE
```

与：

```text
SEND_VEHICLE_TO_DEPOT
```

不能混为一个动作。

---

# 41. SEND_VEHICLE_TO_DEPOT

如果存在明确 API：

单独验证。

未来 AI 卖车可能需要：

```text
remove
↓
send depot
↓
sell
```

但不要假设固定流程。

---

# 42. Vehicle Lifecycle State Machine

Phase 14 建立：

```text
UNKNOWN

UNASSIGNED

ASSIGNED

IN_SERVICE

GOING_TO_DEPOT

IN_DEPOT
```

只映射能够证明的状态。

---

# 43. raw_state 不能直接硬编码含义

当前 snapshot：

```text
raw_state = 1
```

在没有来源验证前：

```text
raw_state = 1
```

只能保留：

```text
RAW
```

不能直接写：

```text
IN_SERVICE
```

---

# 44. 第四项：SET_LINE_STOPS

这是 Phase 14 第二条主线。

开始深挖 TPF2 shipped Lua/API。

目标找到：

```text
line creation/update command
```

能修改：

```text
ordered stop list
```

---

# 45. 必须先确认 Line Stop 数据模型

要求 snapshot 提供：

```text
line_id

ordered stops
```

每个 stop：

```text
station/terminal entity
index
terminal index
```

---

# 46. 保持重复 stop

例如：

```text
A
B
C
B
A
```

必须原样保留。

严禁：

```text
set()
unique()
```

---

# 47. 查找实际 Line API

重点扫描：

```text
api.cmd.make.createLine

api.cmd.make.setLine

api.cmd.make.updateLine

api.cmd.make.setLineStops

api.cmd.make.changeLine
```

以上只是搜索方向。

实际 capability 名称按发现结果决定。

---

# 48. 注意 setLine 已被车辆分配使用

Phase 13 已证明：

```text
api.cmd.make.setLine(vehicle, line, stopIndex)
```

这是车辆 → 线路。

不要把它误认为：

```text
设置线路 Stops
```

---

# 49. Line Entity API 必须单独确认

任何函数都需要：

```text
signature
parameter meaning
shipped-source trace
live probe
```

---

# 50. SET_LINE_STOPS Operation

验证后才加入：

```text
SET_LINE_STOPS
```

参数：

```json
{
  "line_id": 531841,

  "stops": [
    {
      "station_id": 100
    },
    {
      "station_id": 200
    }
  ]
}
```

内部转换实际 command payload。

---

# 51. Stop Mutation 第一阶段只用 existing valid stops

Phase 14 不创建新站。

只允许：

```text
existing station
existing terminal
```

---

# 52. Stop Change Live Test

专用测试线：

```text
A → B → C
```

变成：

```text
A → C
```

或者：

```text
A → B → C → D
```

要求变化可恢复。

---

# 53. Before / After

必须验证：

```text
ordered sequence
```

不是 station count。

---

# 54. SET_LINE_STOPS 风险

设置：

```text
risk_class = MEDIUM
```

默认：

```text
MANUAL
```

---

# 55. Stop Simulation

执行前复用 Phase 10：

```text
simulate_line_stop_change
```

重新计算：

```text
connectivity
components
transfer structure
```

---

# 56. Mutation Preview

Proposal 包含：

```text
before stops

desired stops

topology delta

affected stations

affected lines
```

---

# 57. 第五项：CREATE_LINE

Phase 14 必须认真推进。

目标不是铺轨。

定义：

```text
在已有可用 station/terminal 之间
创建新的 line entity
```

---

# 58. API Discovery

扫描 shipped scripts：

```text
create line
transport line
line component
api.cmd.make.*
```

必须记录具体 source trace。

---

# 59. CREATE_LINE 最小参数

目标：

```json
{
  "transport_mode": "...",

  "stops": [
    ...
  ]
}
```

实际参数依 API 调整。

---

# 60. CREATE_LINE Verification

执行前：

```text
baseline line IDs
```

执行后：

```text
new line IDs
```

要求：

```text
exactly one new line
```

否则：

```text
AMBIGUOUS_NEW_ENTITY
```

---

# 61. 新 line ID 也必须由 fresh snapshot 得到

与 BUY 同原则：

```text
never predict entity IDs
```

---

# 62. CREATE_LINE Goal

成功后增加：

```text
CREATE_LINE_GOAL
```

完成：

```text
new line exists

ordered stops match desired stops
```

---

# 63. CREATE_AND_ASSIGN_EXISTING_VEHICLE Goal

如果 CREATE_LINE + ASSIGN 已验证：

实现：

```text
CREATE_AND_ASSIGN_EXISTING_VEHICLE_GOAL
```

流程：

```text
create line
↓
snapshot
↓
discover line ID
↓
assign existing vehicle
↓
snapshot
↓
verify
```

---

# 64. CREATE_AND_STAFF_LINE Goal

再进一步：

```text
CREATE_LINE
↓
discover line
↓
BUY_VEHICLE
↓
discover vehicle
↓
ASSIGN
↓
verify
```

这是 Phase 14 的 Stretch Goal。

---

# 65. 第六项：调度策略 Discovery

用户最终要求 AI 能：

```text
调整停站和调度策略
```

因此 Phase 14 必须开始确认：

```text
waiting / load / dispatch
```

实际 TPF2 模型。

---

# 66. 调度 Probe

重点查：

```text
line stop settings

vehicle stop behavior

minimum load

full load

maximum waiting

departure rule
```

---

# 67. 不要造 SET_FREQUENCY

只有 API 明确存在：

```text
frequency direct control
```

才能建：

```text
SET_LINE_FREQUENCY
```

---

# 68. 如果 frequency 是结果

若实际：

```text
frequency = fleet + route cycle
```

则把：

```text
frequency
```

定义为：

```text
observed KPI
```

而非直接控制参数。

AI 通过：

```text
增加/减少车辆
```

调整。

---

# 69. 调度 Capability 命名

必须按真实语义命名。

例如如果发现的是：

```text
minimum load percentage
```

就叫：

```text
SET_MINIMUM_LOAD
```

而不是泛化成：

```text
SET_SCHEDULE
```

---

# 70. Parameter Semantic Verification

每一个调度参数至少：

```text
source trace

before value

command

after value

UI cross-check if available
```

---

# 71. 调度操作 risk

默认：

```text
MEDIUM
```

因为会改变运营。

---

# 72. Phase 14 线路控制目标

最终希望 capability matrix 至少达到：

```text
BUY_VEHICLE                 VERIFIED

ASSIGN_VEHICLE_TO_LINE      VERIFIED

SELL_VEHICLE                ideally VERIFIED

SET_LINE_STOPS              VERIFIED

CREATE_LINE                 VERIFIED
```

以及至少一个真实：

```text
scheduling parameter
```

被验证。

---

# 73. Operational Planner

新增：

```text
planning/operations_planner.py
```

不是新的 LLM。

用于根据现有结构化状态产生候选动作。

---

# 74. 增车候选

例如：

```text
long headway
+
compatible existing vehicle template
+
available depot
```

产生：

```text
BUY_AND_ASSIGN_VEHICLE
```

但标：

```text
HEURISTIC
```

---

# 75. 不自动执行 heuristic recommendation

Recommendation：

```text
HEURISTIC
```

Operation capability：

```text
ENGINE_VERIFIED
```

这两个不能混淆。

---

# 76. Planning Option → Executable Task

增加：

```text
materialize_planning_option
```

输入：

```text
planning_option
```

返回：

```text
Task Goal
```

只有底层 operation 都 supported 时才能：

```text
EXECUTABLE
```

---

# 77. 例如“增加一辆车”

Phase 10：

```text
SIMULATE_EXTRA_VEHICLE
```

Phase 14 可以映射：

```text
BUY_AND_ASSIGN_VEHICLE_GOAL
```

前提：

```text
BUY verified
ASSIGN verified
compatible source vehicle exists
compatible depot exists
```

---

# 78. Fleet Selection Helper

新增：

```text
find_vehicle_templates_for_line
```

用于找现有：

```text
same mode
compatible
already running on line
```

车辆作为 clone config template。

---

# 79. 最稳的来源

优先：

```text
target line existing vehicle
```

例如要给 Line A 增车：

```text
选择 Line A 上现有一辆车作为 source_vehicle
```

这样 transport config compatibility 风险最低。

---

# 80. 没有现有车辆时

不要猜。

返回：

```text
NO_VERIFIED_VEHICLE_TEMPLATE
```

直到真正 catalog 支持完成。

---

# 81. Depot Resolution

新增：

```text
find_compatible_depots_for_vehicle
```

必须尽量来自实际数据。

如果只能确认：

```text
source vehicle raw_depot
```

则优先使用该 depot。

---

# 82. 自动扩容线路的最小闭环

用户：

```text
给线路 L 加一辆和现有车辆相同的车
```

执行：

```text
get line fleet
↓
pick existing vehicle template
↓
resolve depot
↓
BUY
↓
fresh snapshot
↓
discover V
↓
ASSIGN V to L
↓
fresh snapshot
↓
verify
```

---

# 83. 增加 Operational Goal

新增：

```text
ADD_ONE_COMPATIBLE_VEHICLE_TO_LINE_GOAL
```

这是比底层：

```text
BUY_AND_ASSIGN
```

更高一级的业务 Goal。

---

# 84. Goal 输入

只需：

```json
{
  "line_id": 531841
}
```

Planner 自动：

```text
选择 source vehicle
选择 depot
```

---

# 85. 必须提供 selection evidence

例如：

```json
{
  "source_vehicle_id": 7656,

  "reason": "Existing vehicle already assigned to target line.",

  "depot_id": 626601
}
```

---

# 86. 不宣称这是“最佳车辆”

只能说：

```text
compatible verified template
```

直到 catalog 与性能决策建立。

---

# 87. 减少线路车辆

如果：

```text
REMOVE
+
SELL
```

都验证成功：

新增：

```text
REMOVE_ONE_VEHICLE_FROM_LINE_GOAL
```

默认不要 sell。

第一目标只是：

```text
remove from service
```

---

# 88. SELL 是独立 Intent

用户明确：

```text
卖掉
```

才触发 SELL Goal。

不要因为“减少线路车辆”自动出售资产。

---

# 89. Task Approval

MEDIUM：

```text
BUY
ASSIGN
SET_LINE_STOPS
CREATE_LINE
```

默认：

```text
MANUAL
```

即使 supports rollback。

---

# 90. HIGH 操作

```text
SELL
DELETE_LINE
```

必须：

```text
explicit approval
```

且永远不能 AUTO_SAFE。

---

# 91. Spending Guard 暂时处理

Phase 13 还没有可靠 purchase price。

所以 Phase 14：

如果 price 仍 UNAVAILABLE：

```text
max_spend guard unavailable
```

不能假装通过。

---

# 92. 两种策略

对于无法验证价格：

```text
BUY operation requires explicit approval
```

并返回：

```text
financial_cost = UNAVAILABLE
```

---

# 93. 等 price source 验证后

再启用：

```text
max_spend
minimum_cash_reserve
```

---

# 94. Company Cash 必须继续读取

即使不能精确预测 purchase cost：

仍记录：

```text
before balance

after balance
```

作为 evidence。

---

# 95. 不能把 balance delta 当 price

继续遵循：

```text
correlation != exact transaction cost
```

---

# 96. Operation Journal Persistent化

Phase 14 应完成 Phase 13 未完全落地部分：

```text
operations.jsonl
tasks.jsonl
```

---

# 97. 重启恢复

Server 启动：

读取：

```text
pending operations
```

状态：

```text
SUBMITTED
EXECUTED
VERIFYING
```

处理：

```text
fresh snapshot
↓
verify
```

---

# 98. 绝不能 server restart 后自动 resend BUY

这是强制测试。

---

# 99. Crash Recovery Test

模拟：

```text
BUY command sent
↓
server dies
↓
game executes
↓
server restart
```

要求：

```text
read snapshot
↓
identify result
↓
mark VERIFIED
```

不能：

```text
再买一辆
```

---

# 100. Async Verification Enhancement

Operation handler 定义：

```text
verification_policy
```

例如：

```text
BUY:
max snapshots = 3

ASSIGN:
max snapshots = 3
```

---

# 101. Verification 结果

区分：

```text
VERIFIED

NOT_YET_OBSERVED

CONFLICT

FAILED
```

---

# 102. 新 Entity Attribution

如果游戏世界同时新增车辆：

不能仅靠：

```text
ID difference
```

以后需要进一步核：

```text
transport config
depot
owner
timestamp/order if available
```

---

# 103. Phase 14 先保持严格策略

如果出现多个候选：

```text
AMBIGUOUS_NEW_ENTITY
```

停止。

不要猜。

---

# 104. Tests 目录

新增：

```text
tests/phase14/
```

至少：

```text
test_capability_states.py

test_operation_handler_registry.py

test_buy_vehicle_controller.py

test_assign_vehicle_controller.py

test_buy_and_assign_goal.py

test_runtime_context.py

test_sell_vehicle.py

test_line_stops.py

test_create_line.py

test_operational_planner.py

test_recovery.py
```

---

# 105. Regression

必须跑完：

```text
Phase 9
Phase 10
Phase 11
Phase 12
Phase 13
```

所有测试。

---

# 106. BUY Controller Test

确认：

```text
propose
validate
execute
verify
```

完整走通。

不允许再通过：

```text
tools/test-phase13-buy-live.py
```

绕过 Controller 才能执行。

---

# 107. ASSIGN Controller Test

同样要求：

```text
MCP
→ Controller
→ Dispatcher
→ TPF2
```

而不是 standalone live script。

---

# 108. Phase 14 最重要 Live Test

# MCP-native BUY_AND_ASSIGN

不是脚本直接发 command。

必须通过正常 MCP API：

```text
create_task
↓
plan_task
↓
approve
↓
continue_task
↓
BUY
↓
continue_task
↓
ASSIGN
↓
COMPLETED
```

---

# 109. 这是 Phase 14 的 P0 验收

如果做不到：

```text
Phase 14 不算完成
```

即使底层 API 已经验证。

---

# 110. Live Evidence 目录

```text
diagnostics/phase14-live/
```

---

# 111. MCP-native buy/assign

```text
buy-and-assign/
    task-created.json
    plan-1.json
    buy-proposal.json
    buy-execution.json
    after-buy.json
    buy-verification.json
    replan.json
    assign-proposal.json
    assign-execution.json
    after-assign.json
    assign-verification.json
    task-completed.json
```

---

# 112. SELL evidence

如果成功：

```text
sell-test-vehicle/
```

必须使用本阶段新买的测试车。

---

# 113. SET_LINE_STOPS evidence

如果成功：

```text
line-stops/
```

必须包含：

```text
before ordered sequence
desired sequence
after sequence
rollback sequence
```

---

# 114. CREATE_LINE evidence

如果成功：

```text
create-line/
```

必须：

```text
before line IDs

command

after line IDs

new line ID

new line stops
```

---

# 115. Scheduling evidence

至少：

```text
scheduling-api-discovery.json
```

如果验证一个参数：

```text
schedule-setting/
```

---

# 116. Phase 14 Capability Matrix

README 必须动态反映实际结果。

例如：

| Capability | Engine | Controller | Task |
|---|---|---|---|
| RENAME_LINE | VERIFIED | YES | YES |
| BUY_VEHICLE | VERIFIED | YES | YES |
| ASSIGN_VEHICLE_TO_LINE | VERIFIED | YES | YES |
| SELL_VEHICLE | ... | ... | ... |
| SET_LINE_STOPS | ... | ... | ... |
| CREATE_LINE | ... | ... | ... |

---

# 117. 禁止状态造假

如果：

```text
Engine = VERIFIED
```

但：

```text
Controller = NO
```

不能统一写：

```text
SUPPORTED
```

---

# 118. Phase 14 最低验收条件

必须至少：

1. 重构 Capability state；
2. OperationController 支持 BUY_VEHICLE；
3. OperationController 支持 ASSIGN_VEHICLE_TO_LINE；
4. 两者通过 normal MCP transport 执行；
5. 两者都有 postcondition verification；
6. TaskOrchestrator 支持 BUY_VEHICLE_GOAL；
7. 支持 ASSIGN_VEHICLE_TO_LINE_GOAL；
8. 支持 BUY_AND_ASSIGN_VEHICLE_GOAL；
9. Step 2 使用 Step 1 fresh snapshot 得到的新 vehicle ID；
10. 每次 continue 最多一个 mutation；
11. MCP-native live task 完整成功；
12. write kill switch 测试结束后恢复 false。

这 12 项是硬条件。

---

# 119. Phase 14 标准验收目标

在最低验收基础上，再完成：

```text
SELL_VEHICLE
```

或者：

```text
SET_LINE_STOPS
```

至少一个新的：

```text
POSTCONDITION_VERIFIED
```

能力。

---

# 120. Phase 14 优秀验收目标

达到：

```text
BUY

ASSIGN

SELL

SET_LINE_STOPS

CREATE_LINE
```

全部：

```text
POSTCONDITION_VERIFIED
```

并至少一个调度参数完成：

```text
ENGINE_VERIFIED
```

---

# 121. Phase 14 最终 Demo A

用户：

```text
给线路 531841 增加一辆和现有车辆同型的车。
```

系统：

```text
读取线路车辆
↓
选择现有车辆作为 config template
↓
识别 depot
↓
生成 Task
↓
BUY
↓
fresh snapshot
↓
发现新 vehicle
↓
ASSIGN
↓
fresh snapshot
↓
验证
↓
COMPLETED
```

---

# 122. Final Demo B

如果 SET_LINE_STOPS 完成：

用户：

```text
把线路 L 的停站从 A-B-C 改成 A-C。
```

系统：

```text
读取当前 stops
↓
simulation
↓
proposal
↓
approval
↓
execute
↓
fresh snapshot
↓
verify ordered stops
```

---

# 123. Final Demo C

如果 CREATE_LINE 完成：

用户：

```text
用现有 A、B、C 三个站建立一条新线路。
```

系统：

```text
validate stations
↓
create line
↓
fresh snapshot
↓
discover new line ID
↓
verify stops
```

---

# 124. Stretch Demo D

如果全部完成：

```text
建立 A-B-C 新线路并给它配一辆和线路 X 同型的车。
```

执行：

```text
CREATE_LINE
↓
snapshot
↓
new line ID
↓
BUY
↓
snapshot
↓
new vehicle ID
↓
ASSIGN
↓
snapshot
↓
COMPLETED
```

这是真正的 multi-entity closed loop。

---

# 125. Phase 14 不做

本阶段暂时不要：

```text
建设轨道

建设道路

建设新车站

terraform

自动桥梁

自动隧道

自动道路 geometry

复杂路径寻路施工

城市规划
```

---

# 126. Phase 15 准备

Phase 14 完成后，下一阶段直接进入：

# Phase 15 — Infrastructure & Station Construction

目标：

```text
选择站点位置

建设 station

规划 road/rail geometry

建设基础设施

创建 line

配置 stops

购买 vehicle

分配 vehicle

形成完整运输线路
```

---

# 127. Phase 14 最终交付

生成：

```text
tpf2-mcp-phase14-line-management.zip
```

包含：

```text
Capability state refactor

Operation handler registry

BUY controller integration

ASSIGN controller integration

vehicle goals

BUY_AND_ASSIGN composite goal

persistent recovery

line API probes

SELL / SET_LINE_STOPS / CREATE_LINE results

unit tests

live MCP evidence

PHASE14_LINE_MANAGEMENT.md
```

---

# 128. 最终原则

Phase 14 不再以：

```text
“找到 API”
```

作为成功。

必须以：

```text
API discovered
↓
engine verified
↓
controller supported
↓
task supported
↓
MCP live verified
```

作为完整 capability。

最终至少真正达到：

```text
AI：
“给这条线路增加一辆车。”

→ MCP 能从正常 task API 完整执行
→ 游戏状态真实变化
→ Fresh Snapshot 验证
→ Task COMPLETED
```

这才算 Phase 13 能力真正进入产品层。