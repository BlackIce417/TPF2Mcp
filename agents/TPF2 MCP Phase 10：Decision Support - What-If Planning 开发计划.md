# TPF2 MCP Phase 10：Decision Support / What-If Planning

## 0. 背景

当前项目已经完成 Phase 0～9。

Phase 9 已经建立：

```text
Raw Engine Data
        ↓
Normalized Snapshot
        ↓
NetworkIntelligenceIndex
        ↓
Line / Station / Fleet Metrics
        ↓
Topology Diagnostics
        ↓
Network Recommendations
```

并已经具备：

```text
get_line_profile
classify_lines
find_line_outliers
find_similar_lines
get_station_profile
rank_station_hubs
analyze_network_reachability
find_isolated_station_clusters
get_network_recommendations
analyze_network
```

Phase 10 不再继续大量增加“统计查询”。

Phase 10 的目标是建立：

```text
Decision Support Layer
```

使 MCP 从：

```text
发现问题
```

进一步发展为：

```text
解释问题
↓
定位影响范围
↓
生成候选方案
↓
模拟方案的结构性影响
↓
比较多个方案
↓
给出证据充分的决策建议
```

Phase 10 仍然必须：

```text
READ ONLY
```

禁止：

```text
build line
delete line
buy vehicle
sell vehicle
change frequency
modify station
modify world
```

任何“方案”只能存在于 MCP Server 内存中的模拟模型。

---

# 1. Phase 10 总体架构

新增：

```text
tpf2_mcp/
  planning/
    __init__.py

    problem_detector.py
    impact_analysis.py
    scenarios.py
    simulator.py
    candidate_generator.py
    scoring.py
    comparator.py
    explanation.py
```

形成：

```text
NetworkIntelligenceIndex
        ↓
ProblemDetector
        ↓
CandidateGenerator
        ↓
ScenarioSimulator
        ↓
ScenarioScorer
        ↓
ScenarioComparator
        ↓
DecisionSupport
```

严格禁止 simulator 访问任何游戏写接口。

---

# 2. Phase 10.1：Problem Object

Phase 9 recommendation 当前主要是：

```text
CHECK_LONG_HEADWAY_LINE
REVIEW_ISOLATED_NETWORK_CLUSTER
```

Phase 10 将其统一抽象成：

```text
NetworkProblem
```

建议结构：

```json
{
  "problem_id": "line:11833:long_headway",

  "type": "LONG_HEADWAY_OUTLIER",

  "target": {
    "entity_type": "LINE",
    "entity_id": 11833
  },

  "severity": "INFO",

  "confidence": "HIGH",

  "source_status": "HEURISTIC",

  "evidence": [],

  "limitations": []
}
```

新增：

```text
detect_network_problems
```

要求结果 deterministic。

同一 snapshot：

```text
same input
=
same problems
```

---

# 3. Phase 10.2：影响范围分析

新增：

```text
analyze_problem_impact
```

例如：

```json
{
  "problem_id": "line:11833:long_headway"
}
```

返回该线路与哪些实体关联：

```text
Line
 ├─ Stations
 ├─ Vehicles
 ├─ Neighbor Lines
 ├─ Transfer Stations
 ├─ Connected Component
 └─ Potentially Related Town/Industry
```

只允许返回已经验证的关系。

例如：

```json
{
  "line_id": 11833,

  "affected_stations": [1001, 1002],

  "fleet": [3001, 3002],

  "transfer_lines": [11834, 11840],

  "connected_component_id": 0
}
```

这里的：

```text
affected
```

表示：

```text
graph dependency / structural relation
```

绝不能解释成：

```text
passenger loss
cargo loss
financial loss
```

---

# 4. Phase 10.3：Scenario Model

建立虚拟方案对象：

```python
class PlanningScenario:
    scenario_id: str
    snapshot_sequence: int
    mutations: list[VirtualMutation]
```

注意：

```text
VirtualMutation
```

绝不能执行到游戏。

只作用于：

```text
copy of NetworkIntelligenceIndex
```

或者：

```text
lightweight planning model
```

第一阶段支持：

```text
CHANGE_VIRTUAL_VEHICLE_COUNT
CHANGE_VIRTUAL_FREQUENCY
CONNECT_EXISTING_STATIONS
DISCONNECT_LINE
```

其中：

## CHANGE_VIRTUAL_VEHICLE_COUNT

例如：

```json
{
  "type": "CHANGE_VIRTUAL_VEHICLE_COUNT",
  "line_id": 11833,
  "delta": 1
}
```

不代表真的买车。

只是：

```text
what-if hypothesis
```

