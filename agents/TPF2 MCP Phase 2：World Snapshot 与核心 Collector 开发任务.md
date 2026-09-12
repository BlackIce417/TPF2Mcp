# TPF2 MCP Phase 2：World Snapshot 与核心 Collector

Phase 1 已通过核心验收。

已通过真实 TPF2 验证：

```text
Lua 5.2
require
io.open read/write
absolute path
api
api.engine
api.engine.util.getWorld()
api.engine.util.getPlayer()

Python → TPF2 ping
TPF2 → Python pong

Python → get_game_state
TPF2 → api.engine → game state
```

已确认当前 TPF2 Lua 环境：

```text
os.rename unavailable
os.remove unavailable
```

因此继续保留：

```text
responses/<request_id>.json
responses/<request_id>.ready
```

文件 Bridge 协议。

不要重新设计 IPC。

本阶段目标由“验证通信”转为：

```text
构建稳定的 TPF2 World Snapshot 数据层。
```

---

# 1. 本阶段核心目标

实现真实：

```text
Company
Town
Industry
Station
Line
Vehicle
```

数据采集。

最终：

```text
get_game_state
```

至少返回：

```json
{
  "game": {},
  "company": {},
  "towns": [],
  "industries": [],
  "stations": [],
  "lines": [],
  "vehicles": []
}
```

这些字段不得继续全部为空。

---

# 2. 第一任务：研究 TPF2 Entity / Component API

不要根据记忆猜 API。

针对真实 Transport Fever 2 API 调研：

```text
api.engine.forEachEntity
api.engine.getComponent
api.engine.getComponentType
api.engine.system.*
```

以及与以下实体有关的 component：

```text
Town
Industry
Station
Line
Vehicle
Company / Player
```

把实际 API 调研记录到：

```text
docs/tpf2-entity-components.md
```

每项必须包含：

```text
API
用途
参数
返回结构
真实运行结果
对应实体类型
```

---

# 3. 实现通用 Collector Framework

新增：

```text
res/scripts/tpf2_mcp/collectors/
```

结构：

```text
collectors/
├── common.lua
├── company.lua
├── town.lua
├── industry.lua
├── station.lua
├── line.lua
└── vehicle.lua
```

---

# 4. common.lua

建立通用：

```lua
safe_get_component(...)
safe_for_each_entity(...)
safe_collect(...)
```

必须满足：

单个 entity 出错：

```text
不得导致整个 snapshot 失败。
```

例如：

```lua
local ok, result = pcall(...)
```

记录：

```text
entity_id
component
error
```

---

# 5. Normalized Entity 格式

所有 Collector 输出统一基础字段：

```json
{
  "entity_id": 123,
  "entity_type": "town",
  "name": "...",
  "position": {
    "x": 0,
    "y": 0,
    "z": 0
  }
}
```

如果字段不可获得：

```text
省略该字段或明确 null。
```

不要伪造。

---

# 6. Town Collector

第一优先级先只实现 Town。

目标：

```text
get_towns
get_town
```

Town 至少尝试获得：

```text
entity_id
name
position
population
```

如 TPF2 API 中能可靠获得，再扩：

```text
jobs
commercial
industrial
residential
```

但第一版不要强制。

---

# 7. Town 单独验收

Town Collector 完成之后必须先停下来验证。

真实存档至少找到：

```text
>= 3 towns
```

输出例如：

```json
[
  {
    "entity_id": 123,
    "name": "A",
    "population": 512
  },
  {
    "entity_id": 456,
    "name": "B",
    "population": 291
  }
]
```

保存：

```text
diagnostics/.../towns.json
```

确认成功以后才继续 Industry。

---

# 8. Industry Collector

实现：

```text
entity_id
name/type
position
```

进一步研究是否能取得：

```text
production
shipment
transport
input cargo
output cargo
```

如果某字段不能可靠取得：

```text
记录 UNKNOWN
```

不要猜。

---

# 9. Station Collector

实现：

```text
entity_id
name
position
station type
```

优先研究：

```text
passenger/cargo
terminal
waiting cargo/passengers
connected lines
```

但第一阶段 Station 只要求：

```text
能够枚举真实车站。
```

---

# 10. Line Collector

至少：

```text
entity_id
name
transport_mode
stops
vehicle_count
```

进一步研究：

```text
frequency
rate
profit/revenue
```

不能获得则暂缓。

---

# 11. Vehicle Collector

至少：

```text
entity_id
name/model
line_id
```

如可靠：

```text
capacity
load
maintenance
age
position
```

逐步加入。

---

# 12. Company / Finance

研究 Player Entity 对应 component/system。

至少尝试获得：

```text
money
loan
```

如不能通过公开 API 获得：

```text
明确标记 limitation。
```

不要用硬编码内存或非公开方法替代。

---

# 13. Collector Metadata

Snapshot 增加：

```json
{
  "metadata": {
    "sequence": 1,
    "timestamp": 0,

    "collector_status": {
      "towns": {
        "ok": true,
        "count": 10
      },

      "industries": {
        "ok": true,
        "count": 28
      }
    }
  }
}
```

这样 MCP 能知道：

