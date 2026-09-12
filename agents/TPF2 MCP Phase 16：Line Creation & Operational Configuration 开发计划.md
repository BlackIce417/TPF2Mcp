# TPF2 MCP Phase 16：Line Creation & Operational Configuration

## 0. Phase 16 定位

当前已经具备：

```text
RENAME_LINE

BUY_VEHICLE

ASSIGN_VEHICLE_TO_LINE

TaskOrchestrator

OperationController

Fresh Snapshot Verification

runtime_context

one mutation per continue_task
```

Phase 16 的核心目标不是建设新的铁路、道路或车站。

本阶段定义的：

```text
CREATE_LINE
```

是指：

```text
在已经存在的轨道/道路/航路
以及已经存在的站点/Terminal
基础上创建新的运营线路。
```

即：

```text
已有基础设施
        ↓
选择起点
        ↓
选择终点
        ↓
选择途经/停靠站
        ↓
创建 Line Entity
        ↓
配置车辆
        ↓
配置运营策略
        ↓
形成可运营线路
```

因此：

```text
CREATE_LINE
```

属于：

```text
Operational Control
```

而不是：

```text
Infrastructure Construction
```

---

# 1. 本阶段明确不做

Phase 16 禁止扩展：

```text
建设铁路

建设道路

建设新车站

terraform

桥梁建设

隧道建设

轨道 geometry planning

road geometry planning

bulldoze
```

已有基础设施是否足以支持线路，由：

```text
TPF2 existing network/pathfinding
```

负责。

Phase 16 只操作：

```text
Line
Stop
Vehicle
Scheduling
```

---

# 2. Phase 16 总目标

最终希望用户能够说：

```text
以 A 为起点、D 为终点，
经过 B、C，
新建一条线路，
然后给它配两辆和线路 X 同型的车。
```

MCP 完成：

```text
Resolve A/B/C/D
↓
Validate stations
↓
Build ordered stops
↓
CREATE_LINE
↓
Fresh Snapshot
↓
Discover new_line_id
↓
Verify stops
↓
Select compatible vehicle template
↓
BUY
↓
Fresh Snapshot
↓
Discover new_vehicle_id
↓
ASSIGN
↓
Fresh Snapshot
↓
repeat vehicle allocation
↓
Final Verification
↓
COMPLETED
```

---

# 3. Phase 16 优先级

严格按照：

```text
P0  Release / Evidence Integrity

P1  CREATE_LINE

P2  Line Route / Stop Model

P3  CREATE_AND_STAFF_LINE_GOAL

P4  SET_LINE_STOPS

P5  Scheduling Controls

P6  REMOVE_VEHICLE_FROM_LINE

P7  SELL_VEHICLE
```

REMOVE / SELL 不再阻塞 CREATE_LINE。

---

# 4. P0：修复 Phase 15 Release Packaging

当前 Phase 15 ZIP 存在目录 flatten 问题。

Phase 16 最终必须恢复完整结构：

```text
tpf2-mcp/
│
├─ mcp_server/
│  ├─ src/
│  │  └─ tpf2_mcp/
│  │     ├─ operations/
│  │     ├─ tasks/
│  │     ├─ planning/
│  │     └─ server.py
│  │
│  └─ tests/
│
├─ tpf2_mod/
│
├─ diagnostics/
│
├─ docs/
│
├─ tools/
│
└─ README.md
```

禁止 ZIP flatten。

---

# 5. Release Self-Test

增加：

```text
tools/verify-release-package.py
```

流程：

```text
build zip
↓
extract into clean temp dir
↓
verify project paths
↓
verify evidence paths
↓
pytest -q
↓
PASS
```

最终 ZIP 必须能够直接测试。

---

# 6. Evidence Integrity

任何 capability：

```text
live_mcp_verified = true
```

都必须具有真实 evidence：

```text
diagnostics/.../
```

不能再出现：

```text
README 指向 evidence
但 ZIP 内不存在
```

---

