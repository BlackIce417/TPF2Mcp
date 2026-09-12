# TPF2 MCP Phase 17：Arbitrary Route Line Creation

## 0. 当前已确认基础

Phase 16 已确认：

```text
api.type.Line.new()
```

可以创建：

```text
Line
```

并且：

```text
line.stops = existing_native_stops
```

有效。

同时：

```text
api.cmd.make.createLine(
    name,
    color,
    player,
    line
)
```

已经能够真实创建线路。

因此：

```text
CREATE_LINE engine primitive
```

已经突破。

当前真正剩下的问题不是：

```text
“怎么创建 line entity”
```

而是：

```text
“怎么从 station / terminal 构造新的合法 native stop descriptors”
```

---

# 1. Phase 17 核心目标

把当前：

```text
source_line_id
↓
copy source_line.stops
↓
createLine
```

升级成：

```text
start_station_id

via_station_ids

end_station_id
↓
LineStopResolver
↓
native ordered stop descriptors
↓
Line.stops
↓
createLine
```

最终实现真正：

```text
CREATE_LINE
```

业务语义。

---

# 2. 当前能力重新命名

Phase 16 现有能力实际上应该在内部重命名为：

```text
CLONE_LINE_ROUTE
```

或者：

```text
CREATE_LINE_FROM_SOURCE_ROUTE
```

不要继续把它当最终 `CREATE_LINE`。

---

# 3. Capability Registry 修改

当前：

```text
CREATE_LINE
```

verified 状态改成：

```text
CREATE_LINE_FROM_SOURCE_ROUTE
```

例如：

```json
{
  "operation_type": "CREATE_LINE_FROM_SOURCE_ROUTE",

  "engine_verified": true,

  "controller_supported": true,

  "task_supported": true
}
```

真正：

```text
CREATE_LINE
```

先恢复为：

```text
DISCOVERED_NOT_VERIFIED
```

直到 arbitrary route Live Verification 完成。

---

# 4. 清除重复 Capability

当前 `_CAPABILITIES` 中：

```text
CREATE_LINE
```

存在两次。

一次：

```text
verified = true
```

另一次：

```text
verified = false
```

必须消除。

Capability Registry 内：

```text
每个 operation_type
只能出现一次
```

增加 unit test：

```text
assert unique operation_type
```

---

# 5. Phase 17 最重要技术问题

要搞清 TPF2 的：

```text
Line.stops
```

每一项到底是什么。

当前 Probe 已经发现：

```text
stationGroup
terminal
```

字段。

重点确认：

```text
stop.stationGroup
stop.terminal
```

真实类型和语义。

---

# 6. 完整 Stop Descriptor Probe

增强：

```text
line_creation_probe.lua
```

不要只输出：

```text
station_id
terminal_id
```

要尽量输出：

```text
Lua type

userdata type

component/entity identity

stationGroup entity

terminal entity/index

edge metadata if any

all accessible fields

metatable-visible fields if safely enumerable
```

---

# 7. 多 Stop 样本

至少选择：

```text
10 个真实 stop
```

来自多条线路。

收集：

```text
raw descriptor
station group
terminal
position
transport mode
```

---

# 8. 同一 Station 多 Terminal 样本

必须重点找：

```text
同一个 stationGroup
```

存在多个 terminal 的情况。

目的是弄清：

```text
station_id
→ terminal
```

选择逻辑。

---

# 9. Station Group 与 Station Entity

必须明确：

```text
station_id
```

用户看到/当前 snapshot 里的 station ID，

和：

```text
stop.stationGroup
```

是不是同一个 entity 类型。

如果不是：

建立：

```text
station → stationGroup
```

映射。

---

# 10. Terminal Resolution

必须搞清：

```text
terminal
```

是：

```text
entity ID
```

还是：

```text
terminal index
```

还是：

```text
userdata/reference
```

不要只依赖当前序列化出来的数字表象。

---

# 11. LineStopResolver

新增：

```text
tpf2_mcp/lines/stop_resolver.py
```

接口：

```python
resolve_station_stop(
    station_id,
    transport_mode=None,
    terminal_selector=None
)
```

返回：

```json
{
  "station_id": 123,

  "station_group_id": 456,

  "terminal": ...,

  "resolution_status": "RESOLVED",

  "source_status": "ENGINE_VERIFIED"
}
```

---

# 12. Resolution Status

统一：

```text
RESOLVED

AMBIGUOUS_TERMINAL

STATION_NOT_FOUND

NO_COMPATIBLE_TERMINAL

TRANSPORT_MODE_MISMATCH

UNAVAILABLE
```

