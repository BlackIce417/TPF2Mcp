# TPF2 MCP Phase 8：运营诊断与解释层

Phase 7 技术实现已通过。

当前已验证可靠字段：

```text
Line:
entity_id
name
stops
stop_count
vehicle_count (derived)
frequency_seconds
throughput/rate

Vehicle:
entity_id
name
line_id
capacity_total
raw_state

Station Group:
entity_id
name
line_ids (derived)
line_count (derived)

Company:
entity_id
loan
balance candidate

Network:
Line → Station Group
Line → Vehicle
Vehicle → Line
Station Group → Line
```

当前明确不可用：

```text
vehicle current load
vehicle occupancy
station waiting
line revenue
line cost
line profit
```

这些字段继续返回：

```text
null
availability=false
source_status=UNAVAILABLE
```

不要重新猜字段。

---

## 1. 首先补齐 Phase 7 验收证据

在开始新功能前，补：

```text
tests/
```

以及：

```text
python -m unittest discover ...
```

真实输出。

重新执行最终代码：

```text
MCP get_game_state(force_refresh=true)
```

记录：

```text
request
response
previous snapshot_sequence
new snapshot_sequence
```

要求：

```text
new sequence > previous sequence
```

保存：

```text
diagnostics/.../mcp-session.jsonl
```

---

## 2. 修正 Snapshot Age 语义

当前：

```text
snapshot_age_ms
```

实际表示 Python SnapshotIndex age。

拆分：

```text
index_age_ms
```

以及：

```text
source_snapshot_age_ms
```

后者基于：

```text
state.timestamp
```

计算。

如果游戏时间戳精度仅秒级，明确记录。

---

## 3. Company balance UI Cross-check

选择三个暂停时刻：

```text
A
B
C
```

记录：

```text
TPF2 UI current money
ACCOUNT.balance
loan
```

要求确认：

```text
ACCOUNT.balance
```

到底是不是：

```text
当前现金余额
```

如果三次一致：

状态提升为：

```text
UI_CROSS_VERIFIED
```

否则保持 raw `balance`，不解释为 cash/money。

---

# 4. 建立 Line Operational Scorecard

新增：

```text
get_line_scorecard(line_id)
```

只使用已验证数据。

返回：

```json
{
  "line": {},

  "network": {
    "stop_count": 6,
    "vehicle_count": 4,
    "frequency_seconds": 120,
    "throughput": 180,
    "capacity_total": 600
  },

  "availability": {}
}
```

其中：

```text
capacity_total
=
sum(vehicle.capacity_total)
```

这是静态总运力，不代表实时载荷。

字段建议明确命名：

```text
fleet_capacity_total
```

不要叫：

```text
line_capacity
```

以免和 TPF2 `rate` 混淆。

---

# 5. 推导 Headway 类指标

已有：

```text
frequency_seconds
```

则可以提供：

```text
departures_per_hour
```

公式：

```text
3600 / frequency_seconds
```

标为：

```text
DERIVED
```

例如：

```json
{
  "frequency_seconds": 120,
  "departures_per_hour": 30
}
```

必须在 source metadata 写公式。

---

# 6. Fleet Capacity

新增派生：

```text
fleet_capacity_total
```

公式：

```text
sum(vehicle.capacity_total)
```

以及：

```text
average_vehicle_capacity
```

公式：

```text
fleet_capacity_total / vehicle_count
```

这些都不依赖实时 load。

---

# 7. Line Structural Diagnostics

建立确定性规则。

新增：

```text
diagnose_line_structure(line_id)
```

只分析：

```text
stop_count
vehicle_count
frequency
throughput
fleet capacity
```

例如规则：

```text
NO_STOPS
SINGLE_STOP
NO_VEHICLES
VERY_LONG_HEADWAY
VERY_SHORT_HEADWAY
HIGH_VEHICLE_COUNT
```

所有阈值必须作为参数或配置。

不要把规则结论叫：

```text
亏损
运力不足
拥堵
```