# 7. Capability Product Readiness

Phase 16 正式定义：

```text
PRODUCT_READY =
    engine_verified
    AND controller_supported
    AND task_supported
    AND live_mcp_verified
    AND evidence_integrity_verified
```

---

# 8. P1：CREATE_LINE API Discovery

本阶段最重要的技术突破：

```text
CREATE_LINE
```

目标：

```text
基于 existing station / terminal
创建新的 Transport Line entity
```

---

# 9. CREATE_LINE 不是建轨

必须明确：

输入：

```text
existing stations
```

输出：

```text
new line entity
```

不改变：

```text
track geometry
road geometry
station geometry
terrain
```

---

# 10. API Source Discovery

重点调查：

```text
api.cmd.make.*
game.interface.*
TransportLine
LineComponent
createLine
addLine
newLine
line manager
transport line UI
```

不仅 grep 函数名。

必须追：

```text
UI action
↓
callback
↓
helper
↓
command constructor
↓
sendCommand
```

---

# 11. Existing Line Raw Probe

新增：

```text
tools / collectors:
line_raw_probe.lua
```

选择多条现有线路，完整采集：

```text
line entity id

component names

transport mode

raw stops

terminal descriptors

station references

owner

vehicle_ids

raw line component
```

---

# 12. 多线路采样

至少：

```text
5 条线路
```

尽可能覆盖：

```text
rail
road
tram
ship
air
```

当前测试存档不存在的模式可以跳过。

---

# 13. 目的

不是为了做统计。

而是为了确定：

```text
Line entity 创建所需的最小数据结构
```

尤其要搞清：

```text
stop descriptor
```

---

# 14. CREATE_LINE Business Model

上层不得直接要求用户构造 TPF2 raw payload。

定义：

```python
LineCreationRequest:
    start_station_id
    end_station_id
    via_station_ids
    transport_mode
```

其中：

```text
via_station_ids
```

表示：

```text
中间需要停靠的站点
```

---

# 15. Ordered Stop Construction

标准业务层：

```text
start = A
via = [B, C]
end = D
```

得到：

```text
[A, B, C, D]
```

但这只是：

```text
Normalized Operational Route
```

不是最终底层 TPF2 payload。

---

# 16. 返程表达必须实测

必须确认 TPF2 LineComponent 是：

```text
A → B → C → D
```

即可代表循环/往返，

还是底层要求：

```text
A → B → C → D → C → B
```

或者其它格式。

禁止提前假设。

---

# 17. 通过现有线路反推

找真实：

```text
A-B-C
```

线路。

对比：

```text
UI stop order
```

和：

```text
raw line component
```

确定真实语义。

---

# 18. Stop 的含义

Phase 16 明确：

```text
via station
```

表示：

```text
运营停靠点
```

不是：

```text
物理轨道途经点
```

列车物理走哪条轨道：

```text
由 TPF2 pathfinder 处理
```

---

# 19. Stop Descriptor

Normalize 为：

```json
{
  "sequence_index": 0,

  "station_id": 100,

  "terminal_id": null,

  "terminal_index": null,

  "raw": {}
}
```

只填确认过的数据。

---

# 20. Raw 强制保留

必须保存：

```text
raw
```

因为实际 CREATE_LINE command 很可能需要：

```text
terminal
edge
station group
```

等底层 descriptor。

---

# 21. Station vs Terminal

Phase 16 必须明确：

```text
station entity
```

和：

```text
terminal
```

之间关系。

用户提供：

```text
station_id
```

时，MCP 应尽量自动选择合法 terminal。

---

# 22. Terminal Resolution

新增：

```text
LineStopResolver
```

接口：

```text
resolve_station_to_stop_descriptor(
    station_id,
    transport_mode
)
```

---

# 23. Multiple Terminals

如果一个 station 有多个 compatible terminal：

不能随便选。

优先规则必须有 evidence。

如果没有可靠选择依据：

返回：

```text
AMBIGUOUS_TERMINAL
```

