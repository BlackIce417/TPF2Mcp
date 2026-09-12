# TPF2 MCP Phase 11：Controlled Operations / 受控执行层

## 0. Phase 11 目标

当前项目已经完成：

```text
Phase 0～8
Runtime / Diagnostics / UI / Dynamic State

Phase 9
Network Intelligence

Phase 10
Decision Support / What-If Planning
```

Phase 10 已经能够完成：

```text
发现问题
↓
分析影响
↓
生成 Planning Option
↓
构造 Virtual Scenario
↓
模拟结构变化
↓
比较方案
```

但是：

```text
Scenario != Game Operation
```

Phase 11 的任务是建立第一个真正能够影响 TPF2 游戏状态的：

```text
Controlled Operations Layer
```

即：

```text
Planning Layer
      ↓
Operation Proposal
      ↓
Precondition Validation
      ↓
Explicit Execution
      ↓
Postcondition Verification
      ↓
Operation Result
```

---

# 1. Phase 11 的核心原则

Phase 11 不允许直接变成：

```text
LLM → game.interface.*
```

必须增加完整的执行控制层：

```text
MCP Tool
   ↓
OperationController
   ↓
Validation
   ↓
Command Envelope
   ↓
Bridge
   ↓
Lua Runtime
   ↓
TPF2 Engine
   ↓
New Snapshot
   ↓
Verification
```

即所有写操作都必须满足：

```text
PROPOSE
→ VALIDATE
→ EXECUTE
→ VERIFY
```

禁止：

```text
调用 MCP tool
→ 直接改游戏
```

---

# 2. Phase 11 安全边界

所有操作分为三级：

```text
READ_ONLY
SAFE_WRITE
DESTRUCTIVE_WRITE
```

Phase 11 首期只实现：

```text
SAFE_WRITE
```

暂时不要支持高破坏性操作。

---

# 3. Phase 11 首批允许操作

第一批控制能力建议限制为：

```text
rename_line
rename_station

set_line_vehicle_replacement
set_vehicle_maintenance_level

change_line_frequency_related_setting
```

但具体能够操作什么，必须根据 TPF2 API 实际验证结果决定。

不要为了满足计划而虚构 API。

更现实的策略是：

```text
先 Runtime Probe
↓
确认 game.interface 可写 API
↓
只开放已验证操作
```

---

# 4. Phase 11.1：Write API Discovery

Phase 11 的第一步不是直接写 MCP tool。

首先建立：

```text
write API discovery
```

新增 Lua：

```text
collectors/
    write_api_probe.lua
```

或者：

```text
operations/
    api_probe.lua
```

探测重点：

```text
game.interface
api.cmd
api.cmd.make.*
api.cmd.sendCommand
```

重点查明：

```text
哪些操作可以通过 documented command API 执行
```

---

# 5. 不允许直接调用未知内部接口

任何操作 API 必须记录：

```json
{
  "operation": "RENAME_LINE",

  "api": "api.cmd.make...",

  "availability": "VERIFIED",

  "tested": true,

  "engine_effect": "LINE_NAME_CHANGED"
}
```

如果只发现函数名但没有 Live Test：

```json
{
  "availability": "DISCOVERED_NOT_VERIFIED"
}
```

这种 API：

```text
禁止暴露为 write MCP tool
```

---

# 6. Write Capability Registry

新增：

```text
tpf2_mcp/operations/
    capability_registry.py
```

结构：

```python
OperationCapability
```

建议字段：

```text
operation_type
available
verified
destructive
requires_confirmation
supports_rollback
source
limitations
```

例如：

```json
{
  "operation_type": "RENAME_LINE",

  "available": true,

  "verified": true,

  "destructive": false,

  "requires_confirmation": true,

  "supports_rollback": true,

  "source_status": "ENGINE_VERIFIED"
}
```

新增 MCP：

```text
get_operation_capabilities
```

---

# 7. Operation Model

建立统一：

```text
GameOperation
```

建议：

```python
@dataclass
class GameOperation:
    operation_id: str
    operation_type: str
    snapshot_sequence: int
    target: dict
    parameters: dict
    expected_effect: dict
```