因为缺少直接数据。

使用：

```text
structural warning
```

---

# 8. Network-wide Diagnostics

新增：

```text
diagnose_transport_network
```

返回：

```text
stations_without_lines

lines_without_vehicles

unassigned_vehicles

broken_references

single_stop_lines

long_headway_lines

short_headway_lines

high_vehicle_count_lines
```

所有结果必须有 evidence。

---

# 9. Evidence Schema

所有诊断统一：

```json
{
  "code": "LONG_HEADWAY",

  "severity": "warning",

  "entity_type": "line",

  "entity_id": 123,

  "evidence": {
    "frequency_seconds": 900,
    "threshold_seconds": 600
  },

  "interpretation": "The line has a long verified service interval."
}
```

不要只返回文字。

---

# 10. 不要把 Rule 直接写成经营结论

禁止：

```text
frequency > 600
→ LINE_UNPROFITABLE
```

允许：

```text
frequency > 600
→ LONG_HEADWAY
```

禁止：

```text
vehicle_count > 10
→ TOO_MANY_VEHICLES
```

更准确：

```text
HIGH_VEHICLE_COUNT
```

是否“太多”留给 Agent 综合判断。

---

# 11. Line Comparison Tool

新增：

```text
compare_lines
```

参数：

```text
line_ids[]
```

返回表格化结构：

```text
name
stop_count
vehicle_count
frequency_seconds
throughput
fleet_capacity_total
average_vehicle_capacity
```

这样 Agent 可以直接：

> 比较线路 3、线路 6、线路 23。

---

# 12. Line Ranking Tools

增加少量确定性排序：

```text
rank_lines_by_frequency

rank_lines_by_throughput

rank_lines_by_vehicle_count

rank_lines_by_fleet_capacity
```

不要为每个排序做独立复杂逻辑。

可以统一：

```text
rank_lines(metric, order, limit)
```

允许 metric whitelist：

```text
frequency_seconds
throughput
vehicle_count
fleet_capacity_total
```

---

# 13. Station Connectivity Analysis

利用：

```text
lines_by_station
```

增加：

```text
get_station_connectivity
```

返回：

```text
line_count
line_ids
connected_station_groups
```

其中 connected station groups 可从：

```text
所有经过本站的线路
→ 其他 stops
```

派生。

---

# 14. Transfer Hub Analysis

新增：

```text
rank_transfer_stations
```

按：

```text
line_count
```

进行排名。

这不是“客流量最大的站”。

必须明确：

```text
connectivity ranking
```

而不是：

```text
traffic ranking
```

---

# 15. Build Network Graph

正式建立 Python 侧：

```text
TransportGraph
```

Node：

```text
StationGroup
```

Edge：

```text
Line connection
```

每条 Line 可生成：

```text
station[i]
↔
station[i+1]
```

Edge metadata：

```text
line_id
line_name
frequency_seconds
throughput
```

---

# 16. 图分析能力

第一版只做：

```text
degree
connected components
isolated stations
```

以及：

```text
shortest transfer path
```

不做地理轨道寻路。

例如：

```text
find_station_route(source_station_id, target_station_id)
```

返回：

```text
Station A
→ Line 3
→ Station B
→ Line 7
→ Station C
```

这是“现有公共交通网络的换乘图”。

---

# 17. Distinguish Graph Route from Physical Path

必须明确：

```text
find_station_route
```

不是：

```text
铁路轨道路径
```

也不是：

```text
道路导航
```

只是：

```text
line/station connectivity graph
```

避免 Agent 误解。

---

# 18. Vehicle Fleet Summary

新增：

```text
get_fleet_summary
```

返回：

```text
vehicle_count
assigned_vehicle_count
unassigned_vehicle_count

capacity_total
average_capacity

vehicles_by_line
```

Transport mode 仍 UNKNOWN 时不要硬分类。

---

# 19. Capacity Distribution

可以直接分析：

```text
capacity_total
```