## CHANGE_VIRTUAL_FREQUENCY

仅修改 planning model。

## CONNECT_EXISTING_STATIONS

表示：

```text
假设存在一条连接 A/B 的运输线路
```

用于拓扑模拟。

不需要构造真实轨道。

---

# 5. Phase 10.4：Scenario Simulator

新增：

```text
simulate_network_scenario
```

输入：

```json
{
  "mutations": [
    {
      "type": "CHANGE_VIRTUAL_VEHICLE_COUNT",
      "line_id": 11833,
      "delta": 1
    }
  ]
}
```

输出：

```json
{
  "baseline": {},
  "scenario": {},
  "delta": {}
}
```

例如：

```json
{
  "delta": {
    "vehicle_count": 1,
    "fleet_capacity_total": 180,
    "vehicles_per_stop": 0.5
  }
}
```

如果 frequency 无法由 vehicle_count 准确推导：

不得自动写：

```text
frequency improves to 40 seconds
```

除非建立经过验证的确定性公式。

否则：

```json
"frequency_seconds": {
  "status": "UNAVAILABLE",
  "reason": "Cannot deterministically derive timetable frequency from virtual fleet count."
}
```

---

# 6. Phase 10.5：Graph What-If

这是 Phase 10 最重要的一部分。

对 topology 可以进行非常可靠的模拟。

新增：

```text
simulate_station_connection
```

输入：

```json
{
  "station_a": 1001,
  "station_b": 2044
}
```

构建：

```text
baseline graph
+
virtual edge
```

然后重新计算：

```text
connected_component_count
reachable_station_count
graph_degree
shortest_hop_distance
isolated_component_count
```

例如：

```json
{
  "baseline": {
    "connected_component_count": 3
  },

  "scenario": {
    "connected_component_count": 2
  },

  "delta": {
    "connected_component_count": -1
  }
}
```

这个结果属于：

```text
DERIVED
```

可信度明显高于需求预测。

---

# 7. Phase 10.6：Network Path Analysis

Phase 9 已经有 connectivity。

Phase 10 增加完整路径分析：

```text
find_station_route
```

输入：

```json
{
  "from_station_id": 123,
  "to_station_id": 456
}
```

返回：

```text
station path
line transitions
hop count
transfer count
```

例如：

```json
{
  "station_path": [
    123,
    234,
    456
  ],

  "line_path": [
    10001,
    10024
  ],

  "hop_count": 2,

  "transfer_count": 1
}
```

采用 deterministic BFS。

暂时不要做：

```text
fastest route
cheapest route
best route
```

因为缺乏 travel time / cost 的完整验证。

---

# 8. Phase 10.7：Alternative Route Search

新增：

```text
find_alternative_routes
```

第一阶段只做：

```text
minimum hop routes
```

或者：

```text
k structurally different routes
```

限制：

```text
max_routes <= 5
```

结果必须说明：

```text
These are topology routes, not guaranteed fastest routes.
```

---

# 9. Phase 10.8：Bottleneck Proxy

目前没有：

```text
station waiting
vehicle load
occupancy
```

所以禁止声称发现真实 congestion。

但可以建立：

```text
structural bottleneck proxy
```

新增：

```text
find_structural_bottlenecks
```

依据：

```text
high line_count
high graph_degree
high transfer centrality
bridge-like connectivity
```

特别关注：

```text
articulation points
```

和：

```text
bridge edges
```

自己实现 Tarjan algorithm。

不要依赖 NetworkX。

新增：

```text
find_articulation_stations
find_bridge_connections
```

这两个结果完全来自 graph：

```text
DERIVED
```

意义是：

```text
移除该节点/边会使网络拓扑断开
```

不是：

```text
该站拥堵
```

---

# 10. Phase 10.9：Network Resilience

基于 articulation / bridge：

新增：

```text
analyze_network_resilience
```

例如：

```json
{
  "articulation_station_count": 8,

  "bridge_connection_count": 12,

  "largest_component_ratio": 0.91,

  "single_point_dependencies": []
}
```

进一步支持：

```text
simulate_station_failure
simulate_line_failure
```

注意：

这仍然只是 topology what-if。

例如：

```text
假设线路 11833 不存在
```

重新计算：

```text
components
reachability
isolated stations
```

---

# 11. Phase 10.10：Candidate Generator

针对检测到的问题生成：

```text
candidate actions
```

但 candidate 必须是：

```text
hypothesis
```

例如：

### 长间隔线路

允许产生：

```text
INSPECT_LINE
COMPARE_SIMILAR_LINES
SIMULATE_EXTRA_VEHICLE
```

