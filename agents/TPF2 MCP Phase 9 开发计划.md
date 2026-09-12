# TPF2 MCP Phase 9：Network Intelligence / Planning Layer

## 0. Phase 9 总目标

当前项目已经完成 Phase 0～8。

Phase 8 已经验证：

- MCP Server 可以稳定读取游戏实时状态；
- 世界快照可以标准化；
- Town / Industry / Station / Line / Vehicle 等基础实体可以读取；
- Line ↔ Station ↔ Vehicle 关系可以解析；
- cargo type 可以动态枚举；
- line frequency / throughput / vehicle capacity 等部分字段已经完成运行时验证；
- 可以构建 station-line connectivity graph；
- 可以执行 line comparison / ranking；
- 可以执行 network structural diagnostics；
- 可以查询 fleet summary；
- 对当前无法可靠读取的数据已经显式声明：
  - `vehicle_load = UNAVAILABLE`
  - `vehicle_occupancy = UNAVAILABLE`
  - `station_waiting = UNAVAILABLE`
  - `line_finance = UNAVAILABLE`
- 不允许将不可验证字段伪装成真实数据。

Phase 9 不再以“继续添加原始查询接口”为核心。

Phase 9 的核心目标是：

> 在现有 verified runtime data 之上建立稳定、可解释、确定性的运输网络分析层，使 MCP 可以回答更高层级的游戏运营问题。

Phase 9 暂时保持 **READ ONLY**。

禁止修改游戏状态。

---

# 1. Phase 9 核心原则

所有分析必须满足：

```text
Raw Engine Data
        ↓
Normalized Snapshot
        ↓
Verified Metrics
        ↓
Derived Metrics
        ↓
Explainable Diagnostics
        ↓
Planning Suggestions
```

严格禁止：

```text
未知字段
↓
经验猜测
↓
伪装成游戏真实状态
```

每一个分析结果必须明确来源等级：

```text
ENGINE_VERIFIED
UI_CROSS_VERIFIED
DERIVED
HEURISTIC
UNAVAILABLE
```

其中：

### ENGINE_VERIFIED

直接来自稳定游戏 API / component。

### UI_CROSS_VERIFIED

已经与游戏 UI 至少完成一次语义交叉验证。

### DERIVED

由 verified fields 确定性计算。

例如：

```text
fleet_capacity_total
graph_degree
transfer_count
station_connectivity
route_hop_count
```

### HEURISTIC

规则型诊断。

例如：

```text
"该线路站点很多但车辆很少"
```

必须返回触发规则和证据。

### UNAVAILABLE

当前无法得到。

不得猜测。

---

# 2. Phase 9.1：建立 Network Intelligence Index

不要每次 MCP tool 调用都重新遍历全部世界对象。

在现有 world snapshot 上建立：

```text
NetworkIntelligenceIndex
```

建议目录：

```text
server/
  tpf2_mcp/
    analytics/
      __init__.py

      network_index.py
      line_metrics.py
      station_metrics.py
      fleet_metrics.py
      route_analysis.py
      network_diagnostics.py
      planning.py
      evidence.py
```

建议核心结构：

```python
class NetworkIntelligenceIndex:
    snapshot_sequence: int

    lines_by_id: dict
    stations_by_id: dict
    vehicles_by_id: dict
    towns_by_id: dict
    industries_by_id: dict

    vehicles_by_line: dict
    lines_by_station: dict

    station_graph: dict
    line_graph: dict

    station_neighbors: dict

    line_metrics: dict
    station_metrics: dict
```

Index 必须绑定：

```text
snapshot_sequence
```

如果 world snapshot sequence 改变：

```text
invalidate old index
build new index
```

不得发生：

```text
snapshot N
+
index N-1
```

混用。

---

# 3. Phase 9.2：线路画像 Line Profile

新增 MCP Tool：

```text
get_line_profile
```

输入：

```json
{
  "line_id": 11833
}
```

返回统一线路画像。

示例结构：

```json
{
  "line": {
    "entity_id": 11833,
    "name": "线路 3"
  },

  "topology": {
    "stop_count": 2,
    "unique_station_count": 2,
    "repeated_stop_count": 0
  },

  "fleet": {
    "vehicle_count": 3,
    "fleet_capacity_total": 540,
    "average_vehicle_capacity": 180
  },

  "operations": {
    "frequency_seconds": 64.73,
    "throughput": 361
  },

  "derived": {
    "capacity_per_stop": 270,
    "vehicles_per_stop": 1.5,
    "throughput_per_vehicle": 120.33
  },

  "availability": {
    "load": "UNAVAILABLE",
    "waiting": "UNAVAILABLE",
    "finance": "UNAVAILABLE"
  },

  "evidence": {}
}
```