例如：

```json
{
  "operation_id": "op-001",

  "operation_type": "RENAME_LINE",

  "snapshot_sequence": 77,

  "target": {
    "entity_type": "LINE",
    "entity_id": 11833
  },

  "parameters": {
    "name": "Lugano Express"
  }
}
```

---

# 8. Operation Proposal

任何写操作先生成：

```text
OperationProposal
```

而不是直接执行。

新增：

```text
propose_operation
```

例如：

```json
{
  "operation_type": "RENAME_LINE",

  "target": {
    "line_id": 11833
  },

  "parameters": {
    "name": "Lugano Express"
  }
}
```

返回：

```json
{
  "proposal_id": "proposal-abc",

  "snapshot_sequence": 77,

  "operation": {},

  "validation": {},

  "expected_effect": {},

  "requires_execution": true
}
```

注意：

```text
propose_operation
```

本身绝不能修改游戏。

---

# 9. Preconditions

每一个 operation 必须定义：

```text
preconditions
```

例如 Rename Line：

```text
line exists
line id matches snapshot
new name valid
operation capability verified
snapshot not stale
```

车辆相关操作则可能包括：

```text
vehicle exists
vehicle belongs to player
vehicle type compatible
line exists
```

---

# 10. OperationValidator

新增：

```text
operations/
    validator.py
```

统一入口：

```text
validate_operation
```

结果：

```json
{
  "valid": true,

  "checks": [
    {
      "check": "ENTITY_EXISTS",
      "status": "PASS"
    },
    {
      "check": "SNAPSHOT_CURRENT",
      "status": "PASS"
    },
    {
      "check": "CAPABILITY_VERIFIED",
      "status": "PASS"
    }
  ]
}
```

失败时：

```text
禁止下发 Lua command
```

---

# 11. Snapshot Concurrency Control

这是 Phase 11 必须完成的关键机制。

所有 operation 必须带：

```text
expected_snapshot_sequence
```

例如：

```text
expected_snapshot_sequence = 77
```

执行之前实际 bridge：

```text
snapshot_sequence = 78
```

则：

```text
STALE_OPERATION
```

禁止执行。

这样防止：

```text
LLM 根据旧状态做出的操作
```

作用到新的游戏状态。

---

# 12. Entity Preconditions

进一步加入：

```text
expected entity state
```

例如：

```json
{
  "line_id": 11833,

  "expected": {
    "name": "Line 4"
  },

  "set": {
    "name": "Lugano Express"
  }
}
```

如果执行时：

```text
name != Line 4
```

返回：

```text
PRECONDITION_CHANGED
```

---

# 13. Operation Command Envelope

Python 不得直接生成任意 Lua。

必须发送结构化：

```text
OperationCommand
```

例如：

```json
{
  "protocol_version": 1,

  "operation_id": "op-001",

  "type": "RENAME_LINE",

  "target": {
    "line_id": 11833
  },

  "parameters": {
    "name": "Lugano Express"
  }
}
```

Lua 端只能：

```text
match known operation type
```

禁止：

```text
eval arbitrary Lua
execute arbitrary command
```

---

# 14. Lua Operation Dispatcher

新增：

```text
tpf2_mod/res/scripts/tpf2_mcp/operations/
```

结构建议：

```text
operations/
    dispatcher.lua
    validator.lua

    rename_line.lua
    rename_station.lua
    vehicle.lua
    line.lua
```

入口：

```lua
operations.dispatch(command)
```

只接受 allowlist：

```text
RENAME_LINE
RENAME_STATION
...
```

未知类型：

```text
UNSUPPORTED_OPERATION
```

---

# 15. Write Bridge

当前 bridge 主要围绕 snapshot/request-response。

Phase 11 增加：

```text
operations/
```

Bridge 文件建议：

```text
commands/
    op-xxxxx.request.json

responses/
    op-xxxxx.response.json
```

或者沿用现有 request/response，但必须增加：

```text
operation_id
```

和：

```text
idempotency_key
```

---

# 16. Idempotency

Phase 11 必须解决重复执行。

例如：