```text
[] 是真的没有实体
```

还是：

```text
Collector 失败。
```

---

# 14. Snapshot 错误隔离

例如：

```text
Town PASS
Industry PASS
Station ERROR
Line PASS
```

最终 snapshot 仍返回：

```json
{
  "towns": [...],
  "industries": [...],
  "stations": [],
  "lines": [...]
}
```

同时：

```json
"collector_status": {
  "stations": {
    "ok": false,
    "error": "..."
  }
}
```

---

# 15. 新增 MCP Tools

Town 验证之后增加：

```text
get_towns
get_town
```

然后依次：

```text
get_industries
get_industry

get_stations
get_station

get_lines
get_line

get_vehicles
get_vehicle
```

不要让这些 tool 直接访问文件。

必须：

```text
MCP Tool
 ↓
Bridge / Snapshot layer
 ↓
Normalized model
```

---

# 16. Snapshot Cache

本阶段加入最简单 cache。

不要 MCP 每执行：

```text
get_town
```

就要求 TPF2 全图重新扫描。

实现：

```text
WorldSnapshot cache
```

由：

```text
get_game_state
```

或周期性 update 刷新。

MCP 对：

```text
get_towns
get_town
```

从最新 snapshot 查询。

---

# 17. 刷新策略

第一版：

```text
最多每 1~2 秒刷新一次。
```

不要：

```text
每帧完整扫描游戏。
```

增加配置：

```lua
snapshot_refresh_interval = ...
```

并记录实际 snapshot generation time。

---

# 18. 性能计时

每个 Collector 记录：

```text
duration
count
```

例如：

```json
{
  "towns": {
    "count": 12,
    "duration_ms": 1.8
  }
}
```

如果 Lua 无高精度计时 API：

```text
使用实际可用能力，
并注明精度。
```

---

# 19. 修复当前 api_status

当前最终源码已经使用：

```text
runtime_verified
```

确保：

```text
安装到游戏中的版本
诊断文件
仓库源码
```

完全一致。

不要再出现：

```text
diagnostics:
documented_not_runtime_verified

source:
runtime_verified
```

这种版本错位。

---

# 20. diagnostics manifest 加版本信息

增加：

```json
{
  "git_commit": "...",
  "mod_version": "...",
  "schema_version": 1
}
```

如果目录不是 git repo：

```text
git_commit = null
```

不得伪造。

---

# 21. 修复日志刷屏

当前：

```text
[tpf2-mcp][INFO] bridge probe completed
```

存在大量重复。

调查 game script 生命周期。

日志增加：

```text
runtime_instance
thread/context
event
```

至少区分：

```text
ENGINE
UI
UNKNOWN
```

避免后续 Collector 日志无法分析。

---

# 22. MCP Live E2E 测试

本阶段补齐上一阶段最后一个证据。

新增：

```text
tools/test-live-mcp.ps1
```

必须真实：

```text
启动 Python MCP Server
      ↓
initialize
      ↓
tools/list
      ↓
tools/call get_game_state
      ↓
MCP Server
      ↓
Bridge
      ↓
TPF2
      ↓
返回真实 world_entity/player_entity
```

输出：

```text
[1/3] MCP initialize ........ PASS
[2/3] tools/list ............ PASS
[3/3] get_game_state ........ PASS

LIVE MCP E2E PASS
```

保存原始 JSON-RPC：

```text
diagnostics/<timestamp>/mcp-session.jsonl
```

---

# 23. 暂时不要做 Analysis

本阶段禁止：

```text
find_unprofitable_lines
find_overcrowded_stations
find_supply_opportunities
AI route planner
```

因为这些依赖 Collector 数据。

---

# 24. 暂时不要写游戏操作

禁止：

```text
pause
buy
sell
rename
build
bulldoze
```

Phase 2 仍然完全：

```text
READ ONLY
```

---

# 25. 开发顺序

严格：

```text
Entity API research

↓

common collector

↓

Town
验证

↓

Industry
验证

↓

Station
验证

↓

Line
验证

↓

Vehicle
验证

↓

Company
验证

↓

World Snapshot

↓

MCP query tools

↓

Live MCP E2E
```

---

# 26. 本阶段交付物

最终提供：

```text
1. 完整代码

2. 完整目录树

3. docs/tpf2-entity-components.md

4. World Snapshot 示例

5. towns.json
6. industries.json
7. stations.json
8. lines.json
9. vehicles.json
10. company.json

11. collector status

12. Python unit test

13. LIVE TPF2 collector test

14. LIVE MCP E2E test

15. stdout.txt

16. heartbeat.json

17. mcp-session.jsonl

18. diagnostics manifest

19. 当前不能取得的 TPF2 字段列表
```

---

# 27. Phase 2 验收目标

最终必须能够通过 MCP 回答：

```text
当前地图有哪些城市？
```

Agent：

```text
get_towns()
```

返回真实 TPF2 城市。

以及：

```text
当前有哪些线路？
```

Agent：

```text
get_lines()
```

返回真实线路。

Phase 2 的核心不是智能分析，而是：

```text
把真实 TPF2 世界稳定、准确、结构化地暴露给 MCP。
```