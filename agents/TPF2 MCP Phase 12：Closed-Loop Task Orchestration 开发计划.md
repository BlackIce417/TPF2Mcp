# TPF2 MCP Phase 12：Closed-Loop Task Orchestration

## 0. 当前基础

当前项目已经完成：

```text
Phase 0～8
Runtime / Snapshot / UI / Diagnostics

Phase 9
Network Intelligence

Phase 10
Decision Support / What-If Planning

Phase 11
Controlled Operations
```

Phase 11 已经真实验证：

```text
RENAME_LINE

Proposal
→ Validation
→ Execute
→ Fresh Snapshot
→ POSTCONDITION_VERIFIED
→ Rollback
→ POSTCONDITION_VERIFIED
```

并已经具有：

```text
write kill switch
operation allowlist
snapshot concurrency control
entity-state preconditions
operation_id idempotency
postcondition verification
operation journal
rollback proposal
```

Phase 12 不再只是增加一个新的 MCP tool。

Phase 12 要建立：

# Closed-Loop Task Orchestration

目标是让 MCP 能够安全执行：

```text
一个目标
→ 多个步骤
→ 每步都观察和验证
→ 状态变化后重新规划
```

而不是：

```text
一次生成一串命令
→ 全部直接执行
```

---

# 1. Phase 12 核心目标

建立：

```text
Goal
 ↓
Task Planner
 ↓
Step Proposal
 ↓
Simulation / Validation
 ↓
Controlled Operation
 ↓
Fresh Snapshot
 ↓
Postcondition Verification
 ↓
Task State Update
 ↓
Re-plan / Continue / Stop
```

最终形成：

```text
Observe
→ Reason
→ Act
→ Verify
→ Re-plan
```

但 Phase 12 仍然不是：

```text
unrestricted autonomous gameplay
```

---

# 2. 最重要原则：一次只执行一个步骤

禁止：

```text
plan = [
    operation1,
    operation2,
    operation3,
    operation4
]

for operation in plan:
    execute(operation)
```

必须：

```text
plan step 1
↓
execute
↓
fresh snapshot
↓
verify
↓
re-evaluate task
↓
生成 step 2
```

原因：

TPF2 世界状态在每一步操作后都可能变化。

因此：

```text
future steps are hypotheses
```

而不是固定命令。

---

# 3. 新目录

新增：

```text
mcp_server/src/tpf2_mcp/tasks/
    __init__.py

    models.py
    goals.py
    planner.py
    orchestrator.py
    executor.py
    verifier.py
    policy.py
    journal.py
    recovery.py
```

整体结构：

```text
DecisionSupport
       ↓
TaskPlanner
       ↓
TaskOrchestrator
       ↓
OperationController
       ↓
TPF2
```

必须保持：

```text
TaskOrchestrator
```

和：

```text
OperationController
```

解耦。

---

# 4. Task Model

新增：

```python
Task
```

建议：

```text
task_id
goal_type
goal
created_snapshot_sequence
status
policy
steps
current_step
result
limitations
created_at
updated_at
```

例如：

```json
{
  "task_id": "task-001",

  "goal_type": "RENAME_LINE",

  "goal": {
    "line_id": 11833,
    "desired_name": "Airport Express"
  },

  "created_snapshot_sequence": 20,

  "status": "PLANNING"
}
```

---

# 5. Task 状态机

统一状态：

```text
CREATED

PLANNING

READY

WAITING_FOR_APPROVAL

EXECUTING

VERIFYING

REPLANNING

COMPLETED

PARTIALLY_COMPLETED

BLOCKED

FAILED

CANCELLED
```

禁止用：

```text
success = true/false
```

代替完整状态。

---

# 6. TaskStep Model

每一步：

```python
TaskStep
```

包含：

```text
step_id
sequence
step_type
status

reason
operation_type
proposal_id
operation_id

snapshot_before
snapshot_after

expected_effect
observed_effect

verification
```

例如：