```text
MCP 超时
```

Python 不知道：

```text
command executed?
```

此时不能再次：

```text
BUY_VEHICLE
```

因此所有写请求必须：

```text
operation_id
```

唯一。

Lua 保存最近已执行 operation：

```text
executed_operation_ids
```

再次收到同 ID：

```json
{
  "status": "ALREADY_EXECUTED"
}
```

禁止第二次执行。

---

# 17. Operation Lifecycle

统一状态：

```text
PROPOSED
VALIDATED
REJECTED
SUBMITTED
ACCEPTED
EXECUTED
VERIFIED
FAILED
PARTIALLY_VERIFIED
STALE
```

生命周期：

```text
PROPOSED
   ↓
VALIDATED
   ↓
SUBMITTED
   ↓
EXECUTED
   ↓
VERIFIED
```

异常：

```text
VALIDATION_FAILED
EXECUTION_FAILED
VERIFICATION_FAILED
```

---

# 18. Execution Result

Lua 返回：

```json
{
  "operation_id": "op-001",

  "accepted": true,

  "engine_command_sent": true
}
```

注意：

```text
engine_command_sent
```

不等于：

```text
VERIFIED
```

真正成功必须等新 Snapshot。

---

# 19. Phase 11 最重要机制：Postcondition Verification

写命令完成后：

```text
重新读取 Snapshot
```

然后确认：

```text
实际状态 == 期望状态
```

例如：

```text
Rename Line

before:
Line 11833 = Line 4

operation:
name = Lugano Express

after:
Line 11833 = Lugano Express
```

最终：

```json
{
  "execution_status": "VERIFIED",

  "before_snapshot_sequence": 77,

  "after_snapshot_sequence": 78,

  "observed_change": {
    "name": {
      "before": "Line 4",
      "after": "Lugano Express"
    }
  }
}
```

---

# 20. 不使用 command response 作为事实来源

必须遵循：

```text
Command ACK
!=
Game State
```

即使 Lua：

```text
api.cmd.sendCommand(...)
```

成功返回，也不能直接认为操作完成。

唯一事实来源仍然应该是：

```text
下一次 Snapshot
```

---

# 21. Operation Diff

新增：

```text
operations/
    diff.py
```

输出：

```text
Before
After
Delta
```

例如：

```json
{
  "entity": {
    "type": "LINE",
    "id": 11833
  },

  "changes": {
    "name": {
      "before": "Line 4",
      "after": "Lugano Express"
    }
  }
}
```

同时检测：

```text
unexpected changes
```

---

# 22. Unexpected Side Effects

如果计划：

```text
RENAME_LINE
```

但 snapshot 发现：

```text
vehicle_count changed
```

不要立刻判定 rename 导致。

记录：

```json
{
  "unexpected_snapshot_changes": []
}
```

并声明：

```text
correlation only
```

---

# 23. Rollback Model

Phase 11 只为可以可靠反向操作的命令支持 rollback。

例如：

```text
RENAME_LINE
```

可以记录：

```text
old_name
```

从而构造：

```text
rollback operation
```

新增：

```text
create_rollback_operation
```

但：

```text
rollback != database transaction
```

只表示：

```text
生成反向操作
```

---

# 24. 暂不支持真正事务

TPF2 本身不是数据库。

不要实现假的：

```text
BEGIN TRANSACTION
COMMIT
ROLLBACK
```

Phase 11 使用：

```text
best-effort compensating operation
```

---

# 25. Dry Run

所有操作都必须支持：

```text
dry_run
```

例如：

```text
execute_operation(
    proposal_id,
    dry_run=true
)
```

返回：

```text
validation
expected mutation
affected entity
```

但：

```text
不写游戏
```

这可以直接复用 Phase 10 what-if。

---

# 26. Phase 10 与 Phase 11 联动

例如用户：

```text
这条线路间隔太长，怎么办？
```

Phase 10：

```text
detect problem
↓
simulate candidate
```

Phase 11：

```text
candidate
↓
operation proposal
```

不能：

```text
recommendation
↓
direct execution
```

---

# 27. Planning → Operation Conversion