禁止直接：

```text
BUY_ONE_TRAIN
```

### isolated component

允许产生：

```text
FIND_NEAREST_TOPOLOGY_CONNECTION_CANDIDATES
SIMULATE_COMPONENT_CONNECTION
```

### articulation station

允许产生：

```text
SEARCH_REDUNDANT_CONNECTION
```

---

# 12. Phase 10.11：Scenario Score

建立：

```text
ScenarioScore
```

但不要假装存在统一“最佳方案”。

第一阶段分维度评分：

```text
connectivity_gain
isolation_reduction
redundancy_gain
fleet_change
complexity
evidence_strength
```

例如：

```json
{
  "connectivity_gain": 0.72,
  "isolation_reduction": 1.0,
  "redundancy_gain": 0.31,

  "cost": "UNAVAILABLE",

  "demand_effect": "UNAVAILABLE",

  "profit_effect": "UNAVAILABLE"
}
```

禁止生成：

```text
overall_roi
expected_profit
```

---

# 13. Phase 10.12：Scenario Comparison

新增旗舰工具：

```text
compare_network_scenarios
```

输入：

```json
{
  "scenarios": [
    {
      "name": "A",
      "mutations": []
    },
    {
      "name": "B",
      "mutations": []
    }
  ]
}
```

返回：

```text
baseline
scenario A
scenario B
delta A
delta B
comparison
```

例如：

```json
{
  "comparison": {
    "connectivity_gain": {
      "better": "B"
    },

    "redundancy_gain": {
      "better": "A"
    },

    "cost": {
      "status": "UNAVAILABLE"
    }
  }
}
```

---

# 14. Phase 10.13：Planning Recommendations

Phase 9：

```text
get_network_recommendations
```

Phase 10 新增：

```text
get_planning_options
```

区别：

Phase 9：

```text
发现什么值得检查
```

Phase 10：

```text
有哪些可以进一步模拟的方案
```

例如：

```json
{
  "problem": "ISOLATED_COMPONENT",

  "options": [
    {
      "type": "SIMULATE_COMPONENT_CONNECTION",

      "stations": [
        123,
        456
      ],

      "expected_structural_effect": {
        "connected_component_count": -1
      },

      "source_status": "DERIVED"
    }
  ]
}
```

---

# 15. Phase 10.14：旗舰接口

增加：

```text
analyze_and_plan_network
```

目标：

LLM 用户只需要问：

```text
帮我看看现在网络哪里有问题，以及我可以怎么调整。
```

一次 MCP 调用完成：

```text
Network Summary
↓
Problems
↓
Impact
↓
Structural Weaknesses
↓
Planning Candidates
↓
What-If Results
↓
Comparison
↓
Limitations
```

返回必须 compact。

不要把 snapshot 原样塞进去。

建议：

```json
{
  "summary": {},

  "problems": [],

  "critical_dependencies": [],

  "planning_options": [],

  "scenario_results": [],

  "limitations": {}
}
```

---

# 16. Phase 10.15：Snapshot Isolation

这是强制要求。

所有 scenario 必须绑定：

```text
snapshot_sequence
```

例如：

```text
scenario created from snapshot 52
```

如果当前游戏已经进入：

```text
snapshot 53
```

旧 scenario 返回：

```text
STALE_SCENARIO
```

绝不能：

```text
snapshot 53
+
scenario from snapshot 52
```

继续比较。

---

# 17. Phase 10.16：Scenario Cache

增加：

```text
ScenarioCache
```

key：

```text
snapshot_sequence
+
normalized mutations
```

同样 scenario：

```text
不重复计算
```

但 snapshot 改变：

```text
invalidate
```

---

# 18. Phase 10.17：Evidence Propagation

Phase 9 已经建立：

```text
ENGINE_VERIFIED
UI_CROSS_VERIFIED
DERIVED
HEURISTIC
UNAVAILABLE
```

Phase 10 必须传播 evidence。

例如：

```text
ENGINE_VERIFIED frequency
↓
DERIVED percentile
↓
HEURISTIC LONG_HEADWAY_PROBLEM
↓
HYPOTHETICAL extra vehicle scenario
```

建议增加：

```text
HYPOTHETICAL
```

source status。

最终：

```text
ENGINE_VERIFIED
UI_CROSS_VERIFIED
DERIVED
HEURISTIC
HYPOTHETICAL
UNAVAILABLE
```

---

# 19. Phase 10.18：明确禁止虚构的数据

以下字段仍然禁止推断：

```text
vehicle_load
vehicle_occupancy
station_waiting
passenger_demand
cargo_demand
line_profit
line_cost
vehicle_profit
expected_revenue
ROI
travel_time
```