---

# 13. 不允许随机选 Terminal

如果存在两个合法 terminal：

```text
terminal 0
terminal 1
```

且没有可靠规则，

必须：

```text
AMBIGUOUS_TERMINAL
```

而不是默认 0。

---

# 14. 允许显式 terminal 参数

高级输入可以支持：

```json
{
  "station_id": 123,
  "terminal_id": 4
}
```

或者真实 API 对应字段。

---

# 15. LineRoute Model

新增：

```text
lines/models.py
```

包含：

```python
LineRouteRequest:
    start_station_id
    via_station_ids
    end_station_id
    transport_mode
```

---

# 16. Normalized Route

例如：

```text
start = A
via = [B,C]
end = D
```

normalize：

```text
[A,B,C,D]
```

---

# 17. 业务停站与物理路径分离

必须明确：

```text
[A,B,C,D]
```

只是：

```text
运营停站顺序
```

不是：

```text
轨道 edge path
```

TPF2 的 pathfinder 决定：

```text
A 到 B 走哪条现有轨道
```

---

# 18. 返程模型验证

这是本阶段一个关键研究点。

必须从现有线路确认：

用户看到：

```text
A → B → C
```

时，底层 `line.stops` 是：

```text
[A,B,C]
```

还是：

```text
[A,B,C,B]
```

还是其它循环形式。

---

# 19. UI / Raw Cross-check

至少选：

```text
3 条线路
```

同时记录：

```text
UI stop order
raw Line.stops
```

建立：

```text
route-representation-analysis.md
```

---

# 20. CREATE_LINE 新参数

最终业务 operation 应该变成：

```json
{
  "operation_type": "CREATE_LINE",

  "target": {},

  "parameters": {
    "name": "New Line",

    "start_station_id": 100,

    "via_station_ids": [
      200,
      300
    ],

    "end_station_id": 400,

    "transport_mode": "RAIL"
  }
}
```

---

# 21. 不再要求 source_line_id

最终：

```text
source_line_id
```

只能用于：

```text
CREATE_LINE_FROM_SOURCE_ROUTE
```

不能继续出现在正式 `CREATE_LINE` 中。

---

# 22. Lua Command Payload

Python Resolver 不应该直接尝试序列化 Lua userdata。

建议两种方案优先研究：

## 方案 A

Python 只发送：

```text
station IDs
terminal selector
```

Lua 端重新：

```text
resolve entity/component
```

并构造 native stop。

这是优先方案。

## 方案 B

如果存在 engine helper：

直接调用：

```text
station/terminal IDs
→ LineStop object
```

---

# 23. 不通过 JSON 传 userdata

禁止：

```text
serialize Lua userdata
→ Python
→ JSON
→ Lua
```

这种不可靠方案。

---

# 24. Lua Line Stop Builder

新增：

```text
tpf2_mod/.../operations/line_stop_builder.lua
```

接口：

```lua
build_stop(station_id, terminal_selector, transport_mode)
```

返回：

```text
native stop descriptor
```

---

# 25. Stop Builder Live Probe

先不要创建线路。

只：

```text
构造 Line()
↓
构造 stop descriptors
↓
line.stops = descriptors
```

然后读取：

```text
line.stops
```

确认 assignment 成功。

---

# 26. 两站最小测试

第一测试：

```text
A → B
```

已有 A/B 站且已有轨道互通。

构造：

```text
stopA
stopB
```

然后：

```text
line.stops = {stopA, stopB}
```

---

# 27. 如果 assignment 成功

再执行：

```text
createLine
```

---

# 28. CREATE_LINE Live Acceptance A

用户输入：

```text
start=A
end=B
via=[]
```

不得使用：

```text
source_line_id
```

执行创建。

---

# 29. Acceptance A 成功条件

必须：

```text
new line observed
```

并且：

```text
new line ordered stops == A,B
```

语义一致。

---

# 30. Acceptance B：Via Station

创建：

```text
A → B → C
```

其中：

```text
B = via
```

---

# 31. Acceptance B 证明

必须：

```text
raw/native stops
```

和 normalize route：

```text
[A,B,C]
```

正确对应。

---

# 32. CREATE_LINE Handler 重写

当前：

```python
source_line_id
```

版本迁到：

```text
CreateLineFromSourceRouteHandler
```

新增真正：

```text
CreateLineHandler
```

---

# 33. CreateLineHandler.validate_parameters

检查：