新增：

```text
operation_from_planning_option
```

但必须明确：

只有存在 VERIFIED write capability 的 planning option 才能转换。

例如：

```text
SIMULATE_EXTRA_VEHICLE
```

只有发现实际：

```text
ADD_VEHICLE
```

能力并完成 Live Verification 后，才能转换。

否则：

```json
{
  "status": "NOT_EXECUTABLE",

  "reason": "No verified game operation exists for this planning option."
}
```

---

# 28. 第一阶段优先实现“可逆、小影响”操作

实际 API Probe 后，优先级：

## Priority A

```text
rename_line
rename_station
```

理由：

```text
易观察
易验证
易回滚
副作用低
```

## Priority B

```text
line configuration
vehicle configuration
```

## Priority C

```text
vehicle purchase / sale
line creation / deletion
```

Phase 11 首次交付不强制 Priority C。

---

# 29. 暂缓复杂基础设施建设

Phase 11 禁止直接实现：

```text
build_road
build_track
build_station
terraform
bulldoze
automatic_route_construction
```

原因：

这些涉及：

```text
geometry
terrain
construction costs
collision
ownership
path planning
```

应该属于后续单独阶段。

---

# 30. Confirmation Semantics

MCP tool 必须区分：

```text
proposal
execution
```

推荐：

```text
propose_rename_line
execute_operation
```

而不是：

```text
rename_line
```

直接写。

这样 LLM 可以先向用户展示：

```text
准备把 Line 11833 从 A 改为 B
```

然后才进入 execution。

---

# 31. Operation History

新增：

```text
OperationJournal
```

记录：

```text
operation_id
proposal
snapshot_before
validation
command_result
snapshot_after
verification
timestamp
```

默认只保留：

```text
metadata + diff
```

不复制完整巨大 snapshot。

---

# 32. 查询接口

新增：

```text
get_operation
```

输入：

```text
operation_id
```

返回当前生命周期。

新增：

```text
list_recent_operations
```

限制：

```text
max <= 50
```

---

# 33. Failure Taxonomy

统一错误：

```text
OPERATION_NOT_SUPPORTED
OPERATION_NOT_VERIFIED

INVALID_PARAMETERS

ENTITY_NOT_FOUND
ENTITY_STATE_CHANGED

STALE_SNAPSHOT
STALE_PROPOSAL

VALIDATION_FAILED

COMMAND_REJECTED
COMMAND_TIMEOUT
ENGINE_ERROR

POSTCONDITION_NOT_MET

ALREADY_EXECUTED
```

---

# 34. Operation Evidence

为每种 write capability 建立：

```text
phase11-evidence/operations/
```

例如：

```text
rename-line/
    before.json
    command.json
    command-response.json
    after.json
    diff.json
```

---

# 35. MCP Tools

Phase 11 最低工具：

```text
get_operation_capabilities

propose_operation

validate_operation

execute_operation

get_operation

list_recent_operations

create_rollback_operation
```

可增加友好封装：

```text
propose_rename_line
propose_rename_station
```

但最终全部走：

```text
OperationController
```

---

# 36. OperationController

Python 增加：

```text
tpf2_mcp/
    operations/
        __init__.py
        models.py
        capabilities.py
        controller.py
        validator.py
        executor.py
        verifier.py
        diff.py
        journal.py
        rollback.py
```

核心：

```python
class OperationController:
    propose()
    validate()
    execute()
    verify()
    rollback()
```

---

# 37. 禁止工具各自实现写逻辑

错误：

```text
server.py
 ├ rename_line implementation
 ├ rename_station implementation
 └ vehicle implementation
```

正确：

```text
MCP tool
    ↓
OperationController
```

MCP 只是 transport adapter。

---

# 38. Lua 侧目录

建议：

```text
tpf2_mod/res/scripts/tpf2_mcp/
    operations/
        dispatcher.lua
        registry.lua
        result.lua

        rename_line.lua
        rename_station.lua
```

以后扩展：

```text
vehicle/
line/
construction/
```

---

# 39. Runtime Safety Guard

Lua 端再做一层检查。

例如：