```json
{
  "step_id": "step-001",

  "sequence": 1,

  "step_type": "GAME_OPERATION",

  "operation_type": "RENAME_LINE",

  "status": "POSTCONDITION_VERIFIED"
}
```

---

# 7. Phase 12.1：Goal Registry

建立：

```text
GoalRegistry
```

第一阶段不要允许任意自然语言直接映射到任意 Lua 操作。

使用明确 Goal Type：

```text
RENAME_LINE_GOAL

RESTORE_LINE_NAME_GOAL

INSPECT_NETWORK_GOAL

IMPROVE_CONNECTIVITY_GOAL

REDUCE_STRUCTURAL_ISOLATION_GOAL
```

其中后两个初期允许：

```text
PLAN_ONLY
```

不要求一定执行。

---

# 8. Goal Capability

每个 Goal 必须声明：

```text
PLAN_ONLY
EXECUTABLE
PARTIALLY_EXECUTABLE
```

例如：

```json
{
  "goal_type": "RENAME_LINE_GOAL",
  "capability": "EXECUTABLE"
}
```

而：

```json
{
  "goal_type": "IMPROVE_CONNECTIVITY_GOAL",
  "capability": "PLAN_ONLY",
  "reason": "No verified infrastructure construction operation exists."
}
```

---

# 9. 不允许 Planner 虚构执行能力

Phase 10 可能生成：

```text
SIMULATE_COMPONENT_CONNECTION
```

但如果 Phase 11/12 没有：

```text
BUILD_CONNECTION
```

则 TaskPlanner 必须返回：

```text
PLAN_ONLY
```

禁止：

```text
planning option
→ automatically invent game command
```

---

# 10. TaskPlanner

新增：

```text
TaskPlanner
```

输入：

```text
Goal
+
current NetworkIntelligenceIndex
+
DecisionSupport
+
OperationCapabilities
```

输出：

```text
TaskPlan
```

---

# 11. TaskPlan

建议：

```json
{
  "task_id": "task-x",

  "goal_status": "EXECUTABLE",

  "steps": [
    {
      "type": "PROPOSE_OPERATION",
      "operation_type": "RENAME_LINE"
    }
  ],

  "limitations": []
}
```

注意：

这里只生成：

```text
logical steps
```

不要预生成：

```text
future operation_id
```

---

# 12. Planner 必须重新读取 Capability Registry

不能假设：

```text
RENAME_LINE 永远存在
```

每次计划都读取：

```text
OperationCapabilityRegistry
```

因为后续不同安装环境可能：

```text
write disabled
operation unavailable
version incompatible
```

---

# 13. Phase 12.2：TaskOrchestrator

建立：

```python
class TaskOrchestrator:
    create_task()
    plan()
    next_step()
    approve_step()
    execute_step()
    verify_step()
    replan()
    cancel()
```

---

# 14. Orchestrator 不能直接写游戏

严格：

```text
TaskOrchestrator
      ↓
OperationController
```

禁止：

```text
TaskOrchestrator
      ↓
Bridge
```

---

# 15. 每一步必须绑定 Snapshot

Task 本身：

```text
created_snapshot_sequence
```

Step：

```text
planned_snapshot_sequence
```

Operation：

```text
snapshot_sequence
```

都必须记录。

---

# 16. Snapshot Change 策略

Phase 11：

```text
snapshot changed
→ stale proposal
```

Phase 12 更进一步。

如果 Task 在执行下一步骤前发现：

```text
current snapshot != planned snapshot
```

不能简单失败整个 Task。

应该：

```text
mark current plan stale
↓
REPLANNING
↓
重新读取状态
↓
重新判断 goal 是否仍需完成
```

---

# 17. Goal Satisfaction Check

每种 Goal 定义：

```text
is_goal_satisfied(snapshot)
```

例如：

```text
RENAME_LINE_GOAL
```

检查：

```text
line.name == desired_name
```

如果外部操作已经完成：

```text
Task → COMPLETED
```