例如：

```text
min
max
mean
median
```

以及：

```text
rank_vehicles_by_capacity
```

这是静态车辆能力分析。

---

# 20. 继续保留 Dynamic UNKNOWN

以下 Tool：

```text
find_low_load_vehicles
find_high_waiting_stations
```

不要删除。

继续返回：

```json
{
  "availability": false,
  "results": []
}
```

但 Agent 必须能知道：

```text
没有数据
```

而不是：

```text
没有低载荷车辆
```

---

# 21. 新增 Capabilities Resource

建议增加：

```text
tpf2://capabilities
```

返回：

```json
{
  "vehicle_capacity": "UI_CROSS_VERIFIED",
  "vehicle_load": "UNAVAILABLE",
  "station_waiting": "UNAVAILABLE",
  "line_frequency": "UI_CROSS_VERIFIED",
  "line_throughput": "UI_CROSS_VERIFIED",
  "line_finance": "UNAVAILABLE",
  "company_balance": "..."
}
```

这个非常适合 LLM。

模型可以先读：

```text
tpf2://capabilities
```

再决定能不能回答某个问题。

---

# 22. Tool Description 同样注明限制

例如：

```text
find_low_load_vehicles
```

description 不能让 Agent 误认为当前肯定支持。

改为类似：

```text
Returns low-load vehicles only when current-load telemetry
is available; otherwise reports metric unavailability.
```

---

# 23. Line Finance 暂时冻结

本阶段不要继续暴力 probe：

```text
income
revenue
profit
...
```

只有在：

```text
官方 API
或
游戏自带 Lua source trace
```

出现明确候选时再继续。

---

# 24. Station Waiting 下一阶段 Probe

这是唯一值得继续深入的动态数据路径。

研究：

```text
STATION_GROUP
→ station ids
→ terminal
→ transportNetwork
```

之后尝试：

```text
simPersonSystem.getSimPersonsAtTerminalForTransportNetwork
simCargoSystem.getSimCargoAtTerminalForTransportNetwork
```

必须：

```text
read-only
bounded
max 3 stations
```

并且只输出：

```text
count
primitive numeric fields
```

不要递归 dump 全部 simulated entities。

---

# 25. Vehicle Load 暂时冻结 getInfo 字段猜测

已确认：

```text
cargoInfos
```

主要暴露配置容量。

不要继续猜：

```text
load2
amount2
currentCargo
...
```

除非：

```text
API docs
或
source trace
```

找到新候选。

---

# 26. Phase 8 仍然 READ ONLY

禁止：

```text
buy
sell
build
rename
edit line
take loan
set speed
pause
```

先让诊断层真正稳定。

---

# 27. Phase 8 最终用户能力

完成后用户应该可以问：

```text
哪些线路班次最稀疏？
```

```text
哪几条线路配置的车辆最多？
```

```text
哪些线路总车辆容量最大？
```

```text
哪些车站是目前网络中的主要换乘节点？
```

```text
线路 3 和线路 6 的结构差异是什么？
```

```text
从 Camorino 到 Locarno 在现有线路图上怎么换乘？
```

这些问题全部可以基于当前已经可靠的数据回答。

不要依赖尚未获得的实时载荷或财务数据。

---

# 28. Phase 8 交付物

必须提交：

```text
1. Phase 7 完整 tests 与最终 Live MCP E2E 证据

2. snapshot age 修正

3. capabilities resource

4. Line scorecard

5. structural diagnostics

6. network diagnostics

7. compare_lines

8. rank_lines

9. Station connectivity

10. TransportGraph

11. transfer/path query

12. fleet summary

13. evidence schema

14. station terminal/network probe

15. company balance UI cross-check

16. Python tests

17. Live MCP session

18. diagnostics
```

Phase 8 核心不是继续“猜更多 TPF2 字段”，而是：

```text
充分利用已经验证可靠的数据，
把 MCP 从“状态读取器”
升级成“可解释的交通网络诊断器”。
```