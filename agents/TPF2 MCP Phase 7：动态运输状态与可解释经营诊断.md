# TPF2 MCP Phase 7：动态运输状态与可解释经营诊断

Phase 6 已验收通过。

当前已完成 UI Cross Verification：

```text
vehicle.capacity_total
    ← TRANSPORT_VEHICLE.config.capacities

line.frequency_seconds
    ← 1 / game.interface.getEntity(line_id).frequency

line.throughput
    ← game.interface.getEntity(line_id).rate
```

当前 ENGINE VERIFIED：

```text
company.balance
company.loan
```

当前动态运营 UNKNOWN：

```text
vehicle.current_load
station.waiting
line.revenue
line.cost
line.profit
industry.production
industry.shipment
```

Phase 7 核心目标：

```text
找到“动态运输状态”的可靠结构化数据源，
并在此基础上建立第一批可解释经营诊断。
```

本阶段仍为：

```text
READ ONLY
```

---

## 1. 保留 Source Confidence Model

所有字段必须继续使用以下状态之一：

```text
UI_CROSS_VERIFIED
ENGINE_VERIFIED
ENGINE_AVAILABLE
SOURCE_TRACE_ONLY
UI_ONLY
UNRESOLVED
```

禁止将：

```text
UI_ONLY
```

字段直接暴露为可靠 MCP 数据。

新增字段必须同步更新：

```text
ui-data-source-map.md
```

---

# 2. 第一优先级：Vehicle Current Load

这是本阶段最高优先级。

目标找到：

```text
当前车辆实际承载人数/货量
```

不要和：

```text
TRANSPORT_VEHICLE.config.capacities
```

混淆。

重点研究已经确认存在的：

```text
api.engine.system.transportVehicleSystem
api.engine.system.simCargoSystem
```

以及与车辆相关的公开 component。

采用：

```text
probe first
```

策略。

---

# 3. 不允许无界枚举未知函数

不要：

```text
遍历 system userdata
→ 对所有字段尝试调用
```

先从：

```text
官方 API 文档
安装游戏 Lua 脚本
UI Lua 源码
```

寻找已知调用点。

然后对明确 candidate 做：

```text
pcall
```

验证。

---

# 4. 建立 UI Source Code Index

当前已有：

```text
tools/index-tpf2-lua-sources.py
```

继续完善。

针对安装目录：

```text
res/scripts/
```

建立可搜索索引。

重点搜索关键词：

```text
capacity
cargo
load
waiting
waitingCargo
passenger
rate
frequency
income
profit
balance
loan
station
vehicle
line
```

输出：

```text
diagnostics/ui-source-index.json
```

每项保存：

```text
file
line
snippet
symbol
```

---

# 5. Vehicle Load Source Trace

优先搜索游戏自己的：

```text
vehicle manager
vehicle detail
line manager
```

UI Lua。

目标找出：

```text
UI 显示车辆当前货物/人数
```

所读取的实际字段。

建立：

```text
vehicle-load-source-trace.md
```

包括：

```text
UI file
UI field
underlying call
entity ID mapping
candidate engine source
```

---

# 6. Vehicle Load Live Probe

找到 candidate 后：

选择至少：

```text
3 个不同车辆
```

最好覆盖：

```text
低载荷
中载荷
高载荷
```

在游戏暂停状态下记录：

```text
vehicle entity_id
vehicle name
UI load
UI capacity
cargo/passenger
```

同时采集 engine source。

生成：

```text
vehicle-load-binding-verification.json
```

只有：

```text
3/3
```

单位和语义一致时才升级：

```text
UI_CROSS_VERIFIED
```

---

# 7. Vehicle Operating Model

成功后：

```json
{
  "capacity_total": 260,
  "load_total": 173,

  "occupancy_ratio": 0.6653846,

  "availability": {
    "capacity": true,
    "load": true,
    "occupancy_ratio": true
  }
}
```

其中：

```text
occupancy_ratio
=
load_total / capacity_total
```

明确标：

```text
DERIVED
```

不是原始游戏字段。

---

# 8. Cargo Breakdown

如果底层数据允许：

```json
{
  "cargo": [
    {
      "cargo_id": 3,
      "cargo_name": "...",
      "amount": 70
    }
  ]
}
```

必须通过当前动态：

```text
cargo_types
```

解析。

不要硬编码 cargo ID。

---

# 9. 第二优先级：Station Waiting

继续针对：

