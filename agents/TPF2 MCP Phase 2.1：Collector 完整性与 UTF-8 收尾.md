# TPF2 MCP Phase 2.1：Collector 完整性验证与工程收尾

当前 Phase 2 审查结果：

已真实验证：

```text
Town Collector       PASS
Industry Collector   PASS
Company entity       PASS
World Snapshot       PASS
File Bridge          PASS
Live MCP E2E         PASS
```

尚未完成：

```text
Station non-empty verification
Line non-empty verification
Vehicle non-empty verification
Company finance fields
UTF-8 MCP output
Python MockBridge test bug
```

本阶段不要增加 Analysis、路线推荐、自动建设等功能。

目标是把 Phase 2 数据层完整收尾。

---

## 1. 修复 Python MockBridge fixture bug

当前：

```python
Path(__file__).resolve().parents[3]
```

会使 fixture 路径跳出项目目录。

不要让生产代码自动寻找：

```text
tests/fixtures
```

修改 MockBridge：

```python
MockBridge(fixture: Path)
```

测试显式传入：

```text
tests/fixtures/world_snapshot_001.json
```

如果需要默认 Mock 数据，则把默认 fixture 移到：

```text
src/tpf2_mcp/fixtures/
```

或 package resources。

要求：

```text
python -m unittest discover -s tests -v
```

在正确安装 package 后全部 PASS。

README 中提供标准测试方式：

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

禁止依赖手动设置 PYTHONPATH。

---

## 2. 修复 MCP UTF-8

当前真实：

```text
industries.json
```

UTF-8 正常。

但：

```text
mcp-session.jsonl
```

中文出现：

```text
����
```

说明问题位于 MCP stdio / PowerShell session capture 路径。

必须定位并修复。

测试必须包含：

```text
铁矿
机械厂
农田
制钢厂
```

等中文字符串。

验证：

```text
TPF2 state.json
→ Python json.loads
→ MCP structuredContent
→ MCP JSON-RPC stdout
→ PowerShell capture
→ mcp-session.jsonl
```

每一阶段内容一致。

Windows PowerShell 脚本必须显式采用 UTF-8。

如果需要：

```powershell
[Console]::InputEncoding
[Console]::OutputEncoding
$OutputEncoding
```

全部设置为 UTF-8。

不要通过 replace 或丢弃中文解决。

---

## 3. 建立固定 MCP_TEST_SAVE

当前存档：

```text
towns      48
industries 193
stations   0
lines      0
vehicles   0
```

无法验证 Station / Line / Vehicle Collector。

创建专门测试存档：

```text
MCP_TEST_SAVE
```

至少包含：

```text
2 个城市

公交：
3 个以上公交站
1 条公交线路
2 辆以上公交车

货运：
2 个货运站
1 条货运线路
至少 1 辆货运车辆
```

尽量保持测试网络简单、可重复。

---

## 4. Station Collector 实机非空验证

目标：

```text
stations > 0
```

至少采集：

```json
{
  "entity_id": 123,
  "entity_type": "station",
  "name": "...",
  "station_count": 1
}
```

研究 TPF2：

```text
STATION_GROUP
STATION
```

二者关系。

明确：

```text
MCP station 的语义到底是 station group
还是单个 station entity。
```

不要混淆。

在：

```text
docs/tpf2-entity-components.md
```

记录关系。

---

## 5. Line Collector 实机验证

要求：

```text
lines >= 2
```

至少返回：

```json
{
  "entity_id": 123,
  "entity_type": "line",
  "name": "...",
  "stop_count": 3
}
```

确认：

```text
LINE component
stops
```

真实字段结构。

如果能可靠获得：

```text
vehicleInfo
```

记录结构，但暂时不强制映射所有字段。

---

## 6. Vehicle Collector 实机验证

要求：

```text
vehicles >= 3
```

至少：

```json
{
  "entity_id": 123,
  "entity_type": "vehicle",
  "name": "...",
  "line_id": 456
}
```

重点确认当前代码：

```lua
TRANSPORT_VEHICLE.line
```

是否真的对应线路 entity id。

如果不是，修改并记录实际关系。

---

## 7. 验证关系一致性

新增测试：

对于每一个：

```text
vehicle.line_id
```

必须能在：

```text
snapshot.lines
```

找到对应：

```text
entity_id
```

如果：

```text
line_id != null
```

但找不到 line：

记录：

```text
BROKEN_REFERENCE
```

同样研究：

```text
line.stops
→ station entity / station group
```

建立第一批实体关系完整性验证。

---

## 8. Company / Account 探针

目前仅有：

```json
{
  "entity_id": 175104,
  "entity_type": "company"
}
```

