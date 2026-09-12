# TPF2 MCP Phase 4：运营指标、财务与产业流分析

Phase 3 已通过。

当前已真实建立：

```text
Town             37
Industry         83
Station Group    178
Line             96
Vehicle          262
Company          1

Line → Station Group
Vehicle → Line
Line → Vehicle
Station Group → Line
```

关系完整性：

```text
Line stop references:
404 / 404 resolved

Vehicle line references:
0 broken
```

当前主要 UNKNOWN：

```text
transport mode
industry type
industry production
industry shipment
company money
line financial metrics
station waiting
vehicle capacity/load
```

Phase 4 核心目标：

```text
从“交通网络结构”
升级为
“交通网络运行状态”。
```

---

## 1. 先修复 Snapshot 一致性问题

当前：

```text
get_town
```

仍可能直接调用 Bridge，而其他 entity 查询通过 SnapshotIndex。

统一：

```text
get_town
get_industry
get_station
get_line
get_vehicle
```

全部使用同一个：

```text
SnapshotIndex
```

禁止单个查询绕开当前缓存 Snapshot。

同一 MCP 分析过程应尽可能看到同一个：

```text
snapshot sequence
```

---

## 2. Snapshot Cache 改进

当前：

```text
SNAPSHOT_CACHE_SECONDS = 60
```

偏长。

改为配置项：

```text
TPF2_MCP_SNAPSHOT_CACHE_SECONDS
```

默认：

```text
5~10 秒
```

增加：

```text
snapshot_sequence
snapshot_age_ms
```

到 MCP overview。

如果可行，部分 Tool 增加：

```text
force_refresh: boolean
```

但保持默认轻量。

---

# 3. 运营字段调研必须坚持 Probe First

不要先假设字段名。

分别针对：

```text
Vehicle
Line
Station
Station Group
Industry
Account
```

建立独立 semantic probe。

所有 probe 输出：

```text
component
field
type
sample value
entity_id
```

禁止因为字段名看起来合理就直接正式暴露。

---

# 4. Vehicle 运营数据

优先研究车辆相关公开 component/system。

目标字段按优先级：

```text
P0:
capacity
current load / occupancy
cargo/passenger type

P1:
speed
state
position
age

P2:
maintenance
condition
purchase value
running cost
```

第一目标是回答：

```text
这辆车现在有多满？
```

目标 Normalize：

```json
{
  "entity_id": 123,
  "line_id": 456,

  "capacity": 120,
  "load": 88,
  "occupancy_ratio": 0.7333
}
```

注意：

```text
occupancy_ratio
```

必须是派生字段：

```text
load / capacity
```

原始值仍保留。

---

# 5. 不同货物必须保留 Cargo Breakdown

如果车辆可同时携带不同货物：

不要只返回：

```text
load = 40
```

应尽量：

```json
{
  "cargo": [
    {
      "cargo_type": "...",
      "amount": 30
    },
    {
      "cargo_type": "...",
      "amount": 10
    }
  ],

  "load_total": 40
}
```

无法取得 cargo 类型时明确 UNKNOWN。

---

# 6. Line 运营数据

研究是否存在公开：

```text
frequency
rate
travel time
vehicle count
financial statistics
```

其中：

```text
vehicle_count
```

已有可靠派生值。

目标：

```json
{
  "line_id": 123,

  "vehicle_count": 5,

  "frequency_seconds": 120,

  "rate": 90,

  "average_load": 0.74
}
```

任何字段必须实际验证。

---

# 7. Average Line Occupancy

如果单车 capacity/load 可得，则 Python 分析层派生：

```text
line occupancy
```

例如：

```text
sum(vehicle.load)
-----------------
sum(vehicle.capacity)
```

或者同时提供：

```text
simple_vehicle_average
capacity_weighted_average
```

明确公式。

不要含糊叫：

```text
utilization
```

---

# 8. Station 等待数据

重点研究：

```text
Station
Station Group
Cargo waiting
Passenger waiting
```

目标：

```json
{
  "station_id": 123,

  "waiting_total": 203,

  "waiting": [
    {
      "cargo_type": "PASSENGERS",
      "amount": 180
    },
    {
      "cargo_type": "FOOD",
      "amount": 23
    }
  ]
}
```

如果数据实际绑定：

```text
STATION
```

而不是：

```text
STATION_GROUP
```

则内部聚合：

```text
Station entities
→ Station Group
```

不要破坏 MCP 用户层的 Station Group 语义。

---

# 9. Station Congestion 先只提供客观指标

暂时不要让：

