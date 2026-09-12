# TPF2 MCP Phase 3：交通网络语义与运营分析

Phase 2.1 已通过验收。

真实 TPF2 数据：

```text
Town        37
Industry    83
Station     178
Line        96
Vehicle     262
Company     1
```

已验证：

```text
Town Collector
Industry Collector
Station Collector
Line Collector
Vehicle Collector
Company Collector

World Snapshot

vehicle.line_id → line.entity_id

UTF-8 end-to-end

Live MCP:
get_game_state
get_towns/get_town
get_industries/get_industry
get_stations/get_station
get_lines/get_line
get_vehicles/get_vehicle
```

Phase 3 不再扩展基础实体数量。

本阶段核心目标：

```text
将“实体列表”升级为“交通网络语义模型”。
```

最终让 MCP 能理解：

```text
Line
 ↕
Vehicle

Line
 ↕
Stop / Station

Station
 ↕
Lines

Industry
 ↕
Cargo / Transport

Company
 ↕
Economy
```

---

# 1. 第一优先级：Line Semantic Collector

当前 Line：

```json
{
  "entity_id": 11833,
  "name": "线路 3",
  "stop_count": 2
}
```

需要进一步研究 LINE component 的真实 userdata。

目标增加：

```text
transport_mode
stops
vehicle_count
```

目标结构：

```json
{
  "entity_id": 11833,
  "entity_type": "line",
  "name": "线路 3",

  "transport_mode": "RAIL",

  "stops": [
    {
      "index": 0,
      "station_id": 123
    },
    {
      "index": 1,
      "station_id": 456
    }
  ],

  "stop_count": 2,

  "vehicle_ids": [
    111,
    222
  ],

  "vehicle_count": 2
}
```

所有字段必须来自实际验证。

如果 LINE stop 保存的不是 station group entity，则记录真实类型。

---

# 2. Line → Vehicle 关系

目前已有：

```text
Vehicle.line_id
```

因此不要重复依赖未知 API。

构建反向索引：

```text
line_id
→ vehicle_ids[]
```

可以在 Python Snapshot Index 层完成。

不要让 Lua 重复扫描。

建立：

```python
SnapshotIndex
```

至少包含：

```text
town_by_id
industry_by_id
station_by_id
line_by_id
vehicle_by_id

vehicles_by_line
```

---

# 3. Station Semantic Model

当前：

```json
{
  "entity_id": 6493,
  "name": "Camorino",
  "station_count": 1
}
```

研究：

```text
STATION_GROUP
STATION
```

关系。

必须明确 MCP 中：

```text
station
```

到底表示：

```text
Station Group
```

还是：

```text
individual station
```

建议 MCP 用户层优先采用：

```text
Station Group
```

因为它更符合玩家看到的“车站”。

内部可以：

```json
{
  "entity_id": 6493,
  "entity_type": "station_group",

  "station_ids": [
    ...
  ]
}
```

---

# 4. Station → Lines

建立：

```text
station_id
→ line_ids[]
```

如果无法直接从 Station API 取得，则：

```text
遍历 Line stops
→ 构建 reverse index
```

不要重复调用昂贵的 engine API。

目标：

```json
{
  "entity_id": 6493,
  "name": "Camorino",

  "line_ids": [
    11833,
    29350
  ],

  "line_count": 2
}
```

---

# 5. 验证 Line Stop Reference

建立 integrity test：

```text
所有 line.stops
```

对应 station reference 必须能够解析。

报告：

```text
resolved
unresolved
```

例如：

```text
Line stop references .... PASS
96 lines
423 stops
423 resolved
0 unresolved
```

如果实际 stop 指向：

```text
STATION
```

而不是：

```text
STATION_GROUP
```

则明确建立映射：

```text
station entity
→ station group
```

禁止强行把二者当同一种 ID。

---

# 6. Vehicle Semantic Collector

当前：

```text
entity_id
name
line_id
```

继续研究：

```text
transport mode
vehicle type/model
capacity
cargo/passenger load
position
state
age
maintenance
```

但本阶段第一批只强制：

```text
transport_mode
line_id
```

如果能安全获得，再逐步增加。

---

# 7. Transport Mode Normalization

不要直接把 TPF2 内部 enum 暴露给 Agent。

统一映射：

```text
ROAD
TRAM
BUS
TRUCK
RAIL
WATER
AIR
UNKNOWN
```