```lua
if not config.write_enabled then
    return WRITE_DISABLED
end
```

默认：

```text
write_enabled = false
```

Phase 11 Live Test 时显式开启。

---

# 40. Global Write Kill Switch

config 增加：

```text
allow_write_operations
```

默认：

```text
false
```

以及：

```text
allowed_operations
```

例如：

```lua
allowed_operations = {
    RENAME_LINE = true,
}
```

即使 Python 发送其它 command：

```text
Lua 也拒绝
```

---

# 41. 每类操作单独开关

建议：

```text
allow_rename
allow_vehicle_management
allow_line_management
allow_construction
```

Phase 11：

```text
construction = false
```

---

# 42. Live Write Verification

必须真正启动 TPF2 测试。

但只在：

```text
专用测试存档
```

进行。

首个测试建议：

```text
Rename Line
```

---

# 43. Live Test A：Rename Line

流程：

```text
Snapshot N
↓
获取 Line ID
↓
记录 old_name
↓
Proposal
↓
Validation
↓
Execute
↓
Snapshot N+1
↓
验证 new_name
↓
Rollback Proposal
↓
Execute
↓
Snapshot N+2
↓
验证 old_name restored
```

这是 Phase 11 最关键的完整闭环。

---

# 44. Live Test B：Duplicate Operation

发送：

```text
same operation_id
```

两次。

要求：

第一次：

```text
EXECUTED
```

第二次：

```text
ALREADY_EXECUTED
```

确认不会重复修改。

---

# 45. Live Test C：Stale Snapshot

创建 proposal：

```text
snapshot = N
```

等待游戏状态变成：

```text
N+1
```

再执行。

要求：

```text
STALE_PROPOSAL
```

---

# 46. Live Test D：Invalid Target

发送不存在：

```text
line_id
```

要求：

```text
ENTITY_NOT_FOUND
```

且游戏保持正常。

---

# 47. Live Test E：Write Kill Switch

```text
allow_write_operations = false
```

发送合法 operation。

要求：

```text
WRITE_DISABLED
```

游戏状态无变化。

---

# 48. Unit Tests

新增：

```text
tests/phase11/
    test_operation_models.py
    test_capabilities.py
    test_validator.py
    test_controller.py
    test_idempotency.py
    test_verifier.py
    test_diff.py
    test_rollback.py
```

---

# 49. 必测：No Accidental Write

Mock bridge：

```text
propose()
validate()
dry_run()
```

期间：

```text
send_write_command call count == 0
```

---

# 50. 必测：Exactly Once

同一个：

```text
operation_id
```

连续 execute 两次。

确认 executor 不产生两个逻辑写操作。

---

# 51. 必测：Stale Rejection

```text
proposal snapshot = 10
current snapshot = 11
```

必须拒绝。

---

# 52. 必测：Postcondition

模拟：

```text
command accepted
```

但 after snapshot：

```text
name unchanged
```

最终：

```text
POSTCONDITION_NOT_MET
```

不能返回成功。

---

# 53. 必测：Rollback

操作：

```text
A → B
```

生成 rollback：

```text
B → A
```

检查参数正确。

---

# 54. Evidence Status

Phase 11 建议扩展 evidence：

```text
ENGINE_VERIFIED
UI_CROSS_VERIFIED
DERIVED
HEURISTIC
HYPOTHETICAL
EXECUTED
POSTCONDITION_VERIFIED
UNAVAILABLE
```

注意：

```text
EXECUTED
```

只说明 command 执行。

最终最强状态：

```text
POSTCONDITION_VERIFIED
```

---

# 55. Phase 11 Flagship Tool

新增：

```text
execute_verified_operation
```

但它必须要求：

```text
proposal_id
```

而不是接受裸参数。

完整：

```text
proposal
↓
validation
↓
execution
↓
new snapshot
↓
verification
```

返回：

```json
{
  "operation_id": "op-x",

  "status": "POSTCONDITION_VERIFIED",

  "before": {},

  "requested_change": {},

  "after": {},

  "diff": {},

  "rollback_available": true
}
```

---

# 56. 不要把 Planner 与 Executor 合并