```text
start_station_id integer

end_station_id integer

via list valid

minimum route length

station existence

name valid
```

---

# 34. expected_effect

变成：

```json
{
  "new_line_count": 1,

  "normalized_route": [
    100,
    200,
    300
  ]
}
```

---

# 35. Postcondition

新线路创建后：

```text
identify new line
```

再比较：

```text
observed route
```

与：

```text
expected normalized route
```

---

# 36. 不再比较 source line stops

当前实现：

```text
observed == source_line.stops
```

必须删除。

---

# 37. Route Comparison Layer

新增：

```text
normalize_observed_line_route(line)
```

避免直接比较：

```text
raw userdata
```

---

# 38. CREATE_LINE_GOAL 重写

当前 Goal：

```text
source_line_id + name
```

必须改成：

```text
start_station_id
via_station_ids
end_station_id
name
transport_mode
```

---

# 39. Goal Scope

scope：

```text
station_ids = all requested stations

operation_types = [CREATE_LINE]

max_new_lines = 1
```

---

# 40. Satisfaction

不能只检查：

```text
new line name
```

当前 Phase 16 就是这样，太弱。

必须：

```text
new line exists
AND
route matches
```

---

# 41. CREATE_AND_STAFF_LINE_GOAL

这是 Phase 17 必须实现的主业务 Goal。

输入：

```json
{
  "name": "A-D Express",

  "start_station_id": 100,

  "via_station_ids": [
    200,
    300
  ],

  "end_station_id": 400,

  "vehicle_count": 2,

  "vehicle_template_source_line_id": 500
}
```

---

# 42. Planner Steps

不能预生成全部实体 ID。

逻辑：

```text
Step 1 CREATE_LINE
```

成功：

```text
runtime_context.new_line_id
```

然后：

```text
Step 2 BUY
```

成功：

```text
runtime_context.current_new_vehicle_id
```

然后：

```text
Step 3 ASSIGN
```

---

# 43. 多车重复

2 辆：

```text
CREATE
BUY
ASSIGN
BUY
ASSIGN
```

---

# 44. 不提前构造 Step 4/5 实体 ID

每一步都用：

```text
Fresh Snapshot
```

后再生成。

---

# 45. Goal Planner 不应继续存完整静态 planned_steps

当前 TaskOrchestrator 使用：

```text
planned_steps
```

列表。

Phase 17 对动态 multi-entity task 建议改成：

```text
plan_next_step()
```

每次实时产生一个 step。

---

# 46. Dynamic Planner

例如：

```python
plan_next_step(task, index)
```

根据：

```text
runtime_context
requested vehicle_count
assigned_vehicle_ids
```

决定下一步。

---

# 47. CREATE_AND_STAFF 状态

runtime_context：

```json
{
  "new_line_id": 123,

  "purchased_vehicle_ids": [
    456,
    457
  ],

  "assigned_vehicle_ids": [
    456
  ]
}
```

则 Planner 判断：

```text
vehicle 457 尚未 assign
```

下一步：

```text
ASSIGN 457
```

---

# 48. 不用 next_step_index 驱动复杂业务

对动态任务：

```text
状态
```

才是事实。

不是：

```text
固定脚本索引
```

---

# 49. 兼容 Phase 12 simple tasks

rename 等简单 Goal 可以继续原模式。

复杂 Goal 使用：

```text
goal handler.plan_next_step()
```

---

# 50. Vehicle Template Selection

现阶段 BUY 依赖：

```text
source_vehicle_id
```

因此 CREATE_AND_STAFF 需要解决：

```text
参考车型
```

---

# 51. 第一版输入允许

```text
vehicle_template_source_line_id
```

然后选择该线路上的一辆现有 vehicle。

---

# 52. Template Selection 必须 deterministic

例如：

```text
选择 ID 最小的 compatible vehicle
```

可以作为 deterministic fallback。

但要明确：

```text
这是模板选择规则
不是性能最优判断
```

---

# 53. 优先按 Transport Mode 过滤

如果新线路 mode 已知：

模板 vehicle 必须兼容该 mode。

---

# 54. Depot Resolution

从 template vehicle：

```text
raw_depot / depot_id
```

解析。

如果无法确定：

```text
NO_VERIFIED_DEPOT
```

阻塞。

---

# 55. Flagship Live Demo

目标：

```text
A 起点
D 终点
B/C 途经
2 辆车
参考线路 X
```

---

# 56. 完整过程