无需再执行。

---

# 18. 不重复做已经完成的事

例如：

Task：

```text
Rename Line 11833 to Airport Express
```

但执行前发现：

```text
Line 11833 already named Airport Express
```

则：

```text
COMPLETED
```

并：

```text
executed_operations = 0
```

---

# 19. Step Approval Policy

Phase 12 建立：

```text
ExecutionPolicy
```

至少：

```text
MANUAL
AUTO_SAFE
PLAN_ONLY
```

---

# 20. MANUAL

默认：

```text
MANUAL
```

每一个 write step：

```text
WAITING_FOR_APPROVAL
```

需要显式执行。

---

# 21. AUTO_SAFE

只允许：

```text
non-destructive
verified
rollback_supported
operation allowlisted
```

操作自动执行。

目前实际上：

```text
RENAME_LINE
```

可以作为唯一候选。

---

# 22. PLAN_ONLY

永远不执行。

只返回：

```text
task plan
simulation
limitations
```

---

# 23. Policy Guard

新增：

```text
tasks/policy.py
```

例如：

```python
can_auto_execute(operation_capability)
```

要求：

```text
verified == true
destructive == false
supports_rollback == true
```

否则：

```text
WAITING_FOR_APPROVAL
```

---

# 24. Destructive Operation 永远不能 AUTO_SAFE

即使后续支持：

```text
SELL_VEHICLE
DELETE_LINE
BULLDOZE
```

Phase 12 必须规定：

```text
destructive == true
→ MANUAL only
```

---

# 25. Phase 12.3：Closed Loop

完整执行：

```text
create_task
↓
read fresh snapshot
↓
check goal
↓
plan next logical step
↓
proposal
↓
validate
↓
policy check
↓
execute
↓
fresh snapshot
↓
verify
↓
check goal again
↓
COMPLETED / REPLAN
```

---

# 26. 最大循环次数

必须防止死循环。

Task 配置：

```text
max_steps
```

默认：

```text
5
```

Phase 12 最大：

```text
10
```

超过：

```text
BLOCKED
```

reason：

```text
MAX_STEPS_EXCEEDED
```

---

# 27. 最大 Re-plan 次数

加入：

```text
max_replans = 3
```

超过：

```text
BLOCKED
```

---

# 28. No-Progress Detection

如果连续两次：

```text
snapshot semantic state unchanged
```

并且 goal 未完成：

```text
NO_PROGRESS
```

停止 Task。

不要无限重试。

---

# 29. Semantic Progress

不要只检查：

```text
snapshot_sequence
```

因为 sequence 可能变化但目标无进展。

应该比较：

```text
goal-relevant fields
```

例如 Rename：

```text
line.name
```

---

# 30. Phase 12.4：Recovery

新增：

```text
TaskRecovery
```

只处理：

```text
known safe recovery
```

例如：

```text
STALE_PROPOSAL
→ replan
```

```text
ALREADY_EXECUTED
→ verify current snapshot
```

```text
COMMAND_TIMEOUT
→ DO NOT immediately retry
→ refresh snapshot
→ determine whether effect occurred
```

---

# 31. COMMAND_TIMEOUT 尤其重要

不能：

```text
timeout
→ resend
```

因为 Phase 11 已经说明：

```text
command may have executed
```

正确：

```text
timeout
↓
read fresh snapshot
↓
check postcondition
```

如果已完成：

```text
POSTCONDITION_VERIFIED
```

如果未完成：

再决定是否：

```text
retry with same operation_id
```

---

# 32. Phase 12.5：Task Journal

建立：

```text
TaskJournal
```

记录：

```text
task
plans
steps
operations
snapshots sequences
replans
verification
recovery actions
final result
```

---

# 33. Journal 不保存完整世界副本

保存：

```text
snapshot_sequence
goal-relevant evidence
operation diff
```

即可。

---

# 34. Task Timeline

返回：