必须保持：

```text
DecisionSupport
```

和：

```text
OperationController
```

两个独立模块。

正确：

```text
DecisionSupport
      ↓
Planning Option

OperationController
      ↓
Explicit Game Operation
```

---

# 57. Phase 11 不做 Autonomous Agent

即使已经可以写游戏，也禁止：

```text
analyze_network
↓
自动选择 recommendation
↓
自动 execute
```

Phase 11 只允许：

```text
明确的单次受控操作
```

自主闭环留给：

```text
Phase 12
```

---

# 58. Phase 11 Evidence 目录

最终：

```text
phase11-evidence/
    manifest.json

    write-capabilities.json
    write-api-probe.json

    rename-line/
        before.json
        proposal.json
        validation.json
        command.json
        response.json
        after.json
        diff.json

    rollback-rename-line/
        ...

    stale-proposal.json
    duplicate-operation.json
    write-disabled.json

    phase11-live-mcp-session.jsonl
```

---

# 59. Documentation

增加：

```text
PHASE11_CONTROLLED_OPERATIONS.md
```

必须解释：

```text
Proposal
Operation
Execution
Verification
Rollback
Idempotency
Snapshot concurrency
Write kill switch
```

README 增加：

```text
## Phase 11 Controlled Operations
```

---

# 60. 最终交付物

打包：

```text
tpf2-mcp-phase11-controlled-operations.zip
```

必须包含：

```text
完整源码

Lua write operation implementation

Python OperationController

MCP tools

Unit tests

Live verification

phase11-evidence/

PHASE11_CONTROLLED_OPERATIONS.md

README.md
```

不要包含：

```text
__pycache__
*.pyc
临时日志
IDE metadata
```

---

# 61. Phase 11 验收条件

Phase 11 完成必须同时满足：

- 已识别至少一个真实可写 TPF2 API；
- API 已完成 Live Verification；
- 存在 Write Capability Registry；
- 默认写操作关闭；
- Lua 有 global write kill switch；
- Lua 有 operation allowlist；
- Python 不直接调用任意 Lua；
- 写操作使用结构化 command；
- Operation Proposal 本身不会修改游戏；
- 所有 operation 绑定 snapshot sequence；
- stale proposal 会被拒绝；
- 所有 operation 有 precondition validation；
- operation_id 支持幂等；
- command ACK 不等于成功；
- 写后重新读取 snapshot；
- 存在 postcondition verification；
- 能输出 before / after / diff；
- 至少一个操作支持 rollback；
- rollback 也必须走正常 OperationController；
- MCP 能查询 operation lifecycle；
- Live 测试完成；
- 游戏测试存档未出现异常；
- 最终生成：

```text
tpf2-mcp-phase11-controlled-operations.zip
```

---

# 62. Phase 11 最小可接受版本

如果 TPF2 API 的复杂性导致大量写能力无法快速验证，不要扩大战线。

Phase 11 最小成功标准可以只有：

```text
RENAME_LINE
```

但必须完整实现：

```text
API verification

Proposal

Validation

Snapshot locking

Structured command

Write kill switch

Idempotency

Execution

Postcondition verification

Diff

Rollback
```

相比一次性支持十几个不可靠的操作：

```text
1 个完全闭环且可靠的 operation
```

更有价值。

---

# 63. 不要提前做 Phase 12

Phase 11 禁止：

```text
自动选择最优方案
自动连续执行多个 operation
自动买车
自动卖车
自动重构网络
自动根据 KPI 持续调整
自动恢复失败计划
```

这些属于：

# Phase 12 — Closed-Loop Agent

Phase 11 最终应形成：

```text
              READ PATH
Game
 ↓
Snapshot
 ↓
Network Intelligence
 ↓
Decision Support

              WRITE PATH
Planning Option
 ↓
Operation Proposal
 ↓
Validation
 ↓
Controlled Executor
 ↓
TPF2
 ↓
New Snapshot
 ↓
Postcondition Verification
```

到这里，TPF2 MCP 才第一次形成完整的：

```text
Observe → Think → Act → Verify
```

基础设施。