```text
CREATE A-B-C-D
↓
Fresh Snapshot
↓
new_line_id

BUY #1
↓
Fresh Snapshot
↓
vehicle1

ASSIGN vehicle1 → new_line
↓
Fresh Snapshot

BUY #2
↓
Fresh Snapshot
↓
vehicle2

ASSIGN vehicle2 → new_line
↓
Fresh Snapshot
```

---

# 57. Final Verification

必须：

```text
new line exists

route == A-B-C-D

vehicle1.line_id == new_line

vehicle2.line_id == new_line

assigned_vehicle_count == 2
```

---

# 58. CREATE_LINE_FROM_SOURCE_ROUTE 保留用途

这个 Phase 16 已经验证的能力不要删。

可以作为：

```text
diagnostic / fallback / testing primitive
```

例如：

```text
复制已有线路创建测试 line
```

---

# 59. 但默认用户接口不暴露 source_line_id 模式

正常 AI 新建线路应该使用：

```text
start / via / end
```

---

# 60. P2：SET_LINE_STOPS

当 arbitrary stop builder 成功后，这个能力应该很自然。

核心：

```text
existing line
+
new stop descriptors
```

更新 Line component。

---

# 61. 先找 update API

继续调查：

```text
api.cmd.make.updateLine
```

Phase 16 probe 已经在尝试读取它的 doc。

重点确认真实 signature。

---

# 62. 如果 updateLine 存在

追：

```text
arguments
component structure
```

---

# 63. SET_LINE_STOPS 输入

同样业务化：

```text
line_id
start
via
end
```

---

# 64. 不要求用户传 raw stops

---

# 65. Live Test

只改 Phase 17 临时线路。

例如：

```text
A-B
→
A-C-B
```

---

# 66. Postcondition

fresh snapshot：

```text
route == A-C-B
```

---

# 67. P3：Scheduling

仍然继续，但优先级低于 arbitrary route。

至少继续 source trace：

```text
minimum load
max wait
full load
```

---

# 68. 不因为 Scheduling 未突破阻塞 Phase 17

Phase 17 的硬目标是：

```text
任意已有站点线路创建
+
配车
```

---

# 69. README 更新

当前 README 仍是：

```text
Phase 15 capability matrix
```

必须增加 Phase 16/17。

---

# 70. Capability Matrix 必须真实

至少：

| Operation | Engine | Controller | Task | Live MCP | Product |
|---|---:|---:|---:|---:|---:|
| CREATE_LINE_FROM_SOURCE_ROUTE | Yes | Yes | Yes | ... | ... |
| CREATE_LINE | ... | ... | ... | ... | ... |
| BUY_VEHICLE | Yes | Yes | Yes | Yes | Yes |
| ASSIGN_VEHICLE_TO_LINE | Yes | Yes | Yes | Yes | Yes |

---

# 71. Phase 16 Evidence 补档

当前 capability 写：

```text
Phase 16 live probe:
source line 11833
→ new line 1735075
```

但 release 包中没有结构化 Phase 16 evidence。

必须补成真实目录：

```text
diagnostics/phase16-live/
```

---

# 72. 至少：

```text
create-line-from-source-route/
    before.json
    command.json
    after.json
    verification.json
```

---

# 73. Phase 17 Evidence

```text
diagnostics/phase17-live/
```

---

# 74. Arbitrary A-B evidence

```text
create-line-a-b/
```

---

# 75. Via evidence

```text
create-line-a-b-c/
```

---

# 76. Create-and-staff evidence

```text
create-and-staff/
```

---

# 77. Release Manifest

根目录加入：

```text
RELEASE_MANIFEST.json
```

不能再省略。

---

# 78. Manifest 内容

```text
phase

release name

pytest result

capability statuses

evidence paths

sha256

package layout version
```

---

# 79. evidence_integrity_verified

真正实现。

不要只是概念。

Release builder 自动验证：

```text
evidence file exists
hash valid
```

---

# 80. product_ready

正式改成：

```text
engine_verified
AND controller_supported
AND task_supported
AND live_mcp_verified
AND evidence_integrity_verified
```

---

# 81. CREATE_LINE 当前不能标 Product Ready

即使 Engine create primitive 已验证，

因为：

```text
arbitrary station route
```

尚未实现。

应该：

```text
CREATE_LINE_FROM_SOURCE_ROUTE = verified
CREATE_LINE = not yet verified
```

---

# 82. Tests

新增：

```text
tests/phase17/
```

---

# 83. Unique Capability Test

```python
assert len(operation_types) == len(set(operation_types))
```

防止 Phase 16 的重复 CREATE_LINE 问题。

---