```json
{
  "timeline": [
    {
      "event": "TASK_CREATED"
    },
    {
      "event": "PLAN_CREATED"
    },
    {
      "event": "OPERATION_PROPOSED"
    },
    {
      "event": "OPERATION_EXECUTED"
    },
    {
      "event": "POSTCONDITION_VERIFIED"
    },
    {
      "event": "TASK_COMPLETED"
    }
  ]
}
```

---

# 35. Phase 12.6：增加第二个真实 Write Capability

Phase 12 除编排之外，应继续 Runtime Probe。

优先：

```text
RENAME_STATION
```

原因：

现有 Phase 11 已发现：

```text
game.interface.setName(id, name)
```

而：

```text
RENAME_STATION
```

已经是：

```text
DISCOVERED_NOT_VERIFIED
```

---

# 36. 验证 RENAME_STATION

在专用测试存档：

```text
station old name
↓
rename
↓
fresh snapshot
↓
verify
↓
rollback
↓
fresh snapshot
↓
verify
```

成功后：

```text
POSTCONDITION_VERIFIED
```

---

# 37. 不要因为 setName 可用于 Line 就假设 Station 一定可用

必须 Live Verify。

如果：

```text
game.interface.setName(station_id, ...)
```

失败：

保持：

```text
DISCOVERED_NOT_VERIFIED
```

---

# 38. 第三个 Capability Probe

在时间允许情况下探测：

```text
vehicle name
```

如果 TPF2 entity 支持 rename：

```text
RENAME_VEHICLE
```

可以成为 Phase 12 的第三个低风险操作。

仍然要求：

```text
Live verify
rollback
```

---

# 39. 暂时不要优先做 Buy/Sell Vehicle

Phase 12 的重点是：

```text
闭环控制
```

而不是 write API 数量。

因此优先：

```text
RENAME_LINE
RENAME_STATION
RENAME_VEHICLE
```

这三类可逆操作验证 orchestration。

---

# 40. Phase 12.7：Composite Task

在至少两个 rename capability 可用后，加入：

```text
MULTI_RENAME_GOAL
```

例如：

```json
{
  "goal_type": "MULTI_RENAME_GOAL",

  "targets": [
    {
      "type": "LINE",
      "id": 11833,
      "name": "Airport Express"
    },
    {
      "type": "STATION",
      "id": 123,
      "name": "Airport Central"
    }
  ]
}
```

用于验证真正：

```text
multi-step closed loop
```

---

# 41. Composite Task 必须逐步执行

错误：

```text
rename line
rename station
send both
```

正确：

```text
rename line
↓
snapshot verify
↓
replan
↓
rename station
↓
snapshot verify
```

---

# 42. Step Failure

如果：

```text
Step 1 success
Step 2 fail
```

Task 状态：

```text
PARTIALLY_COMPLETED
```

不能自动说：

```text
FAILED
```

因为游戏已经发生部分改变。

---

# 43. Compensation

如果 Task policy：

```text
rollback_on_failure = true
```

可以：

```text
generate rollback proposal
```

但不能悄悄 rollback。

MANUAL 模式：

```text
WAITING_FOR_ROLLBACK_APPROVAL
```

---

# 44. AUTO_SAFE Compensation

只有：

```text
original operation
+
rollback operation
```

都：

```text
verified
non-destructive
rollback-supported
```

才允许自动 compensation。

---

# 45. Phase 12.8：Goal-Oriented Planning

现在 Phase 10 已经支持：

```text
detect_network_problems
get_planning_options
simulate scenarios
```

Phase 12 要建立：

```text
create_network_improvement_task
```

但第一阶段：

```text
PLAN_ONLY
```

---

# 46. 示例

用户目标：

```text
改善当前网络连通性
```

系统：

```text
Network Intelligence
↓
detect isolated component
↓
DecisionSupport
↓
simulate candidate connection
```

如果没有：

```text
BUILD_CONNECTION
```

能力：