```text
waiting > X
```

直接等于：

```text
拥堵
```

第一版 Tool：

```text
get_station_load
```

返回客观值。

然后可增加：

```text
find_high_waiting_stations
```

使用可配置阈值：

```text
waiting_threshold
```

明确：

```text
这是规则筛选，不是 TPF2 官方拥堵定义。
```

---

# 10. Company Finance

继续研究：

```text
ACCOUNT
PLAYER
```

当前：

```text
loan = verified
money = UNKNOWN
```

系统性检索公开 API 中：

```text
account
balance
money
cash
finance
company
player
loan
```

目标：

```json
{
  "money": 12345678,
  "loan": 5000000
}
```

如果 money 最终仍不可获得：

保持 unavailable。

禁止：

```text
内存地址
DLL 注入
外挂式内存读取
```

Phase 4 仍然基于官方 Mod/Game Script 能力。

---

# 11. Line 财务数据

研究是否存在：

```text
line revenue
line running cost
line profit
```

如果不存在直接 Line 财务：

尝试从：

```text
vehicle finance statistics
```

聚合。

例如：

```text
line revenue
=
sum(vehicle revenue)
```

但仅在 API 语义明确时实现。

---

# 12. 时间窗口必须明确

财务指标不能只叫：

```text
profit
```

必须注明：

```text
lifetime
current year
last 12 months
game period
```

如果 TPF2 返回数组/历史窗口：

完整保留：

```text
raw finance history
```

然后 Python 侧派生。

---

# 13. Industry 类型继续调研

当前：

```text
industry_type = UNKNOWN
```

不要使用显示名称解析作为正式实现。

继续研究：

```text
SIM_BUILDING
CONSTRUCTION
BASE_EDGE
MODEL_INSTANCE
```

以及可能的：

```text
api.engine.system.simBuildingSystem
```

公开接口。

目标优先找到：

```text
construction/config identifier
```

只要拿到类似：

```text
industry/oil_refinery.con
```

就足以构造稳定 Industry Type。

---

# 14. Industry 生产数据

目标调研：

```text
production
shipment
transport
stock
input
output
```

首先只确认原始公开字段。

目标模型：

```json
{
  "entity_id": 123,

  "production": 200,
  "shipment": 170,
  "transport_percentage": 0.85
}
```

不要自行把：

```text
shipment / production
```

叫 TPF2 的：

```text
transport_percentage
```

除非游戏语义就是这样。

如果是派生指标，命名：

```text
derived_shipment_ratio
```

---

# 15. Cargo Type Registry

Phase 4 必须开始系统调查 Cargo Type。

不要硬编码完整 cargo 列表。

优先查询：

```text
api.res.cargoTypeRep
```

或实际当前版本对应 registry。

如果官方 registry 可枚举：

构建：

```text
cargo_id
internal_name
display_name
```

Normalize。

目标：

```json
{
  "cargo_id": 3,
  "cargo_key": "COAL",
  "display_name": "Coal"
}
```

---

# 16. 第一版经营分析只能建立在真实字段上

新增：

```text
get_vehicle_operating_state
get_line_operating_state
get_station_operating_state
```

这些 Tool 主要汇总数据，不作复杂判断。

---

# 17. Line Occupancy Ranking

在 load/capacity 验证后增加：

```text
rank_lines_by_occupancy
```

返回：

```text
line_id
name
load
capacity
occupancy_ratio
vehicle_count
```

可以排序：

```text
ascending
descending
```

---

# 18. Empty / Low-load Vehicle Analysis

在数据支持后新增：

```text
find_low_load_vehicles
```

参数：

```text
occupancy_threshold
```

例如：

```text
0.2
```

这是确定性筛选。

---

# 19. High Waiting Station Analysis

数据支持后：

```text
find_high_waiting_stations
```

参数：

```text
waiting_threshold
```

返回：

```text
station
waiting
served_lines
```

---

# 20. Line Operational Summary

扩展当前：

```text
get_line_summary
```

不要破坏旧结构。

新增：

```text
get_line_operating_summary
```

目标：

```json
{
  "line": {},

  "stations": [],

  "vehicles": [],

  "operations": {
    "vehicle_count": 5,
    "capacity": 600,
    "load": 470,
    "occupancy_ratio": 0.783,
    "frequency_seconds": 120
  },

  "finance": {
    "revenue": null,
    "cost": null,
    "profit": null
  }
}
```

未知字段使用：

```text
null
```

并提供：

```text
availability
```

避免 Agent 将 null 当成 0。

---