要求更明确输入。

---

# 24. CREATE_LINE Operation

最终 Operation：

```text
CREATE_LINE
```

参数建议：

```json
{
  "start_station_id": 100,

  "end_station_id": 400,

  "via_station_ids": [
    200,
    300
  ],

  "transport_mode": "RAIL"
}
```

---

# 25. Transport Mode

如果能够从：

```text
stations + terminals
```

唯一确定 mode，可以自动解析。

否则显式输入。

---

# 26. CREATE_LINE Preconditions

至少：

```text
start station exists

end station exists

all via stations exist

all stop descriptors resolvable

transport mode valid

minimum number of stops valid

no unresolved terminal ambiguity

snapshot current

CREATE_LINE engine verified

runtime write enabled
```

---

# 27. 不负责提前证明所有轨道 path 可通

如果 TPF2 API 本身进行 route/path validation：

优先交给 Engine。

MCP 可以做已有 graph 的辅助检查，但不能把：

```text
network graph connectivity
```

错误等同于：

```text
TPF2 line can definitely route
```

---

# 28. CREATE_LINE Live Probe

必须使用专用测试存档。

选择：

```text
已有轨道连接的现有站 A
已有轨道连接的现有站 B
```

先尝试：

```text
A → B
```

最小线路。

---

# 29. 第一阶段不要一开始测试复杂 via

先：

```text
A → B
```

成功后：

```text
A → B → C
```

再验证中间站。

---

# 30. CREATE_LINE Verification

执行前：

```text
baseline line IDs
```

执行后 Fresh Snapshot：

```text
after line IDs
```

计算：

```text
new_ids = after - before
```

必须：

```text
len(new_ids) == 1
```

---

# 31. New Line ID

必须来自：

```text
Fresh Snapshot
```

禁止猜 ID。

---

# 32. 第二级 Verification

识别：

```text
new_line_id
```

之后验证：

```text
observed ordered stops
```

与：

```text
desired normalized route
```

语义一致。

---

# 33. 第三级 Verification

如果可用，再验证：

```text
transport_mode

owner

vehicle_count == 0
```

---

# 34. CREATE_LINE Handler

新增：

```text
operations/handlers/create_line.py
```

统一：

```text
validate
build command
execute
verify
```

---

# 35. Capability

CREATE_LINE 成功后：

```text
engine_verified = true
controller_supported = true
task_supported = true
```

最终 MCP Live 后：

```text
PRODUCT_READY
```

---

# 36. CREATE_LINE_GOAL

新增：

```text
CREATE_LINE_GOAL
```

输入：

```text
start
end
via
transport_mode
```

---

# 37. Satisfaction

必须：

```text
task.runtime_context.new_line_id exists
```

且：

```text
line exists
```

以及：

```text
stop sequence verified
```

---

# 38. Runtime Context

成功后记录：

```json
{
  "new_line_id": 123456
}
```

只能来自：

```text
POSTCONDITION_VERIFIED CREATE_LINE
```

---

# 39. P2：线路 Route Model

新增：

```text
LineRoute
```

建议：

```python
LineRoute:
    start_station_id
    end_station_id
    via_station_ids
    normalized_stop_sequence
```

---

# 40. Route 和 Infrastructure Path 分开

必须保持：

```text
LineRoute
```

代表：

```text
运营停站
```

而不是：

```text
track path
```

不要存每段铁路 edge。

---

# 41. 查询接口

新增：

```text
get_line_route
```

返回：

```json
{
  "line_id": 123,

  "start_station_id": 100,

  "end_station_id": 400,

  "via_station_ids": [
    200,
    300
  ],

  "ordered_stops": [...]
}
```

---

# 42. 如果线路实际上循环

不要为了业务展示强行声称 start/end。

返回：

```text
route_type
```

例如：

```text
LINEAR
LOOP
UNKNOWN
```

只有能证明时使用。

---

# 43. create_line 上层第一版

Phase 16 第一版主要支持：