注意：

```text
throughput_per_vehicle
```

只能命名为 derived ratio。

绝对不能叫：

```text
vehicle utilization
vehicle load
profit efficiency
```

因为没有对应 telemetry。

---

# 4. Phase 9.3：线路分类

新增：

```text
classify_lines
```

目标不是自动说“好/坏”。

而是按照结构特征分类。

例如：

```text
HIGH_FREQUENCY_SHORT_ROUTE
LOW_FREQUENCY_LONG_ROUTE
HIGH_CAPACITY_ROUTE
LOW_FLEET_ROUTE
TRANSFER_HEAVY_ROUTE
REPEATED_STOP_ROUTE
SIMPLE_SHUTTLE
```

规则必须显式。

例如：

```text
SIMPLE_SHUTTLE

unique_station_count == 2
```

```text
LOW_FLEET_ROUTE

vehicle_count <= threshold
AND
stop_count >= threshold
```

返回：

```json
{
  "classification": "SIMPLE_SHUTTLE",
  "source_status": "HEURISTIC",
  "rule": {
    "unique_station_count": 2
  },
  "evidence": {
    "unique_station_count": 2
  }
}
```

不要使用：

```text
bad line
inefficient line
unprofitable line
```

---

# 5. Phase 9.4：线路异常值分析

新增：

```text
find_line_outliers
```

针对整个存档比较：

```text
frequency_seconds
vehicle_count
fleet_capacity_total
stop_count
throughput
vehicles_per_stop
capacity_per_stop
```

支持：

```json
{
  "metric": "frequency_seconds",
  "method": "iqr"
}
```

至少实现：

```text
IQR
percentile
```

例如：

```json
{
  "metric": "frequency_seconds",
  "method": "iqr",
  "results": [
    {
      "line_id": 123,
      "value": 894.2,
      "direction": "HIGH",
      "source_status": "DERIVED"
    }
  ]
}
```

这里表达的是：

> 统计异常值。

不是：

> 运营异常。

两者必须区分。

---

# 6. Phase 9.5：线路相似度

新增：

```text
find_similar_lines
```

输入：

```json
{
  "line_id": 11833,
  "limit": 10
}
```

使用 verified / derived structural features：

```text
stop_count
vehicle_count
frequency_seconds
throughput
fleet_capacity_total
```

先做归一化。

建议：

```text
z-score
```

然后计算：

```text
euclidean distance
```

返回：

```json
{
  "reference_line": 11833,
  "features": [
    "stop_count",
    "vehicle_count",
    "frequency_seconds",
    "throughput",
    "fleet_capacity_total"
  ],
  "results": []
}
```

必须说明：

```text
similarity is structural similarity
```

不是：

```text
same profitability
same passenger demand
```

---

# 7. Phase 9.6：Station Hub Analysis

Phase 8 已经有：

```text
rank_transfer_stations
get_station_connectivity
```

Phase 9 增强为：

```text
get_station_profile
```

返回：

```text
line_count
unique_line_count
graph_degree
neighbor_station_count
directly_reachable_station_count
```

并增加：

```text
transfer centrality
```

第一阶段不要上复杂 NetworkX。

自己实现 deterministic BFS 即可。

新增：

```text
rank_station_hubs
```

支持：

```text
line_count
graph_degree
reachable_station_count
```

注意：

```text
hub
```

表示 network topology hub。

绝对不能默认等价：

```text
high passenger traffic
high waiting volume
```

---

# 8. Phase 9.7：Network Reachability

新增：

```text
analyze_network_reachability
```

目标：

分析整个玩家运输网络是否存在多个互相隔离的 connectivity components。

返回：

```json
{
  "station_count": 178,

  "connected_component_count": 3,

  "components": [
    {
      "component_id": 0,
      "station_count": 150
    },
    {
      "component_id": 1,
      "station_count": 20
    },
    {
      "component_id": 2,
      "station_count": 8
    }
  ]
}
```

并新增：

```text
find_isolated_station_clusters
```

用于识别：

```text
独立运输网络
```

注意：

这不是物理地图隔离。