不要猜 ACCOUNT userdata 字段。

实现独立调研 probe。

对：

```text
PLAYER
ACCOUNT
NAME
```

分别：

```lua
pcall(api.engine.getComponent, ...)
```

在不影响游戏稳定的前提下记录：

```text
type(component)
```

以及可以安全读取的已知公开字段。

目标研究：

```text
money
loan
```

如果公开 API 无法获得：

明确：

```text
UNAVAILABLE VIA CURRENT PUBLIC READ API
```

不要伪造字段。

---

## 9. Company name 编码

当前历史 MCP 留档曾出现：

```text
ī������
```

而 Collector 已选择暂时不暴露 company name。

保持这一策略。

只有明确 UTF-8 来源和字段语义以后再开放。

---

## 10. MCP session 日志改为双向

当前只保存 response。

修改：

```text
tools/test-live-mcp.ps1
```

保存：

```json
{
  "direction": "request",
  "message": {}
}
```

和：

```json
{
  "direction": "response",
  "message": {}
}
```

到：

```text
mcp-session.jsonl
```

必须能够还原：

```text
initialize
tools/list
tools/call
```

完整会话。

---

## 11. Live MCP 增加 Collector Tool 测试

现在不能只测：

```text
get_game_state
```

增加：

```text
get_towns
get_town

get_industries
get_industry

get_stations
get_station

get_lines
get_line

get_vehicles
get_vehicle
```

至少对每个 collection：

```text
plural tool
+
singular tool
```

各测试一次。

例如：

```text
get_lines
→ 取得第一条 line id
→ get_line(id)
→ 两者数据一致
```

---

## 12. Snapshot Integrity Test

增加 Python 验证工具：

```text
tools/validate-snapshot.py
```

至少检查：

```text
schema_version
unique entity_id per collection
collector count == actual list length
vehicle.line_id references existing line
required base fields
JSON UTF-8 validity
```

输出：

```text
Town .......... PASS (48)
Industry ...... PASS (193)
Station ....... PASS (5)
Line .......... PASS (2)
Vehicle ....... PASS (4)
References .... PASS
UTF-8 ......... PASS
```

---

## 13. Collector 状态增加验证级别

目前：

```json
{
  "ok": true,
  "count": 0
}
```

不能区分：

```text
collector 实际验证过
```

还是：

```text
当前存档没有数据
```

可在 diagnostics，而非 Snapshot runtime schema 中增加测试报告：

```text
LIVE_NON_EMPTY
LIVE_EMPTY
NOT_TESTED
```

例如：

```text
town       LIVE_NON_EMPTY
industry   LIVE_NON_EMPTY
station    LIVE_NON_EMPTY
line       LIVE_NON_EMPTY
vehicle    LIVE_NON_EMPTY
```

不要把这种开发测试状态塞进正常游戏状态协议，单独写：

```text
diagnostics/verification.json
```

---

## 14. 固化验证数量

测试存档完成后记录：

```text
expected minimums
```

不要要求 exact count，防止 TPF2 自动生成变化。

例如：

```json
{
  "towns_min": 2,
  "industries_min": 1,
  "stations_min": 3,
  "lines_min": 2,
  "vehicles_min": 3
}
```

---

## 15. 暂时不要扩展字段

本轮主要目标是：

```text
非空枚举
ID
Name
实体关系
UTF-8
```

不要同时研究几十个：

```text
profit
frequency
cargo load
production
shipment
population
```

这些放下一阶段。

---

# Phase 2.1 验收标准

最终要求：

```text
Town        > 0
Industry    > 0
Station     > 0
Line        > 0
Vehicle     > 0
Company     = 1
```

并且：

```text
MCP get_towns       PASS
MCP get_industries  PASS
MCP get_stations    PASS
MCP get_lines       PASS
MCP get_vehicles    PASS
```

至少有：

```text
vehicle → line
```

关系经过真实验证。

所有中文：

```text
TPF2
→ state.json
→ Python
→ MCP
→ diagnostics
```

保持 UTF-8 无损。

Python tests：

```text
ALL PASS
```

---

# Phase 2.1 交付物

提交：

```text
1. 完整源码
2. Python unit test 输出
3. state.json
4. towns.json
5. industries.json
6. stations.json
7. lines.json
8. vehicles.json
9. company.json
10. verification.json
11. snapshot validation 输出
12. UTF-8 验证结果
13. mcp-session.jsonl
14. stdout.txt
15. docs/tpf2-entity-components.md
16. 当前 UNKNOWN 字段清单
```

Phase 2.1 完成后停止。

不要进入自动经营或 Analysis。