```text
LINEAR-style user intent
```

即：

```text
start
via
end
```

底层再适配游戏 representation。

---

# 44. P3：CREATE_AND_STAFF_LINE_GOAL

这是 Phase 16 的旗舰业务能力。

目标：

```text
新建线路
+
配指定数量的车辆
```

---

# 45. 输入

建议：

```json
{
  "start_station_id": 100,

  "end_station_id": 400,

  "via_station_ids": [
    200,
    300
  ],

  "vehicle_count": 2,

  "vehicle_template_source_line_id": 900
}
```

---

# 46. Template Source Line

用户可以给：

```text
vehicle_template_source_line_id
```

表示：

```text
新线路车辆参考已有线路 X
```

---

# 47. 自动 Template Selection

如果用户不指定，可尝试：

```text
find compatible existing line
```

但必须给 selection evidence。

不能说：

```text
最佳车型
```

只能说：

```text
verified compatible template
```

---

# 48. 最可靠 Template

优先：

```text
现有同 transport mode 线路
```

上的车辆。

---

# 49. Composite Task Step 1

```text
CREATE_LINE
```

执行后：

```text
Fresh Snapshot
↓
new_line_id
```

---

# 50. Step 2

```text
BUY_VEHICLE
```

使用 compatible vehicle template。

Fresh Snapshot：

```text
new_vehicle_id
```

---

# 51. Step 3

```text
ASSIGN_VEHICLE_TO_LINE
```

目标：

```text
runtime_context.new_line_id
```

---

# 52. 多辆车循环

如果：

```text
vehicle_count = 2
```

流程：

```text
CREATE
BUY #1
ASSIGN #1
BUY #2
ASSIGN #2
```

---

# 53. 严格 One Mutation Per Continue

必须：

```text
continue #1 → CREATE

continue #2 → BUY #1

continue #3 → ASSIGN #1

continue #4 → BUY #2

continue #5 → ASSIGN #2
```

---

# 54. Task runtime_context

建议：

```json
{
  "new_line_id": 123,

  "purchased_vehicle_ids": [
    456,
    457
  ],

  "assigned_vehicle_ids": [
    456,
    457
  ]
}
```

---

# 55. 所有 ID 只能来自 Fresh Snapshot

包括：

```text
new_line_id

new_vehicle_ids
```

严禁 Planner 推测。

---

# 56. Composite Goal Completion

最终必须验证：

```text
line exists

route matches desired stops

assigned vehicle count >= requested count

all task-purchased vehicles assigned to new line
```

---

# 57. 不以单纯 line.vehicle_count 判断

最好同时验证：

```text
vehicle.line_id == new_line_id
```

---

# 58. Partial Completion

例如：

```text
CREATE success
BUY #1 success
ASSIGN #1 success
BUY #2 failed
```

Task：

```text
PARTIALLY_COMPLETED
```

明确：

```text
1 / 2 vehicles configured
```

---

# 59. 默认 allow_partial

对于：

```text
CREATE_AND_STAFF_LINE_GOAL
```

默认：

```text
allow_partial = false
```

但注意：

已经发生的 mutation 无法凭空撤销。

所以实际失败后：

```text
PARTIALLY_COMPLETED
```

仍需如实记录。

---

# 60. Dry Run / Preview

增加：

```text
preview_create_line
```

只做：

```text
resolve stops
check ambiguity
show normalized route
show vehicle template
show required mutations
```

不执行。

---

# 61. Preview 输出

例如：

```json
{
  "route": {
    "start": 100,
    "via": [200, 300],
    "end": 400
  },

  "vehicle_plan": {
    "count": 2,
    "template_source_line_id": 900
  },

  "mutations": 5
}
```

---

# 62. P4：SET_LINE_STOPS

定义：

```text
修改现有 Line 的运营停站序列
```

不修改基础设施。

---

# 63. 业务接口

支持：

```json
{
  "line_id": 123,

  "start_station_id": 100,

  "end_station_id": 500,

  "via_station_ids": [
    200,
    400
  ]
}
```