这里只表示：

```text
line-station graph
```

不存在连通关系。

---

# 9. Phase 9.8：Town Connectivity

目前 Town 只是独立实体。

Phase 9 尝试建立：

```text
Town
 ↕
Station Group
 ↕
Line
```

但这里不能猜。

首先做 probe：

```text
town-station-relation-probe.json
```

搜索 runtime API 是否存在稳定关系。

优先顺序：

```text
Engine component
↓
Entity relation
↓
station ownership/catchment
↓
UI/runtime source
```

如果无法证明：

```text
town_station_relation = UNAVAILABLE
```

不得使用：

```text
station.name contains town.name
```

作为正式 relation。

字符串匹配最多只能：

```text
HEURISTIC
```

并且不能进入 verified graph。

如果成功验证：

新增：

```text
get_town_connectivity
find_town_route
rank_connected_towns
```

如果失败：

保留 probe artifact。

不要阻塞 Phase 9。

---

# 10. Phase 9.9：Industry / Cargo Semantic Probe

当前：

```text
industry_type = UNKNOWN
```

这明显是下一批值得突破的字段。

Phase 9 应做：

```text
industry-runtime-probe
```

寻找：

```text
industry production type
input cargo
output cargo
production level
shipment
transported percentage
```

但是：

第一原则仍然是验证。

目标优先级：

## P0

```text
industry type
input cargo types
output cargo types
```

## P1

```text
production
shipment
transport
```

只有运行时确认后才能进入 snapshot。

如果成功：

Industry schema：

```json
{
  "entity_id": 123,
  "name": "...",

  "industry_type": "STEEL_MILL",

  "inputs": [
    "IRON_ORE",
    "COAL"
  ],

  "outputs": [
    "STEEL"
  ]
}
```

增加：

```text
source_status
```

---

# 11. Phase 9.10：Cargo Production Graph

仅在 Industry Semantic Probe 成功后实现。

构建：

```text
CargoProductionGraph
```

例如：

```text
IRON_ORE ─┐
          ├→ STEEL → MACHINES
COAL ─────┘
```

新增：

```text
get_cargo_chain
```

例如：

```json
{
  "cargo": "MACHINES"
}
```

返回：

```text
required upstream cargo
candidate producer industries
candidate consumer industries
```

注意：

这里只描述：

```text
production dependency
```

不是：

```text
当前物流是否已经建立
```

---

# 12. Phase 9.11：运输网络建议层

这是 Phase 9 最核心的上层能力。

新增：

```text
get_network_recommendations
```

但是推荐必须是：

```text
rule-based
evidence-backed
conservative
```

示例：

```json
{
  "recommendations": [
    {
      "type": "CHECK_LOW_FREQUENCY_LINE",
      "severity": "INFO",
      "line_id": 24363,

      "reason": {
        "frequency_seconds": 894.2,
        "network_percentile": 0.98
      },

      "statement":
        "This line has one of the longest verified headways in the current network.",

      "limitations": [
        "vehicle load unavailable",
        "station waiting unavailable",
        "profitability unavailable"
      ]
    }
  ]
}
```

允许：

```text
Consider inspecting this line.
```

禁止：

```text
Add more trains.
Delete this line.
This line is losing money.
This station is overcrowded.
```

除非未来获得真实数据。

---

# 13. Phase 9.12：What Can I Improve?

增加一个特别适合 LLM 的 MCP Tool：

```text
analyze_network
```

这是 Phase 9 的旗舰接口。

用户以后可以直接问：

```text
帮我分析一下我的运输网络。
```

LLM 调一个接口即可。

返回：

```json
{
  "summary": {
    "line_count": 96,
    "station_count": 178,
    "vehicle_count": 262
  },

  "network_structure": {},

  "line_outliers": {},

  "hub_analysis": {},

  "fleet_analysis": {},

  "isolated_components": {},

  "recommendations": [],

  "limitations": {
    "load": "UNAVAILABLE",
    "waiting": "UNAVAILABLE",
    "finance": "UNAVAILABLE"
  }
}
```

要求：

不要把整个 world snapshot 再塞一遍。

应该输出：

```text
high-information compact result
```

避免 MCP token 爆炸。

---

# 14. Phase 9.13：Evidence Object 标准化

Phase 8 已经开始体现 source status。

Phase 9 必须统一。

建议：