```text
stationSystem
simCargoSystem
```

但必须先从：

```text
官方/安装 UI Lua
```

找到已知调用路径。

目标：

```text
station entity
→ waiting cargo/passenger
```

如果 waiting 数据绑定单个：

```text
STATION
```

MCP 层聚合到：

```text
STATION_GROUP
```

---

# 10. Station Group 聚合规则

如果一个 Station Group 下有：

```text
N station entities
```

定义：

```text
waiting_total
=
sum(each station waiting)
```

Cargo breakdown：

```text
按 cargo_id 聚合
```

目标：

```json
{
  "entity_id": 6493,

  "waiting_total": 218,

  "waiting": [
    {
      "cargo_id": 0,
      "amount": 170
    },
    {
      "cargo_id": 5,
      "amount": 48
    }
  ]
}
```

---

# 11. Station Waiting UI Cross Check

至少验证：

```text
3 station groups
```

必须使用：

```text
same save
paused
same simulation state
```

防止等待数量实时变化。

输出：

```text
station-waiting-binding-verification.json
```

---

# 12. Line Dynamic Aggregation

当车辆 load 可用后：

建立：

```text
line_capacity_total
line_load_total
line_occupancy_ratio
```

定义：

```text
line_capacity_total =
sum(vehicle.capacity_total)

line_load_total =
sum(vehicle.load_total)

line_occupancy_ratio =
line_load_total / line_capacity_total
```

这属于：

```text
current snapshot aggregate
```

不要叫：

```text
average historical occupancy
```

---

# 13. 区分 Throughput 和 Current Load

必须在文档明确：

```text
throughput
!=
current load
```

其中：

```text
throughput
```

来自：

```text
line.rate
```

而：

```text
current_load
```

来自当前车辆状态聚合。

不得混淆。

---

# 14. 建立 Line Operating Summary v2

扩展：

```text
get_line_operating_summary
```

目标：

```json
{
  "operations": {
    "vehicle_count": 5,

    "frequency_seconds": 331.25,

    "throughput": 406,

    "capacity_total": 920,

    "load_total": 610,

    "occupancy_ratio": 0.663
  }
}
```

所有字段同时提供：

```text
availability
source/confidence
```

---

# 15. 第三优先级：Line Finance Source Trace

不要直接 Probe 随机 field。

重点搜索 TPF2 UI Lua 中：

```text
line income
line finances
line statistics
vehicle finances
```

当前已经有 UI Ground Truth：

```text
线路91  +5,906,462
线路29    -958,495
线路35 +30,288,364
```

找到真正 UI binding。

---

# 16. 必须先确认 UI 金额语义

UI 上的金额可能是：

```text
annual profit
rolling period profit
balance
revenue - maintenance
```

必须先确定实际定义。

不要直接命名：

```text
profit
```

直到来源代码证明语义。

---

# 17. Finance 字段命名规则

如果发现的是：

```text
transport_result
```

就保持：

```text
transport_result
```

不要擅自变成：

```text
profit
```

如果是某个时间窗口：

```text
last_12_months
```

必须写入字段名或 metadata。

---

# 18. Company Balance UI Cross Verification

当前：

```text
ACCOUNT.balance
game.interface player.balance
```

已经 engine cross verified。

本轮补：

```text
Finance UI cash display
```

至少记录：

```text
1 个 same-save paused sample
```

由于两个 Engine Source 已经互相吻合，只需完成语义确认。

成功后：

```text
company.balance
→ UI_CROSS_VERIFIED
```

Loan 同理。

---

# 19. Industry 先继续 Source Trace，不强求突破

本阶段核心仍然是动态运输状态。

Industry：

```text
production
shipment
transport
```

继续搜索：

```text
industry UI Lua
```

但如果仍找不到：

```text
不阻塞 Phase 7
```

---

# 20. 第一个真正的经营诊断：Low Load

Vehicle load 成功后启用：

```text
find_low_load_vehicles
```

规则：

```text
occupancy_ratio < threshold
```

输出必须：

```json
{
  "reason": "CURRENT_OCCUPANCY_BELOW_THRESHOLD",

  "evidence": {
    "load_total": 15,
    "capacity_total": 100,
    "occupancy_ratio": 0.15,
    "threshold": 0.2
  }
}
```

---

# 21. 不可用字段不能产生“空即正常”

如果：

```text
load unavailable
```

则：

```text
find_low_load_vehicles
```

不能简单返回：