---

# 64. 内部转换

转换成：

```text
ordered stop descriptors
```

再发送真实 API。

---

# 65. Source Discovery

CREATE_LINE API 找到后，重点检查：

```text
是否同一 command 支持修改 line component
```

或者：

```text
是否另有 update line command
```

---

# 66. Live Test

只使用：

```text
Phase 16 创建的测试线路
```

例如：

```text
A-B
```

修改为：

```text
A-C-B
```

---

# 67. Verification

必须比较：

```text
normalized route
```

以及底层：

```text
ordered stop descriptors
```

---

# 68. Precondition

保存：

```text
expected_old_route
```

如果实际 route 已变化：

```text
PRECONDITION_CHANGED
```

拒绝。

---

# 69. SET_LINE_STOPS Risk

```text
MEDIUM
MANUAL
```

---

# 70. SET_LINE_STOPS Goal

新增：

```text
SET_LINE_STOPS_GOAL
```

---

# 71. 高层 Goal：RECONFIGURE_LINE_ROUTE_GOAL

输入：

```text
line_id
start
end
via
```

由 Planner 转：

```text
SET_LINE_STOPS
```

---

# 72. P5：Scheduling

本阶段用户要求的运营能力还包括：

```text
调度策略
```

因此 Phase 16 要继续推进真实 scheduling API。

---

# 73. 不再把 frequency 当直接操作

如果 TPF2 frequency 是结果：

```text
frequency
```

继续只作为 KPI。

---

# 74. 优先寻找真实可控策略

例如：

```text
minimum load

maximum waiting time

wait for full load

stop waiting policy

terminal-specific behavior
```

具体名称按实际 API。

---

# 75. UI → Command Trace

从线路/车辆 UI 中：

```text
control widget
↓
callback
↓
component
↓
command
```

建立：

```text
docs/scheduling-deep-trace.md
```

---

# 76. 至少争取一个真实调度 operation

比如如果找到：

```text
minimum load
```

则实现：

```text
SET_MINIMUM_LOAD
```

不要搞一个：

```text
SET_SCHEDULING_PARAMETER(key,value)
```

万能接口。

---

# 77. Scheduling Verification

必须：

```text
before
↓
execute
↓
fresh snapshot
↓
after
```

如果只能从 UI 读取：

可以：

```text
UI_CROSS_VERIFIED
```

但仍需明确来源。

---

# 78. Scheduling Risk

默认：

```text
MEDIUM
```

---

# 79. CREATE_AND_CONFIGURE_LINE_GOAL

如果 Scheduling 成功，则扩展旗舰 Goal：

```text
CREATE
↓
BUY
↓
ASSIGN
↓
SET scheduling
```

---

# 80. 运营策略输入

未来可以：

```json
{
  "scheduling": {
    "minimum_load": 0.5,
    "maximum_wait": 60
  }
}
```

但只有已验证参数才允许。

---

# 81. 未验证参数

返回：

```text
UNSUPPORTED_SCHEDULING_OPTION
```

---

# 82. P6：REMOVE_VEHICLE_FROM_LINE

这一项继续做，但优先级降低。

目标：

```text
车辆不再属于指定线路
```

不是 sell。

---

# 83. API Discovery

继续调查：

```text
setLine
sendToDepot
line assignment UI
vehicle manager
```

---

# 84. 禁止猜 nil/-1

实际 command 语义必须实测。

---

# 85. Live Test

只使用 Phase 16 临时车辆。

---

# 86. Goal

新增：

```text
REMOVE_VEHICLE_FROM_LINE_GOAL
```

---

# 87. 高层 Goal

```text
REDUCE_LINE_FLEET_GOAL
```

默认：

```text
remove from line
```

而不是：

```text
sell
```

---

# 88. P7：SELL_VEHICLE

继续查真实 API。

只卖：

```text
Phase 16 测试车辆
```

---

# 89. SELL Risk