# 84. Stop Resolver Test

测试：

```text
one station one terminal
```

必须 resolve。

---

# 85. Ambiguous Terminal Test

```text
one station two compatible terminals
```

必须：

```text
AMBIGUOUS_TERMINAL
```

---

# 86. Route Model Test

```text
A + [B,C] + D
=
[A,B,C,D]
```

---

# 87. Route Order Test

```text
[A,B,C,D]
!=
[A,C,B,D]
```

---

# 88. CREATE Handler Test

不得出现：

```text
source_line_id
```

依赖。

---

# 89. Legacy Clone Handler Test

单独确保：

```text
CREATE_LINE_FROM_SOURCE_ROUTE
```

仍工作。

---

# 90. New Line Attribution Test

before：

```text
{1,2}
```

after：

```text
{1,2,3}
```

new:

```text
3
```

---

# 91. Ambiguous Attribution

after：

```text
{1,2,3,4}
```

必须 BLOCK。

---

# 92. CREATE_AND_STAFF One Vehicle Test

mutation sequence：

```text
CREATE
BUY
ASSIGN
```

---

# 93. Two Vehicle Test

mutation：

```text
5
```

每次 continue：

```text
1
```

---

# 94. Runtime Context Recovery

server restart 后：

```text
new_line_id
purchased_vehicle_ids
```

不能丢。

---

# 95. Crash after CREATE Test

```text
CREATE sent
↓
game created
↓
server crash
↓
restart
```

必须：

```text
identify line
↓
continue BUY
```

不能再 create。

---

# 96. Release Self-Test

继续要求：

```text
extract ZIP
↓
pytest
```

必须全绿。

---

# 97. Artifact Hygiene

禁止：

```text
__pycache__
*.pyc
.pytest_cache
```

---

# 98. Phase 17 最低验收

必须完成：

1. `CREATE_LINE_FROM_SOURCE_ROUTE` 与真正 `CREATE_LINE` 分离；
2. Capability duplicate 清理；
3. 搞清 `Line.stops` stop descriptor 基本结构；
4. 完成 `LineStopResolver`；
5. 用户可以输入 `start/end` 创建 A-B 线路；
6. 不依赖 `source_line_id`；
7. Fresh Snapshot 识别 new_line_id；
8. route postcondition verified；
9. CREATE_LINE 进入 Controller；
10. CREATE_LINE_GOAL 支持 start/via/end；
11. 正常 MCP Live A-B 创建成功；
12. 完整 pytest 全绿。

---

# 99. 标准验收

在最低标准基础上：

```text
A-B-C via route
```

Live 成功。

并：

```text
CREATE_AND_STAFF_LINE_GOAL
```

至少完成：

```text
CREATE
BUY
ASSIGN
```

一辆车闭环。

---

# 100. 优秀验收

完成：

```text
start=A
via=[B,C]
end=D

vehicle_count=2
```

完整：

```text
CREATE
BUY
ASSIGN
BUY
ASSIGN
```

Live MCP Task：

```text
COMPLETED
```

---

# 101. Stretch

如果 arbitrary stop builder 已经稳定：

继续完成：

```text
SET_LINE_STOPS
```

---

# 102. Phase 17 不做

继续不做：

```text
铺轨
修路
建站
terraform
```

它们与本阶段无关。

---

# 103. 最终 Demo

用户：

```text
以 A 为起点，
D 为终点，
中间停 B、C，
建一条新线路，
配两辆和 X 线路同型的车。
```

最终必须变成：

```text
A → B → C → D
```

真实新线路，

然后：

```text
2 辆新车
```

真实分配到：

```text
new_line_id
```

---

# 104. 最终交付

生成：

```text
tpf2-mcp-phase17-arbitrary-line-route.zip
```

包含：

```text
LineStopResolver

LineRoute model

CREATE_LINE_FROM_SOURCE_ROUTE

真正 CREATE_LINE

dynamic CREATE_AND_STAFF planner

updated Goal system

updated Capability registry

Phase16 evidence cleanup

Phase17 live evidence

RELEASE_MANIFEST.json

full tests

PHASE17_ARBITRARY_LINE_ROUTE.md
```

---

# 105. 本阶段最重要判断标准

Phase 17 不看：

```text
能不能复制一条已有线路
```

而看：

```text
用户给出任意已有站点组合
↓
MCP 能构造真实 TPF2 stops
↓
创建新运营线路
↓
配车
↓
Fresh Snapshot 验证
```

只有做到这一点，

```text
CREATE_LINE
```

才真正算完成。