```json
{
  "task_status": "BLOCKED",

  "planning_status": "PLAN_AVAILABLE",

  "execution_status": "NOT_EXECUTABLE",

  "reason": "No verified construction operation."
}
```

---

# 47. BLOCKED 不代表失败

需要区分：

```text
FAILED
```

和：

```text
BLOCKED
```

BLOCKED 表示：

```text
有合理计划
但当前 MCP 没有可信执行能力
```

---

# 48. Phase 12.9：Explainability

新增：

```text
explain_task
```

返回：

```text
goal
current state
why current step exists
why it is executable/not executable
expected effect
actual effect
remaining work
```

---

# 49. 不输出内部推理

这里只输出：

```text
decision evidence
```

例如：

```text
Line 11833 currently has name X.
Goal requires Y.
RENAME_LINE is POSTCONDITION_VERIFIED.
Therefore the next permitted operation is RENAME_LINE.
```

---

# 50. MCP Tool 清单

新增：

```text
get_task_capabilities

create_task

plan_task

get_task

list_tasks

get_next_task_step

approve_task_step

execute_task_step

continue_task

cancel_task

explain_task
```

---

# 51. continue_task

这是 Phase 12 的旗舰接口。

但必须严格受：

```text
ExecutionPolicy
```

控制。

逻辑：

```text
check task
↓
fresh snapshot
↓
check goal
↓
if satisfied → completed
↓
plan one next step
↓
if PLAN_ONLY → return plan
↓
if approval required → WAITING_FOR_APPROVAL
↓
if AUTO_SAFE → execute ONE step
↓
verify
↓
return
```

注意：

一次 `continue_task`：

```text
最多执行一个 write operation
```

---

# 52. 禁止 continue_task 内部无限循环

即使：

```text
AUTO_SAFE
```

也必须：

```text
one invocation
=
at most one game mutation
```

这样 MCP client 能够看到中间状态。

---

# 53. MCP Resource：Task State

可以增加 resource：

```text
tpf2://tasks/{task_id}
```

返回：

```text
task state
timeline
next action
```

---

# 54. Task Capability API

```text
get_task_capabilities
```

例如：

```json
{
  "goals": [
    {
      "goal_type": "RENAME_LINE_GOAL",
      "status": "EXECUTABLE"
    },
    {
      "goal_type": "IMPROVE_CONNECTIVITY_GOAL",
      "status": "PLAN_ONLY"
    }
  ]
}
```

---

# 55. Phase 12.10：Operation Capability Discovery 改进

Phase 11 registry 是静态 Python 数据。

Phase 12 建议逐步变成：

```text
static known capabilities
+
runtime capability report
```

---

# 56. Capability Fingerprint

每个 capability 记录：

```text
game version
mod version
API source
live verification date
verification snapshot
```

例如：

```json
{
  "operation_type": "RENAME_LINE",

  "verification": {
    "game_version": "...",
    "verified_at": "...",
    "method": "game.interface.setName"
  }
}
```

---

# 57. Version Drift

如果发现：

```text
TPF2 game version changed
```

旧 write capability 不应该无条件保持：

```text
VERIFIED
```

建议：

```text
VERIFIED_FOR_VERSION
```

---

# 58. Capability Compatibility

状态：

```text
VERIFIED

VERIFIED_FOR_VERSION

DISCOVERED_NOT_VERIFIED

UNAVAILABLE

VERSION_MISMATCH
```

---

# 59. Version mismatch 时 fail closed

对于 write：

```text
VERSION_MISMATCH
→ refuse execution
```

read path 可以继续。

---

# 60. Phase 12.11：Task Safety Budget

为 Task 增加：

```text
max_write_operations
```

默认：

```text
1
```

Composite Task：

```text
明确提高
```

最大：

```text
5
```

---

# 61. Mutation Budget

可以进一步区分：

```text
rename_count
vehicle_change_count
construction_count
destructive_count
```

Phase 12：

```text
construction_count = 0
destructive_count = 0
```

---