```text
HIGH

destructive

MANUAL only

no rollback guarantee
```

---

# 90. SELL Goal

```text
SELL_VEHICLE_GOAL
```

用户没有明确卖车意图时：

不得由：

```text
reduce fleet
```

自动转换成 SELL。

---

# 91. Line Creation Planner

新增：

```text
planning/line_creation.py
```

只负责结构化：

```text
resolve route
resolve transport mode
resolve terminal
resolve vehicle template
estimate required task steps
```

---

# 92. Planner 不执行

严格：

```text
LineCreationPlanner
↓
Task Goal
↓
TaskOrchestrator
↓
OperationController
```

---

# 93. New MCP Tools

建议增加：

```text
preview_create_line

create_line_task

get_line_route

validate_line_route

find_vehicle_templates_for_route
```

---

# 94. 不建议增加直接 write MCP

不要新增：

```text
create_line_now
```

绕过 Task。

写操作仍走：

```text
Task
```

---

# 95. validate_line_route

输入：

```text
start
via
end
transport mode
```

返回：

```text
stations resolved

terminals resolved

ambiguities

normalized stops

structural graph relation

limitations
```

---

# 96. 注意 graph relation

如果现有 network graph：

```text
A reachable to B
```

可以作为：

```text
supporting evidence
```

但不要声称：

```text
Engine definitely accepts line
```

---

# 97. Station Name Resolution

除了 station ID，后续可支持：

```text
station name
```

但必须：

```text
resolve unique entity
```

存在同名：

```text
AMBIGUOUS_STATION
```

---

# 98. Line Name

CREATE_LINE 成功后，如果 API 默认生成名称：

可以保留。

若用户提供：

```text
desired_name
```

则作为下一独立：

```text
RENAME_LINE
```

step。

---

# 99. 不把 rename 合并进 CREATE

继续保持：

```text
one operation
one mutation
```

例如：

```text
continue #1 CREATE
continue #2 RENAME
```

---

# 100. CREATE_AND_STAFF_WITH_NAME Goal

Stretch：

```text
CREATE
↓
RENAME
↓
BUY
↓
ASSIGN
```

---

# 101. Task Scope

新线路任务需要：

```text
allowed_station_ids

allowed_template_line_ids

max_new_lines

max_new_vehicles

allowed_operations
```

---

# 102. 默认 Budget

```text
max_new_lines = 1
```

车辆：

```text
max_new_vehicles = requested count
```

---

# 103. 防止重复建线

如果 task timeout：

禁止直接重新：

```text
CREATE_LINE
```

---

# 104. CREATE idempotency

必须像 BUY 一样强化。

如果：

```text
command submitted
server crashes
```

恢复时：

```text
Fresh Snapshot
↓
check new line
```

而不是再 CREATE。

---

# 105. CREATE Recovery Attribution

如果出现新线路，需要结合：

```text
ordered stops
transport mode
task baseline
```

确认是不是 task 创建的。

---

# 106. Multiple New Lines

如果恢复时出现多个候选：

```text
AMBIGUOUS_NEW_ENTITY
```

不猜。

---

# 107. Persistent runtime_context

Phase 16 必须把：

```text
new_line_id
new_vehicle_ids
```

持久化到 task journal。

Server restart 后可恢复。

---

# 108. Phase 16 Test Suite

增加：

```text
tests/phase16/
```

至少：

```text
test_release_package.py

test_evidence_integrity.py

test_line_route_model.py

test_line_stop_resolver.py

test_create_line_handler.py

test_create_line_goal.py

test_create_and_staff_line.py

test_multiple_vehicle_staffing.py

test_create_line_recovery.py

test_set_line_stops.py

test_scheduling_capabilities.py

test_remove_vehicle.py

test_sell_vehicle.py
```

---

# 109. CREATE Unit Test

before：

```text
lines = {1,2}
```

after：

```text
lines = {1,2,3}
```

要求：

```text
new_line_id = 3
```

---

# 110. Ambiguous CREATE Test