如果 TPF2 API 无法可靠区分：

```text
BUS / TRUCK
```

则采用更高层：

```text
ROAD
```

禁止猜测。

所有原始值可保留：

```json
{
  "transport_mode": "RAIL",
  "raw_transport_mode": 3
}
```

---

# 8. Line Summary Tool

新增 MCP：

```text
get_line_summary
```

参数：

```text
line_id
```

返回：

```json
{
  "line": {},
  "stations": [],
  "vehicles": [],

  "summary": {
    "stop_count": 6,
    "vehicle_count": 4,
    "transport_mode": "RAIL"
  }
}
```

Agent 不需要自己调用：

```text
get_line
get_vehicle
get_station
...
```

几十次。

---

# 9. Transport Network Summary

新增：

```text
get_transport_network_summary
```

返回：

```text
line_count

station_count

vehicle_count

lines_by_mode

vehicles_by_mode

unassigned_vehicle_count

lines_without_vehicles

stations_without_lines
```

例如：

```json
{
  "line_count": 96,

  "lines_by_mode": {
    "RAIL": 42,
    "ROAD": 38,
    "WATER": 8,
    "AIR": 8
  },

  "vehicle_count": 262,

  "unassigned_vehicle_count": 3
}
```

---

# 10. 查找没有车辆的线路

新增：

```text
find_lines_without_vehicles
```

这属于 deterministic analysis。

不需要 LLM 推测。

逻辑：

```text
line
→ vehicles_by_line
→ count == 0
```

---

# 11. 查找未分配车辆

新增：

```text
find_unassigned_vehicles
```

检测：

```text
line_id == null
```

或：

```text
line_id 无法解析
```

区分：

```text
UNASSIGNED

BROKEN_REFERENCE
```

---

# 12. Line Stop Count / Vehicle Count 基础异常

暂时可以提供：

```text
find_suspicious_lines
```

只做明确规则：

```text
stop_count == 0

stop_count == 1

vehicle_count == 0

vehicle_count > configurable threshold
```

不要现在判断：

```text
这条线路一定亏损
```

因为还没有财务数据。

---

# 13. Company Finance Research

继续研究：

```text
ACCOUNT
PLAYER
```

已验证：

```text
loan
```

可读取。

money 当前为：

```text
nil
```

本阶段继续搜索公开 API：

```text
money
balance
cash
account
finance
```

只允许：

```text
公开脚本 API
公开 component
公开 game system
```

禁止：

```text
内存扫描
DLL 注入
硬编码地址
```

如果仍然无法取得：

```text
money = unavailable
```

即可。

---

# 14. Industry Semantic Probe

当前 Industry 只有：

```text
entity_id
name
```

开始研究：

```text
SIM_BUILDING
PRODUCTION
INDUSTRY
```

等相关 component/system。

目标找到：

```text
input cargo
output cargo
production
shipment
transport percentage
```

但本阶段不用全部实现。

首先完成：

```text
industry type
```

不要仅靠：

```text
name contains "Oil refinery"
```

解析产业类型。

必须优先找到实际 construction/config/component 来源。

---

# 15. Industry Type Normalization

目标：

```json
{
  "entity_id": 8494,

  "industry_type": "OIL_REFINERY",

  "name": "Serocca Oil refinery"
}
```

同时保留：

```text
raw identifier
```

例如：

```json
{
  "industry_type": "OIL_REFINERY",
  "industry_config": "industry/oil_refinery.con"
}
```

如果 API 可取得。

---

# 16. Cargo Semantic Model

建立统一 cargo model：

```text
CRUDE
OIL
FUEL

IRON_ORE
COAL
STEEL

LOGS
PLANKS
TOOLS

GRAIN
FOOD

STONE
CONSTRUCTION_MATERIAL

PLASTIC
MACHINES
GOODS
```

实际名称必须以 TPF2 当前 cargo config 为准。

不要凭记忆直接硬编码并假设完整。

需要读取：

```text
cargo type registry/config/API
```

之后生成 normalization mapping。

---

# 17. Supply Chain Graph

Industry type 成功之后建立：

```text
IndustryNode
CargoEdge
```

例如：

```text
Oil Well
   │ CRUDE
   ▼
Oil Refinery
   │ OIL
   ▼
Fuel Refinery
   │ FUEL
   ▼
Town
```