```json
{
  "source_status": "DERIVED",

  "evidence": [
    {
      "field": "frequency_seconds",
      "value": 894.2,
      "source": "game.interface.getEntity(line_id).frequency",
      "verification": "UI_CROSS_VERIFIED"
    }
  ],

  "limitations": []
}
```

建议建立：

```text
analytics/evidence.py
```

统一生成。

不要各 tool 自己手写字符串。

---

# 15. Phase 9.14：Capability Registry 升级

当前：

```text
tpf2://capabilities
```

升级为机器可读结构。

不要只返回：

```json
{
  "vehicle_load": "UNAVAILABLE"
}
```

建议：

```json
{
  "vehicle_load": {
    "status": "UNAVAILABLE",
    "reason": "No verified runtime source"
  },

  "line_frequency": {
    "status": "UI_CROSS_VERIFIED",
    "source": "game.interface.getEntity(line_id).frequency"
  },

  "line_similarity": {
    "status": "DERIVED"
  }
}
```

---

# 16. Phase 9.15：新增 MCP Tools

Phase 9 推荐新增：

```text
get_line_profile
classify_lines
find_line_outliers
find_similar_lines

get_station_profile
rank_station_hubs

analyze_network_reachability
find_isolated_station_clusters

get_town_connectivity
find_town_route

get_industry_profile
get_cargo_chain

get_network_recommendations
analyze_network
```

注意：

Town / Industry / Cargo 相关接口：

只有验证成功才 expose。

如果 probe 没成功：

不要注册半残 tool。

---

# 17. Tool 数量控制

Phase 8 已经有 35 tools。

不要无限增加。

Phase 9 结束建议：

```text
45～50 tools max
```

如果功能可以通过一个 tool + 参数解决：

不要拆成 5 个 tool。

例如：

```text
find_line_outliers(metric=...)
```

优于：

```text
find_frequency_outliers
find_capacity_outliers
find_vehicle_count_outliers
...
```

---

# 18. 性能要求

当前存档约：

```text
96 lines
178 stations
262 vehicles
```

Phase 9 必须确保：

普通 analytics：

```text
< 50 ms
```

network BFS：

```text
< 100 ms
```

全局 analyze_network：

```text
< 300 ms
```

以上为 MCP server 本地处理时间目标。

不要每次触发 game bridge refresh。

默认：

```text
use current snapshot
```

只有：

```text
force_refresh=true
```

才主动要求 bridge 更新。

---

# 19. Snapshot Consistency

每个 analytics response 必须返回：

```text
snapshot_sequence
```

例如：

```json
{
  "snapshot_sequence": 10
}
```

所有关联对象必须来自同一个 sequence。

---

# 20. Phase 9 测试目录

新增：

```text
tests/
  phase9/
    test_network_index.py
    test_line_profile.py
    test_line_classification.py
    test_line_outliers.py
    test_line_similarity.py
    test_station_hubs.py
    test_reachability.py
    test_recommendations.py
    test_evidence.py
```

测试必须使用 fixture snapshot。

不要依赖真实游戏才能跑单测。

---

# 21. Golden Snapshot

从当前已经验证的 live snapshot 创建：

```text
tests/fixtures/
  phase8_verified_snapshot.json
```

用于所有 Phase 9 analytics 测试。

不得在测试里写死：

```text
entity 11833 永远存在
```

除非 fixture 明确定义。

---

# 22. 数学测试

对 derived metrics 做明确测试。

例如：

```text
frequency_seconds
fleet_capacity_total
average_vehicle_capacity
vehicles_per_stop
capacity_per_stop
```

所有：

```text
division by zero
None
empty lines
empty vehicles
missing relation
```

都必须覆盖。

---

# 23. Graph 测试

构造 synthetic graph：

```text
A -- B -- C
     |
     D

E -- F
```

验证：

```text
connected components = 2

route A → D

route A → F = unavailable
```

---

# 24. Recommendation Regression Test

推荐系统必须 deterministic。

同一 snapshot：

```text
recommendations
```

排序和内容必须一致。

禁止：

```text
random score
```

---

# 25. Phase 9 Live Verification

完成开发后，在真实 TPF2 存档执行：

```text
initialize
tools/list

get_game_state

get_line_profile
classify_lines
find_line_outliers
find_similar_lines

get_station_profile
rank_station_hubs

analyze_network_reachability

get_network_recommendations

analyze_network
```

然后重新读取：

```text
tpf2://capabilities
tpf2://network
```