after：

```text
{1,2,3,4}
```

expected：

```text
1 new line
```

必须：

```text
AMBIGUOUS_NEW_ENTITY
```

---

# 111. Route Order Test

必须证明：

```text
[A,B,C,D]
!=
[A,C,B,D]
```

---

# 112. Duplicate Stop Test

如果 TPF2 允许：

```text
[A,B,C,B]
```

必须完整保留。

---

# 113. Multi-Vehicle Task Test

requested：

```text
vehicle_count = 2
```

必须执行：

```text
CREATE
BUY
ASSIGN
BUY
ASSIGN
```

共：

```text
5 mutations
```

但每次 continue：

```text
<= 1 mutation
```

---

# 114. Restart Recovery Test

模拟：

```text
CREATE sent
↓
game creates line
↓
MCP crashes
↓
restart
```

要求：

```text
recover task
↓
fresh snapshot
↓
identify new line
↓
continue to BUY
```

禁止再 CREATE。

---

# 115. Live Acceptance A：最小 CREATE_LINE

专用测试存档：

```text
A
B
```

都是现有站。

执行：

```text
CREATE_LINE_GOAL
```

---

# 116. Acceptance A 必须证明

```text
new line entity observed

new line ID discovered

stops verified

transport mode verified if available

Task COMPLETED
```

---

# 117. Live Acceptance B：Via Stop

创建：

```text
A → B → C
```

其中：

```text
A start
B via
C end
```

证明：

```text
via semantics
```

成立。

---

# 118. Live Acceptance C：CREATE_AND_STAFF

创建：

```text
A → B → C
```

并配：

```text
1 vehicle
```

流程：

```text
CREATE
↓
BUY
↓
ASSIGN
```

完整 MCP-native。

---

# 119. Live Acceptance D：2 Vehicles

同样线路：

```text
vehicle_count = 2
```

证明多步循环。

---

# 120. Live Acceptance E：SET_LINE_STOPS

如果 API 找到：

对 Phase 16 临时线路：

```text
A-B
→
A-C-B
```

再验证。

---

# 121. Live Acceptance F：Scheduling

如果找到真实参数：

修改临时线路。

然后恢复原值。

---

# 122. Live Acceptance G：Remove/Sell

只使用测试车辆。

---

# 123. Phase 16 Evidence Layout

必须真实存在：

```text
diagnostics/phase16-live/
```

---

# 124. CREATE evidence

```text
create-line/
    before.json
    route-resolution.json
    proposal.json
    validation.json
    command.json
    response.json
    after.json
    verification.json
```

---

# 125. CREATE_AND_STAFF evidence

```text
create-and-staff/
    task-created.json

    step1-create.json
    after-create.json

    step2-buy.json
    after-buy.json

    step3-assign.json
    after-assign.json

    final-verification.json
    task-completed.json
```

---

# 126. Two Vehicle Evidence

单独：

```text
create-and-staff-two-vehicles/
```

证明循环正确。

---

# 127. Manifest

```text
diagnostics/phase16-live/manifest.json
```

至少：

```text
game version

mod version

test save

verified capabilities

task IDs

operation IDs

evidence paths

sha256
```

---

# 128. README Capability Matrix

例如：

| Operation | Engine | Controller | Task | Live MCP | Product |
|---|---:|---:|---:|---:|---:|
| BUY_VEHICLE | Yes | Yes | Yes | Yes | Yes |
| ASSIGN_VEHICLE_TO_LINE | Yes | Yes | Yes | Yes | Yes |
| CREATE_LINE | ... | ... | ... | ... | ... |
| SET_LINE_STOPS | ... | ... | ... | ... | ... |
| REMOVE_VEHICLE_FROM_LINE | ... | ... | ... | ... | ... |
| SELL_VEHICLE | ... | ... | ... | ... | ... |

---

# 129. Phase 16 最低验收

硬性要求：