本阶段先做结构：

```text
producer
consumer
cargo
```

不做自动线路推荐。

---

# 18. MCP Resource 调整

增加：

```text
tpf2://network
tpf2://network/lines
tpf2://network/stations
tpf2://network/vehicles
```

以及：

```text
tpf2://industries/graph
```

仅当 supply chain graph 稳定以后开放。

---

# 19. Snapshot 不应该越来越巨大

当前：

```text
get_game_state
```

直接返回整个 World Snapshot。

已经开始变大。

本阶段开始拆分：

```text
get_game_state
```

只返回：

```text
game
company
metadata
counts
```

不要默认返回全部：

```text
262 vehicles
178 stations
...
```

新增：

```text
get_world_snapshot
```

专门返回完整 snapshot。

---

# 20. Collection Query

新增 Bridge/Python query：

```text
get_collection
```

例如：

```json
{
  "collection": "vehicles"
}
```

以及：

```text
get_entity
```

例如：

```json
{
  "collection": "vehicles",
  "entity_id": 8055
}
```

避免：

```text
get_vehicle
→ 先传整个 World Snapshot
→ Python 再筛选
```

---

# 21. 但不要过早复杂化 Lua Bridge

优先在 Python 缓存完整：

```text
state.json
```

然后：

```text
get_vehicle
```

从 Python Snapshot cache 查询。

如果实际性能仍然很好：

```text
不要增加新的 Lua commands。
```

先测性能，再决定。

---

# 22. Snapshot Index

新增：

```python
class SnapshotIndex:
```

一次 Snapshot 构建：

```text
town_by_id
industry_by_id
station_by_id
line_by_id
vehicle_by_id

vehicles_by_line
lines_by_station
```

MCP 查询必须：

```text
O(1)
```

或接近 O(1)。

不要每次线性扫描：

```text
262 vehicles
96 lines
178 stations
```

虽然当前规模小，但这是正确的数据层设计。

---

# 23. Snapshot Version

开始区分：

```text
snapshot schema version
```

如果增加大量关系字段：

```text
schema_version = 2
```

不要悄悄改变：

```text
schema_version = 1
```

的语义。

编写：

```text
docs/snapshot-schema-v2.md
```

---

# 24. Live Test

建立真实关系验证。

至少选择：

```text
3 条线路
```

覆盖：

```text
road
rail
其他模式
```

如果当前存档存在。

人工在游戏 UI 中记录：

```text
line name
stops
vehicles
```

然后和 MCP 对比。

生成：

```text
diagnostics/semantic-verification.json
```

例如：

```json
{
  "line_id": 29350,

  "expected": {
    "name": "线路 23",
    "stop_count": 2,
    "vehicle_count": 3
  },

  "observed": {},

  "result": "PASS"
}
```

---

# 25. 暂时禁止

Phase 3 暂时不要：

```text
自动建铁路

自动建车站

自动买车

自动卖车

自动修改线路

自动贷款

自动经营

LLM 自主操作游戏
```

依然：

```text
READ ONLY
```

---

# 26. Phase 3 最终目标

完成后用户可以问：

```text
线路 23 有哪些站和哪些车辆？
```

Agent：

```text
get_line_summary(line_id)
```

能够准确回答。

用户：

```text
当前交通网络规模如何？
```

Agent：

```text
get_transport_network_summary()
```

返回结构化摘要。

用户：

```text
哪些线路没有车辆？
```

Agent：

```text
find_lines_without_vehicles()
```

直接得到结果。

用户：

```text
有哪些车辆没有分配线路？
```

Agent：

```text
find_unassigned_vehicles()
```

直接回答。

---

# 27. Phase 3 交付物

必须提交：

```text
1. Snapshot schema v2

2. SnapshotIndex

3. Line semantic collector

4. Station relationships

5. Vehicle relationships

6. transport mode normalization

7. industry type probe

8. company finance probe

9. get_line_summary

10. get_transport_network_summary

11. find_lines_without_vehicles

12. find_unassigned_vehicles

13. relation integrity validator

14. semantic-verification.json

15. Live MCP session

16. Python unit tests

17. TPF2 stdout.txt

18. UNKNOWN / unavailable 字段列表
```

本阶段核心：

```text
从“TPF2 有哪些东西”
升级成
“TPF2 这些东西之间是什么关系、当前网络是什么结构”。
```