```json
[]
```

必须返回类似：

```json
{
  "status": "UNAVAILABLE",
  "reason": "VEHICLE_LOAD_NOT_AVAILABLE",
  "items": []
}
```

同理：

```text
find_high_waiting_stations
```

如果 waiting 不可用：

```text
status = UNAVAILABLE
```

---

# 22. High Waiting Stations

Waiting 成功后：

```text
find_high_waiting_stations
```

输出：

```text
station
waiting_total
served_lines
threshold
evidence
```

这是规则筛选。

不要叫：

```text
官方拥堵状态
```

---

# 23. Line Capacity Pressure

Vehicle load + Station waiting 都可用后增加：

```text
analyze_line_capacity_pressure
```

只使用明确规则。

例如考虑：

```text
occupancy
waiting
frequency
throughput
```

输出不是一句：

```text
建议加车
```

而是：

```json
{
  "classification": "HIGH_PRESSURE",

  "evidence": {
    "occupancy_ratio": 0.92,
    "max_station_waiting": 281,
    "frequency_seconds": 420,
    "throughput": 106
  }
}
```

阈值必须配置。

---

# 24. Recommendations 必须与 Observations 分离

Phase 7 可以开始生成：

```text
diagnosis
```

但不要让底层分析直接执行。

格式：

```json
{
  "observations": [],
  "diagnosis": [],
  "recommendations": []
}
```

例如：

```text
Observation:
occupancy 96%

Observation:
station waiting 340

Diagnosis:
capacity pressure

Recommendation:
consider increasing capacity
```

---

# 25. Agent 不得把规则结论说成游戏真理

例如：

```text
HIGH_PRESSURE
```

必须说明：

```text
TPF2 MCP heuristic
```

而不是：

```text
Transport Fever 2 官方定义的拥堵线路
```

---

# 26. Dynamic Metrics Freshness

Phase 7 开始，5~10 秒缓存对动态数据可能仍偏长。

增加：

```text
snapshot_age_ms
```

所有 Operating Tool 返回。

例如：

```json
{
  "snapshot": {
    "sequence": 17,
    "age_ms": 823
  }
}
```

---

# 27. force_refresh

动态 Tool 支持：

```text
force_refresh=true
```

至少：

```text
get_vehicle_operating_state
get_station_operating_state
get_line_operating_summary
```

这样 Agent 在用户明确说：

```text
“我刚刚加了一辆车，再看一下”
```

时可以强制刷新。

---

# 28. Live Dynamic Test

建立专门动态验收。

测试流程：

```text
游戏暂停
↓
读取 A
↓
记录 UI/API

恢复游戏一段时间
↓
再次暂停
↓
读取 B
```

确认：

```text
frequency/load/waiting
```

等动态值确实更新，而不是旧缓存。

输出：

```text
dynamic-refresh-verification.json
```

---

# 29. 不进入 Write Phase

禁止：

```text
buy_vehicle
sell_vehicle
change_line
build
loan
pause
```

即使已经能诊断：

```text
“应该加车”
```

也只能返回建议。

---

# 30. Phase 7 最终最低目标

至少突破以下两个中的一个：

```text
Vehicle Current Load
Station Waiting
```

理想情况两个都突破。

并真正做到：

```text
哪几辆车现在空载/低载？
```

或者：

```text
哪些车站现在积压最多？
```

如果两个都没有找到可靠底层数据源：

Phase 7 不算失败。

但必须提交：

```text
完整 UI source trace
candidate API
失败证据
为什么当前公开 Mod API 无法可靠取得
```

不得伪造数据。

---

# 31. Phase 7 交付物

提交：

```text
1. ui-data-source-map.md 更新

2. UI Lua source index

3. vehicle-load-source-trace.md

4. station-waiting-source-trace.md

5. line-finance-source-trace.md

6. vehicle-load-binding-verification.json
   （如成功）

7. station-waiting-binding-verification.json
   （如成功）

8. company-balance-binding-verification.json

9. dynamic-refresh-verification.json

10. Line Operating Summary v2

11. Low-load analysis

12. High-waiting analysis

13. Capacity-pressure analysis
    （数据足够时）

14. Live MCP session

15. Python tests

16. stdout.txt

17. UNKNOWN / UI_ONLY 字段清单
```

Phase 7 的核心原则：

```text
宁愿返回 unavailable，
也不要把“看起来像这个值”的字段当成可靠经营指标。
```