# 62. Task Scope

Task 创建时冻结：

```text
allowed_entity_types
allowed_entity_ids
allowed_operation_types
```

例如：

```json
{
  "scope": {
    "line_ids": [11833],
    "operation_types": [
      "RENAME_LINE"
    ]
  }
}
```

Orchestrator 禁止越界。

---

# 63. 这是防止 Planner Scope Creep

例如用户只要求：

```text
把线路改名
```

Planner 不应该顺手：

```text
改站名
买车
改线路
```

---

# 64. Phase 12.12：Task Preview

新增：

```text
preview_task
```

返回：

```text
goal
current state
likely steps
write budget
required approvals
known limitations
```

绝不执行。

---

# 65. Phase 12 Live Test A

Single-step：

```text
RENAME_LINE_GOAL
```

流程：

```text
create task
↓
plan
↓
WAITING_FOR_APPROVAL
↓
approve
↓
continue
↓
POSTCONDITION_VERIFIED
↓
COMPLETED
```

---

# 66. Live Test B

AUTO_SAFE：

```text
RENAME_LINE_GOAL
policy = AUTO_SAFE
```

一次：

```text
continue_task
```

允许执行一个 rename。

新 snapshot 后：

```text
COMPLETED
```

---

# 67. Live Test C

Externally satisfied goal：

创建 Task：

```text
Line A → B
```

然后人工在游戏里先改成 B。

`continue_task`：

```text
fresh snapshot
↓
goal already satisfied
↓
COMPLETED
```

且：

```text
writes = 0
```

---

# 68. Live Test D

Stale Task：

```text
plan at snapshot N
```

状态改变：

```text
snapshot N+1
```

要求：

```text
REPLANNING
```

而不是直接执行旧 proposal。

---

# 69. Live Test E

Duplicate continue：

客户端因为超时重复：

```text
continue_task
```

不能重复执行已经完成的操作。

---

# 70. Live Test F

Composite task。

如果 RENAME_STATION 验证成功：

```text
rename line
+
rename station
```

验证：

```text
Step 1
snapshot
Step 2
snapshot
COMPLETED
```

---

# 71. Live Test G

Partial failure。

构造：

```text
Step 1 success
Step 2 target unavailable
```

结果：

```text
PARTIALLY_COMPLETED
```

不得隐藏 Step 1 已产生的游戏变化。

---

# 72. Unit Tests

新增：

```text
tests/phase12/

test_task_models.py
test_goal_registry.py
test_task_planner.py
test_orchestrator.py
test_task_policy.py
test_task_replanning.py
test_task_recovery.py
test_task_journal.py
test_composite_task.py
```

---

# 73. 必测：One Mutation Per Continue

测试：

```text
continue_task()
```

内部：

```text
OperationController.execute
```

调用次数：

```text
<= 1
```

---

# 74. 必测：Goal Already Satisfied

确认：

```text
write count == 0
```

---

# 75. 必测：Re-plan

snapshot 变化：

```text
旧 step 不得执行
```

---

# 76. 必测：Scope Boundary

Task 只允许：

```text
line 11833
```

Planner 尝试操作：

```text
line 11834
```

必须：

```text
TASK_SCOPE_VIOLATION
```

---

# 77. 必测：Write Budget

```text
max_write_operations = 1
```

已经写一次：

第二次：

```text
WRITE_BUDGET_EXCEEDED
```

---

# 78. 必测：AUTO_SAFE

capability：

```text
destructive = true
```

即使 policy：

```text
AUTO_SAFE
```

仍：

```text
WAITING_FOR_APPROVAL
```

---

# 79. Phase 12 Evidence

新增：

```text
diagnostics/phase12-live/
```

至少：

```text
manifest.json

task-capabilities.json

rename-line-task/
    task-created.json
    plan.json
    proposal.json
    execution.json
    after.json
    task-completed.json

stale-task/
    before.json
    stale-plan.json
    replan.json

duplicate-continue.json

goal-already-satisfied.json

write-budget.json

phase12-live-mcp-session.jsonl
```