# 21. Availability Metadata

这一阶段开始正式加入：

```json
{
  "availability": {
    "capacity": true,
    "load": true,
    "frequency": false,
    "revenue": false
  }
}
```

避免 UNKNOWN 数据和真实 0 混淆。

---

# 22. Analysis Result 必须带 Evidence

例如：

```text
find_low_load_vehicles
```

结果：

```json
{
  "vehicle_id": 123,

  "reason": "OCCUPANCY_BELOW_THRESHOLD",

  "evidence": {
    "load": 10,
    "capacity": 80,
    "occupancy_ratio": 0.125,
    "threshold": 0.2
  }
}
```

不要只返回：

```text
车辆利用率低
```

---

# 23. MCP Tool 分层

保持：

```text
RAW
get_vehicle
get_line
get_station

DOMAIN
get_vehicle_operating_state
get_line_operating_summary

ANALYSIS
find_low_load_vehicles
find_high_waiting_stations
```

不要混成几十个含义重复 Tool。

---

# 24. 手工 UI 对照验证必须真正做一次

上一阶段：

```text
semantic-verification.json
```

只是 Snapshot 内部一致性验证。

Phase 4 至少选择：

```text
3 lines
3 vehicles
3 stations
```

人工从 TPF2 UI 记录：

```text
name
vehicle count
stop count

capacity/load（如 UI 可见）

station waiting（如 UI 可见）

line frequency（如 UI 可见）
```

保存：

```text
diagnostics/ui-ground-truth.json
```

然后由：

```text
verify-ui-ground-truth.py
```

与 MCP 数据比较。

明确区分：

```text
INTERNAL CONSISTENCY
LIVE API
UI CROSS-CHECK
```

---

# 25. Transport Mode 继续 Probe，但不要阻塞 Phase 4

仍然研究：

```text
ROAD
RAIL
WATER
AIR
```

来源。

可以检查：

```text
vehicle model/config
carrier component
line vehicleInfo
station type
```

但如果仍无法可靠取得：

继续：

```text
UNKNOWN
```

不要阻塞 occupancy/finance 等其他指标。

---

# 26. 当前 network Tool 小修

增加：

```text
find_stations_without_lines
```

因为当前已经真实检测到：

```text
9 station groups without lines
```

同时保留：

```text
find_lines_without_vehicles
find_unassigned_vehicles
```

---

# 27. `find_suspicious_lines` 补 Live MCP 测试

当前实现已有：

```text
STOP_COUNT_LE_1
NO_VEHICLES
VEHICLE_COUNT_ABOVE_THRESHOLD
```

增加实际：

```text
tools/call find_suspicious_lines
```

到 Live MCP 会话。

即使结果：

```text
[]
```

也要留档。

---

# 28. Phase 4 暂时仍然 READ ONLY

禁止：

```text
buy vehicle
sell vehicle
edit line
build station
build track
take loan
change game state
```

只有运营读取稳定之后才进入 write phase。

---

# 29. Phase 4 第一优先级顺序

严格按照：

```text
Vehicle capacity/load
        ↓
Station waiting
        ↓
Line operational aggregation
        ↓
Company finance
        ↓
Industry production/shipment
        ↓
Cargo semantics
```

原因：

```text
Vehicle + Station
```

最容易直接产生有价值的运输运营分析。

---

# 30. Phase 4 最终目标

完成后 Agent 至少应能回答：

```text
哪几条线路车辆平均载荷最低？
```

```text
哪些站目前积压最多？
```

```text
线路 23 当前 5 辆车的运力和载荷怎么样？
```

```text
有没有大量空跑的车辆？
```

如果财务 API 成功：

```text
哪些线路可能是亏损来源？
```

如果产业 API 成功：

```text
哪些产业生产高但运输不足？
```

---

# 31. Phase 4 交付物

提交：

```text
1. 所有 semantic probe 结果

2. vehicle operations collector

3. station operations collector

4. line operations aggregation

5. company finance probe

6. industry production probe

7. cargo registry probe

8. availability metadata

9. get_vehicle_operating_state

10. get_station_operating_state

11. get_line_operating_summary

12. find_low_load_vehicles

13. find_high_waiting_stations

14. find_stations_without_lines

15. UI ground truth

16. UI verification report

17. Live MCP session

18. Python tests

19. stdout.txt

20. UNKNOWN / unavailable 字段清单
```

本阶段结束后停止，不要进入写操作。

核心目标：

```text
让 MCP 不仅知道“网络怎么连接”，
还开始知道“网络现在运行得怎么样”。
```