1. ZIP 目录结构修复；
2. ZIP clean extract 后 pytest 能运行；
3. Evidence path 不再悬空；
4. CREATE_LINE API 找到并完成真实 Live Probe；
5. CREATE_LINE 至少 `POSTCONDITION_VERIFIED`；
6. `start + via + end` Route Model 完成；
7. Fresh Snapshot 能识别 `new_line_id`；
8. CREATE_LINE 接入 OperationController；
9. CREATE_LINE_GOAL 接入 Task；
10. MCP-native CREATE_LINE Live 成功；
11. BUY/ASSIGN Regression 不退化；
12. one mutation per continue 保持。

---

# 130. 标准验收

在最低要求基础上：

```text
CREATE_LINE = PRODUCT_READY
```

并完成：

```text
CREATE_AND_STAFF_LINE_GOAL
```

真实 Live：

```text
CREATE
BUY
ASSIGN
COMPLETED
```

---

# 131. 优秀验收

达到：

```text
CREATE_LINE                 PRODUCT_READY

SET_LINE_STOPS              PRODUCT_READY

BUY_VEHICLE                 PRODUCT_READY

ASSIGN_VEHICLE_TO_LINE      PRODUCT_READY
```

并至少一个：

```text
Scheduling capability
```

达到：

```text
POSTCONDITION_VERIFIED
```

---

# 132. Stretch

如果时间充足：

```text
REMOVE_VEHICLE_FROM_LINE

SELL_VEHICLE
```

继续产品化。

---

# 133. Phase 16 最关键 Demo

用户：

```text
用 A 站作为起点，
D 站作为终点，
中间停靠 B、C，
新建一条线路，
并给它配两辆和线路 X 一样的车。
```

系统应完成：

```text
Resolve A/B/C/D
↓
Route = A-B-C-D
↓
CREATE_LINE
↓
Fresh Snapshot
↓
new_line_id
↓
BUY #1
↓
Fresh Snapshot
↓
new_vehicle_id #1
↓
ASSIGN #1
↓
Fresh Snapshot
↓
BUY #2
↓
Fresh Snapshot
↓
new_vehicle_id #2
↓
ASSIGN #2
↓
Fresh Snapshot
↓
Verify:
  route
  line
  vehicle #1
  vehicle #2
↓
COMPLETED
```

---

# 134. 最终产品语义

Phase 16 完成后：

```text
“AI 新建线路”
```

应明确表示：

```text
选择已有站点
+
定义起点
+
定义终点
+
定义途经停站
+
创建运营线路
+
配置车辆
+
可选配置调度策略
```

而不是：

```text
建设轨道
建设道路
建设站点
```

---

# 135. Infrastructure Construction 独立后移

以后如果真的需要：

```text
AI 建站
AI 铺轨
AI 修路
```

单独建立 Phase。

不能再作为：

```text
CREATE_LINE
```

的前置条件。

---

# 136. 最终交付

生成：

```text
tpf2-mcp-phase16-line-creation.zip
```

必须包含：

```text
完整正确目录结构

LineRoute Model

LineStopResolver

CREATE_LINE discovery

CREATE_LINE handler

CREATE_LINE goal

CREATE_AND_STAFF_LINE goal

相关 scheduling probe

完整 tests

Live MCP evidence

Release manifest

PHASE16_LINE_CREATION.md
```

---

# 137. 给 Codex 的最终执行重点

优先级最终固定为：

```text
1. 修复 Release Packaging

2. 突破 CREATE_LINE

3. 搞清 start / via / end 与 TPF2 stop descriptor 的映射

4. CREATE_LINE 接入 Controller + Task

5. 打通 CREATE_AND_STAFF_LINE_GOAL

6. SET_LINE_STOPS

7. 调度策略

8. REMOVE / SELL
```

Phase 16 的核心成果不是“又发现几个函数”。

核心成果必须是：

```text
用户指定已有站点
↓
MCP 创建真实运营线路
↓
给线路配置车辆
↓
Fresh Snapshot 验证
↓
Task COMPLETED
```