---

# 80. 如果 RENAME_STATION 验证成功

增加：

```text
rename-station-task/
```

以及：

```text
composite-task/
```

---

# 81. Documentation

新增：

```text
docs/PHASE12_CLOSED_LOOP_TASKS.md
```

必须解释：

```text
Goal
Task
TaskPlan
TaskStep
ExecutionPolicy
Scope
Write Budget
Replanning
Recovery
Partial Completion
```

---

# 82. README 更新

增加：

```text
Phase 12 Closed-Loop Tasks
```

明确：

```text
Phase 12 is task orchestration,
not unrestricted autonomous gameplay.
```

---

# 83. Phase 12 最终交付物

生成：

```text
tpf2-mcp-phase12-closed-loop-tasks.zip
```

包含：

```text
完整源码

Task system

TaskPlanner

TaskOrchestrator

ExecutionPolicy

TaskJournal

Recovery logic

MCP tools

Phase 12 tests

Live evidence

PHASE12_CLOSED_LOOP_TASKS.md
```

---

# 84. Phase 12 验收标准

必须满足：

- 存在明确 Task Model；
- 存在 Goal Registry；
- goal 能判断是否已经满足；
- TaskPlanner 不会虚构不存在的 operation；
- TaskOrchestrator 不直接调用 bridge 写接口；
- 所有写操作继续走 OperationController；
- 一个 continue 调用最多一个 mutation；
- step 完成后一定读取新 snapshot；
- snapshot 改变后旧 plan 会失效并 re-plan；
- stale proposal 不会直接执行；
- timeout 后优先验证，不直接重复写；
- 有 max_steps；
- 有 max_replans；
- 有 no-progress detection；
- 有 task scope；
- 有 write budget；
- AUTO_SAFE 仅允许 verified/non-destructive/rollback-supported operation；
- destructive operation 不允许 AUTO_SAFE；
- PLAN_ONLY goal 可以正常存在；
- task 可以进入 BLOCKED；
- partial execution 可以进入 PARTIALLY_COMPLETED；
- Task Journal 可重建完整执行时间线；
- RENAME_LINE 完整 task live test 成功；
- 至少尝试验证 RENAME_STATION；
- 所有 live writes 都在专用测试存档完成；
- 最终产出：

```text
tpf2-mcp-phase12-closed-loop-tasks.zip
```

---

# 85. Phase 12 最小交付要求

如果新的 write API 仍然不好找，Phase 12 仍可验收。

最低只要求：

```text
RENAME_LINE
```

但必须证明：

```text
Goal
→ Task
→ Planner
→ Approval
→ OperationController
→ Execute
→ Snapshot
→ Verification
→ Goal Satisfaction
→ Completed
```

也就是说：

Phase 12 的评价标准不是：

```text
支持多少游戏操作
```

而是：

```text
闭环任务系统是否真正可靠
```

---

# 86. Phase 12 不要做的事情

禁止提前实现：

```text
无限自主运行

后台无限循环

AI 自己决定持续优化整个地图

自动拆除基础设施

自动花费大量资金

自动创建复杂铁路网络

自动连续买卖车辆

无审批执行 destructive operations
```

---

# 87. Phase 12 之后的路线

完成后架构应为：

```text
TPF2
  ↑
Controlled Operations
  ↑
Task Orchestrator
  ↑
Decision Support
  ↑
Network Intelligence
  ↑
Snapshot
```

形成：

```text
Observe
↓
Understand
↓
Plan
↓
Execute one controlled step
↓
Observe
↓
Verify
↓
Re-plan
```

之后才适合进入：

```text
Phase 13
Operational Expansion
```

用于真正扩展：

```text
vehicle management
line management
depot operations
```

再往后：

```text
Phase 14
Construction Planning / Geometry

Phase 15
Autonomous Network Operator
```

不要在 Phase 12 提前完成这些内容。