---

# 26. Live Evidence Pack

最终必须生成：

```text
tpf2-mcp-phase9-network-intelligence.zip
```

目录：

```text
YYYYMMDD-HHMMSS/

  manifest.json

  game-state.json

  capabilities.json
  network.json

  line-profile.json
  line-classification.json
  line-outliers.json
  line-similarity.json

  station-profile.json
  station-hubs.json

  network-reachability.json
  isolated-components.json

  network-recommendations.json
  network-analysis.json

  industry-probe.json
  town-relation-probe.json

  phase9-live-mcp-session.jsonl

  responses/
```

如果 industry/town probe 没找到可靠来源：

仍然保留：

```text
industry-probe.json
town-relation-probe.json
```

并明确：

```text
UNRESOLVED
```

---

# 27. manifest.json

至少记录：

```json
{
  "phase": 9,
  "schema_version": 6,
  "snapshot_sequence": 0,

  "features": {
    "network_intelligence": true,
    "line_profiles": true,
    "station_hub_analysis": true,
    "network_reachability": true,
    "network_recommendations": true,

    "town_station_relation": "VERIFIED|UNRESOLVED",
    "industry_semantics": "VERIFIED|UNRESOLVED"
  }
}
```

---

# 28. 文档

新增：

```text
docs/
  PHASE9_NETWORK_INTELLIGENCE.md
```

必须写清楚：

## Verified Facts

哪些字段直接来自 engine。

## Derived Metrics

每个指标公式。

## Heuristic Rules

每条诊断规则。

## Unsupported Claims

特别明确：

当前不能判断：

```text
线路是否盈利
车辆是否满载
车站是否拥堵
乘客等待量
真实线路需求
```

---

# 29. README 更新

加入用户级示例：

```text
"分析一下我的运输网络"

"哪几条线路的班次最稀疏？"

"线路 23 和哪些线路结构比较相似？"

"我的运输网络有几个互相独立的区域？"

"哪些车站是网络中的主要换乘节点？"

"有哪些值得我进一步检查的线路？"
```

---

# 30. 不要做的事情

Phase 9 禁止：

### 1. 不写游戏状态

不要：

```text
buy_vehicle
sell_vehicle
create_line
delete_line
change_line
```

### 2. 不做自动操作

不要：

```text
auto optimize
```

### 3. 不伪造负载

没有 load 就：

```text
UNAVAILABLE
```

### 4. 不伪造等待人数

没有 waiting 就：

```text
UNAVAILABLE
```

### 5. 不从 throughput 推断盈利

```text
throughput != revenue
```

### 6. 不从 capacity 推断 occupancy

```text
capacity != current passengers
```

### 7. 不靠名称正式判断 Industry Type

例如：

```text
"xxx Steel Mill"
```

只能作为 probe clue。

不能作为正式 runtime truth。

---

# 31. Phase 9 成功标准

Phase 9 完成后，下面的问题必须可以直接通过 MCP 回答：

```text
这条线路的结构是什么？

哪些线路班次最稀疏？

哪些线路在当前网络里属于统计异常值？

哪几条线路跟这条线路结构最类似？

哪些车站是网络拓扑上的核心换乘节点？

整个运输网络是不是完全连通？

有哪些孤立的运输子网络？

有哪些线路值得我进一步检查？

为什么系统推荐我检查这条线路？

这个结论来自游戏真实数据、派生指标还是规则判断？
```

并且：

对于：

```text
这条线是不是亏钱？

这个车站是不是爆满？

这辆车是不是空载？
```

如果当前 runtime source 不存在：

必须明确返回：

```text
UNAVAILABLE
```

而不是猜测。

---

# 32. Phase 9 最终定位

Phase 8：

```text
TPF2
 ↓
MCP
 ↓
Queryable / Diagnostic Runtime
```

Phase 9：

```text
TPF2
 ↓
Verified Runtime Snapshot
 ↓
Network Intelligence Index
 ↓
Topology + Metrics + Diagnostics
 ↓
Explainable Planning Suggestions
 ↓
LLM
```

Phase 9 结束以后：

MCP 不再只是：

> “帮我把 Transport Fever 2 的数据读出来。”

而开始具备：

> “基于 Transport Fever 2 的真实运行时数据，帮我分析当前运输网络，并告诉我哪些地方值得检查，以及为什么。”

这就是 Phase 9 的主要交付目标。