除非 Phase 10 runtime probe 获得明确验证。

如果不可得：

```json
{
  "status": "UNAVAILABLE"
}
```

---

# 20. Phase 10.19：Runtime Probe 独立进行

可以继续探测：

```text
vehicle load
vehicle occupancy
station waiting
line finance
travel time
```

但必须与 Decision Support 主线解耦。

目录：

```text
phase10-evidence/
  probes/
    vehicle-load-probe.json
    station-waiting-probe.json
    finance-probe.json
    travel-time-probe.json
```

Probe 失败：

```text
不得阻塞 Phase 10
```

---

# 21. Phase 10 MCP Tool 清单

最低要求：

```text
detect_network_problems

analyze_problem_impact

find_station_route

find_alternative_routes

find_articulation_stations

find_bridge_connections

analyze_network_resilience

simulate_station_connection

simulate_line_failure

simulate_station_failure

simulate_network_scenario

get_planning_options

compare_network_scenarios

analyze_and_plan_network
```

---

# 22. 单元测试

新增：

```text
phase10/
  test_problem_detector.py
  test_routes.py
  test_resilience.py
  test_scenarios.py
  test_scenario_comparison.py
```

必须覆盖：

### deterministic

同一 snapshot：

```text
same result
```

### stale scenario

snapshot 改变：

```text
STALE_SCENARIO
```

### graph correctness

人工构造：

```text
A-B-C
  |
  D
```

验证：

```text
articulation point
bridge
component
route
```

### no mutation

测试执行 scenario 前后：

```text
original SnapshotIndex unchanged
```

这是强制测试。

---

# 23. Live Verification

必须继续实际启动 TPF2。

生成：

```text
phase10-evidence/
```

至少：

```text
manifest.json
capabilities.json

network-baseline.json

network-problems.json
station-route.json

articulation-stations.json
bridge-connections.json
network-resilience.json

scenario-connect-components.json
scenario-line-failure.json
scenario-station-failure.json

scenario-comparison.json

planning-options.json

network-plan.json

phase10-live-mcp-session.jsonl
```

---

# 24. Live Test Case

至少挑当前真实存档完成：

## Case A

```text
选择两座已连通 station
```

验证：

```text
find_station_route
```

## Case B

选择不同 component 的 station。

验证：

```text
baseline:
component_count = N

virtual connection:
component_count = N - 1
```

## Case C

寻找 articulation station。

执行：

```text
simulate_station_failure
```

验证：

```text
component count changes
```

如果当前地图不存在 articulation point：

```text
明确记录 NONE_FOUND
```

不能造数据。

---

# 25. README

README 必须增加：

```text
Phase 10 Decision Support
```

解释以下概念差异：

```text
diagnostic
recommendation
planning option
scenario
simulation
```

特别明确：

```text
Scenario simulation does NOT modify the game.
```

---

# 26. 最终交付物

最终打包：

```text
tpf2-mcp-phase10-decision-support.zip
```

要求：

```text
完整源码
单元测试
Live evidence
README
PHASE10_DECISION_SUPPORT.md
```

禁止包含：

```text
__pycache__
*.pyc
临时日志
IDE 文件
```

---

# 27. Phase 10 验收标准

只有同时满足以下条件，Phase 10 才算完成：

- 可以从 Phase 9 diagnostics 生成标准 NetworkProblem；
- 可以分析问题影响范围；
- 可以计算 station-to-station topology route；
- 可以识别 articulation stations；
- 可以识别 bridge connections；
- 可以分析 network resilience；
- 可以对 station/line failure 做虚拟模拟；
- 可以对虚拟 station connection 做模拟；
- scenario 不会修改真实 snapshot；
- scenario 与 snapshot sequence 强绑定；
- 可以比较至少两个 scenario；
- 所有无法证明的数据继续返回 UNAVAILABLE；
- 所有 hypothetical 数据显式标记 HYPOTHETICAL；
- Live MCP 验证成功；
- 有完整 evidence artifact；
- 测试通过；
- 最终生成：

```text
tpf2-mcp-phase10-decision-support.zip
```

---

# 28. 不要提前做 Phase 11

Phase 10 暂时禁止：

```text
自动买车
自动建线
自动修改线路
自动建站
自动拆除
自动改 timetable
自动执行 recommendation
```

这些属于后续：

```text
Phase 11
Controlled Operations / Execution Layer
```

Phase 10 只负责：

```text
Observe
↓
Diagnose
↓
Plan
↓
Simulate
↓
Compare
```

不负责：

```text
Execute
```