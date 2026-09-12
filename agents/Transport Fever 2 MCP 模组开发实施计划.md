# Transport Fever 2 MCP 模组开发实施计划

## 1. 项目目标

开发一套面向 **Transport Fever 2（TPF2）** 的 MCP 系统，使外部 AI Agent（如 ChatGPT、Claude、Codex 等）能够：

1. 读取当前游戏世界状态；
2. 查询城市、产业、车站、线路、车辆、财务等信息；
3. 对运输网络进行结构化分析；
4. 在后续阶段执行部分游戏内操作；
5. 最终形成一个可扩展的 “TPF2 Copilot / AI Operator”。

项目必须采用分层设计，不允许把所有逻辑直接堆在 TPF2 Lua 模组中。

整体架构划分为：

```text
LLM / Agent
    │
    │ MCP
    ▼
External MCP Server
    │
    │ IPC / Bridge Protocol
    ▼
TPF2 MCP Mod
    │
    ▼
Transport Fever 2 API
```

---

# 2. 第一原则

本项目第一阶段的核心目标不是实现大量 MCP Tools，而是验证：

```text
TPF2 Lua
    ↕
外部进程
```

之间是否存在稳定、可重复、低风险的数据交换方法。

必须先完成一个 Bridge MRE：

```text
游戏内 Lua 产生测试状态
        ↓
传递给外部程序
        ↓
外部程序返回 command
        ↓
Lua 接收到 command
        ↓
游戏内记录执行结果
```

只有 Bridge MRE 验证成功之后，才进入正式 MCP 开发。

---

# 3. 总体目录结构

整个仓库建议：

```text
tpf2-mcp/
│
├── README.md
├── docs/
├── tpf2_mod/
├── mcp_server/
├── protocol/
├── tests/
├── tools/
└── examples/
```

详细结构：

```text
tpf2-mcp/
│
├── README.md
├── LICENSE
├── .gitignore
│
├── docs/
│   ├── architecture.md
│   ├── bridge.md
│   ├── protocol.md
│   ├── tpf2-api-notes.md
│   ├── mcp-tools.md
│   ├── development.md
│   └── troubleshooting.md
│
├── tpf2_mod/
│   │
│   ├── mod.lua
│   ├── strings.lua
│   │
│   └── res/
│       ├── config/
│       │   └── game_script/
│       │       └── tpf2_mcp.lua
│       │
│       └── scripts/
│           └── tpf2_mcp/
│               │
│               ├── core/
│               │   ├── runtime.lua
│               │   ├── state.lua
│               │   ├── config.lua
│               │   └── logger.lua
│               │
│               ├── collectors/
│               │   ├── game.lua
│               │   ├── finance.lua
│               │   ├── town.lua
│               │   ├── industry.lua
│               │   ├── station.lua
│               │   ├── line.lua
│               │   └── vehicle.lua
│               │
│               ├── commands/
│               │   ├── game.lua
│               │   ├── line.lua
│               │   ├── vehicle.lua
│               │   └── dispatcher.lua
│               │
│               ├── bridge/
│               │   ├── bridge.lua
│               │   ├── request.lua
│               │   ├── response.lua
│               │   └── transport.lua
│               │
│               ├── serializers/
│               │   ├── json.lua
│               │   ├── entity.lua
│               │   └── normalize.lua
│               │
│               └── ui/
│                   └── status_panel.lua
│
├── mcp_server/
│   │
│   ├── pyproject.toml
│   │
│   ├── src/
│   │   └── tpf2_mcp/
│   │       ├── __init__.py
│   │       ├── server.py
│   │       ├── config.py
│   │       ├── bridge.py
│   │       ├── protocol.py
│   │       │
│   │       ├── tools/
│   │       │   ├── game.py
│   │       │   ├── finance.py
│   │       │   ├── towns.py
│   │       │   ├── industries.py
│   │       │   ├── stations.py
│   │       │   ├── lines.py
│   │       │   ├── vehicles.py
│   │       │   └── analysis.py
│   │       │
│   │       ├── resources/
│   │       │   ├── world.py
│   │       │   ├── towns.py
│   │       │   ├── industries.py
│   │       │   └── transport.py
│   │       │
│   │       └── analysis/
│   │           ├── profitability.py
│   │           ├── congestion.py
│   │           ├── supply_chain.py
│   │           └── network.py
│   │
│   └── tests/
│
├── protocol/
│   ├── README.md
│   ├── request.schema.json
│   ├── response.schema.json
│   ├── snapshot.schema.json
│   └── error.schema.json
│
├── tests/
│   ├── fixtures/
│   ├── integration/
│   └── protocol/
│
└── examples/
    ├── snapshots/
    ├── commands/
    └── mcp-client/
```

---

# 4. Phase 0：TPF2 Mod API 调研

首先不要急着写 MCP。

需要确认 TPF2 游戏脚本中以下能力。

## 4.1 确认 Lua 环境

调查：

```text
Lua 版本
允许 require 哪些模块
文件读写能力
可写目录
是否可以 io.open
是否允许 os.*
是否允许 socket
是否允许 ffi
是否允许调用 DLL / shared library
```

输出：

```text
docs/tpf2-api-notes.md
```

必须记录实际测试结果，禁止单纯依据猜测。

---

# 5. Phase 1：Bridge MRE

这是整个项目最高优先级任务。

目标：

```text
TPF2
   ↓
state
   ↓
Bridge
   ↓
Python

Python
   ↓
command
   ↓
Bridge
   ↓
TPF2
```

---

## 5.1 首选方案

首先验证文件 IPC。

例如：

```text
bridge/
├── state.json
├── command.json
├── response.json
└── heartbeat.json
```

TPF2：

```text
写 state.json
读取 command.json
写 response.json
```

Python：

```text
读取 state.json
写 command.json
读取 response.json
```

必须考虑：

```text
原子写入
临时文件 rename
文件锁
request_id
sequence
timestamp
schema_version
```

---

## 5.2 Bridge Request 格式

统一格式：

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "command": "get_game_state",
  "params": {},
  "timestamp": 0
}
```

Response：

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "ok": true,
  "result": {},
  "error": null
}
```

错误：

```json
{
  "schema_version": 1,
  "request_id": "uuid",
  "ok": false,
  "result": null,
  "error": {
    "code": "ENTITY_NOT_FOUND",
    "message": "entity 1234 not found"
  }
}
```

---

# 6. Phase 2：最小状态读取

完成 Bridge 后开始读取游戏。

第一版 Collector 只实现：

```text
game
finance
town
industry
station
line
vehicle
```

不要一开始采集所有 component。

---

# 7. World Snapshot

建立统一：

```text
WorldSnapshot
```

结构：

```json
{
  "schema_version": 1,

  "game": {},

  "company": {},

  "towns": [],

  "industries": [],

  "stations": [],

  "lines": [],

  "vehicles": []
}
```

要求所有 TPF2 内部对象经过 Normalize 后才能进入 Snapshot。

禁止 MCP Server 直接依赖 TPF2 内部 Lua table 结构。

---

# 8. Entity ID 原则

TPF2 内部对象统一用：

```text
entity_id
```

例如：

```json
{
  "entity_id": 1823,
  "entity_type": "town",
  "name": "Berlin"
}
```

MCP 层不得重新生成虚假 ID。

---

# 9. Collector 实现

建议统一接口：

```lua
collect()
```

例如：

```text
collectors/town.lua
collectors/industry.lua
collectors/line.lua
```

所有 Collector 必须：

```text
1. 捕获 API 异常
2. 避免单个实体导致整个 Snapshot 失败
3. 对 nil 做处理
4. 保证输出结构稳定
```

---

# 10. 第一阶段 MCP Tools

正式 MCP 第一版只允许做 15 个左右。

## Game

```text
get_game_state
get_company_finance
```

## Town

```text
get_towns
get_town
```

## Industry

```text
get_industries
get_industry
```

## Station

```text
get_stations
get_station
```

## Line

```text
get_lines
get_line
```

## Vehicle

```text
get_vehicles
get_vehicle
```

## Analysis

```text
find_unprofitable_lines
find_overcrowded_stations
get_network_summary
```

第一版 MCP 必须以 READ ONLY 为主。

---

# 11. MCP Resources

同时提供：

```text
tpf2://world
tpf2://game
tpf2://finance
tpf2://towns
tpf2://industries
tpf2://stations
tpf2://lines
tpf2://vehicles
```

Resources 应主要适合读取完整上下文。

Tools 用于：

```text
查询
过滤
分析
执行操作
```

---

# 12. 分析层

不要让 Agent 自己从几万个原始对象中计算所有问题。

增加：

```text
analysis/
```

---

## 12.1 盈利性分析

实现：

```text
find_unprofitable_lines
```

至少返回：

```json
{
  "line_id": 1001,
  "name": "Line 1",
  "revenue": 0,
  "cost": 0,
  "profit": 0,
  "vehicle_count": 0,
  "status": "loss"
}
```

---

## 12.2 拥堵分析

实现：

```text
find_overcrowded_stations
```

返回：

```text
station
waiting_cargo
waiting_passengers
related_lines
severity
```

---

## 12.3 网络摘要

```text
get_network_summary
```

返回类似：

```text
town_count
industry_count
station_count
line_count
vehicle_count
profitable_lines
loss_lines
overcrowded_stations
```

---

# 13. Phase 3：地图局部查询

不要每次把全地图发送给 LLM。

实现：

```text
get_map_region
```

参数：

```text
center_x
center_y
radius
entity_types
```

返回附近：

```text
towns
industries
stations
roads
tracks
```

如果道路、轨道读取困难，可以先只实现实体查询。

---

# 14. Nearby API

实现：

```text
find_nearby_entities
```

例如：

```json
{
  "position": [1200, 2500],
  "radius": 5000,
  "types": [
    "industry"
  ]
}
```

这将成为后续路线规划的基础。

---

# 15. Phase 4：产业链语义层

实现产业图模型：

```text
producer
    ↓
cargo
    ↓
consumer
```

实现：

```text
get_supply_chain
find_unserved_industries
find_supply_opportunities
```

例如：

```text
Farm
 ↓ grain
Food Processing Plant
 ↓ food
Town
```

输出必须包含：

```text
entity
cargo_type
production
shipment
transport_percentage
distance
existing_service
```

先做分析，不进行自动建设。

---

# 16. Phase 5：写操作

只有读取功能稳定之后才允许添加。

第一批写操作：

```text
pause_game
set_game_speed
rename_line
```

第二批：

```text
set_vehicle_line
sell_vehicle
```

第三批：

```text
buy_vehicle
modify_line
```

最后再研究：

```text
build_station
build_track
build_road
bulldoze
```

---

# 17. Command 权限等级

必须设计权限控制。

```text
LEVEL 0
READ ONLY

LEVEL 1
SAFE WRITE

LEVEL 2
ECONOMIC WRITE

LEVEL 3
WORLD MODIFY
```

例如：

```text
get_lines
→ LEVEL 0

rename_line
→ LEVEL 1

buy_vehicle
→ LEVEL 2

build_track
→ LEVEL 3

bulldoze
→ LEVEL 3
```

配置：

```text
config.json
```

例如：

```json
{
  "max_permission_level": 1
}
```

默认：

```text
READ ONLY
```

---

# 18. Dry Run

所有经济或地图修改操作以后必须支持：

```text
dry_run=true
```

例如：

```text
build_track
```

先返回：

```json
{
  "estimated_cost": 3200000,
  "operations": [
    "build track",
    "build station"
  ]
}
```

再决定是否执行。

---

# 19. MCP Server 设计

推荐 Python。

核心：

```text
server.py
bridge.py
protocol.py
```

其中：

```text
server.py
```

只负责 MCP 注册。

```text
bridge.py
```

只负责和 TPF2 通信。

```text
analysis/
```

负责业务逻辑。

严禁：

```text
MCP Tool
→ 直接操作文件
```

正确：

```text
MCP Tool
↓
Bridge Client
↓
Bridge Protocol
↓
TPF2
```

---

# 20. Cache

TPF2 不需要每个 MCP 请求都重新遍历整个世界。

建立：

```text
snapshot cache
```

例如：

```text
snapshot_age
snapshot_sequence
```

MCP：

```text
get_world_snapshot(force_refresh=false)
```

---

# 21. Snapshot 增量更新

第一版可以全量 Snapshot。

后续可增加：

```text
snapshot seq 100
snapshot seq 101
```

Delta：

```json
{
  "added": [],
  "updated": [],
  "removed": []
}
```

暂时不要在 MVP 实现。

只需要预留 architecture。

---

# 22. 日志系统

Lua：

```text
[tpf2-mcp][INFO]
[tpf2-mcp][WARN]
[tpf2-mcp][ERROR]
```

Python：

```text
INFO
DEBUG
WARNING
ERROR
```

日志至少包含：

```text
request_id
command
duration
error
```

---

# 23. Heartbeat

Bridge 必须实现：

```text
heartbeat
```

例如：

```json
{
  "game_running": true,
  "bridge_ready": true,
  "snapshot_seq": 123,
  "last_update": 123456
}
```

MCP 提供：

```text
get_bridge_status
```

---

# 24. 自动测试

Python 必须有 pytest。

至少：

```text
test_protocol.py
test_bridge.py
test_snapshot.py
test_tools.py
```

Lua 不方便做完整单元测试时，可以把 Collector 输出保存为 fixture。

例如：

```text
tests/fixtures/world_snapshot_001.json
```

Python 分析层必须完全可以基于 fixture 离线测试。

---

# 25. Mock Transport

这是重点。

必须实现：

```text
MockBridge
```

使没有启动 TPF2 时，也能：

```text
MCP Server
→ MockBridge
→ fixture JSON
```

这样绝大部分 MCP 功能开发不依赖游戏实时运行。

---

# 26. CLI Debug 工具

额外实现：

```text
python -m tpf2_mcp.cli status
python -m tpf2_mcp.cli snapshot
python -m tpf2_mcp.cli towns
python -m tpf2_mcp.cli lines
```

这样调试 Bridge 时不用一直连接 MCP Client。

---

# 27. 性能要求

需要测量：

```text
100 towns
100 industries
500 stations
100 lines
1000 vehicles
```

情况下：

```text
snapshot generation time
serialization time
snapshot size
MCP response latency
```

必须避免每帧扫描全部 entity。

建议：

```text
定时刷新
事件触发
按需刷新
```

三者组合。

---

# 28. 开发顺序

严格按照：

```text
Phase 0
TPF2 API 调研

↓

Phase 1
Bridge MRE

↓

Phase 2
World Snapshot

↓

Phase 3
MCP Read Tools

↓

Phase 4
Analysis API

↓

Phase 5
Map / Nearby

↓

Phase 6
Industry Chain

↓

Phase 7
Safe Write

↓

Phase 8
Economic Write

↓

Phase 9
Construction
```

不能跳过 Bridge MRE。

---

# 29. 第一里程碑

必须能够做到：

用户问：

```text
分析一下当前这个档为什么亏钱。
```

Agent 可以调用：

```text
get_company_finance
get_lines
get_vehicles
find_unprofitable_lines
```

并得到结构化结果。

---

# 30. 第二里程碑

用户问：

```text
哪些车站现在拥堵最严重？
```

调用：

```text
find_overcrowded_stations
```

返回：

```text
station
waiting
related_lines
severity
```

---

# 31. 第三里程碑

用户问：

```text
现在有哪些值得开发的货运线路？
```

调用：

```text
get_industries
find_supply_opportunities
```

得到产业链候选。

---

# 32. 第四里程碑

实现：

```text
pause_game
set_game_speed
rename_line
```

证明：

```text
LLM
→ MCP
→ Bridge
→ TPF2
```

写操作闭环成功。

---

# 33. Codex 工作方式要求

不要一次性生成整个项目。

按阶段开发，每阶段完成后必须提供：

```text
实现内容
目录变化
核心文件
测试方法
运行方法
已知问题
下一步
```

---

# 34. 每个阶段必须可运行

禁止出现：

```text
placeholder
TODO implementation
pseudo code
```

作为阶段性交付。

如果某 TPF2 API 无法确定，则：

1. 明确标记 UNKNOWN；
2. 创建独立实验；
3. 写最小测试脚本；
4. 根据实际日志确认；
5. 再进入正式代码。

---

# 35. 第一批任务

现在先只做以下任务。

## Task 1

创建完整仓库骨架。

## Task 2

编写：

```text
docs/architecture.md
```

说明整个：

```text
TPF2 Mod
↔ Bridge
↔ MCP Server
```

架构。

## Task 3

建立：

```text
protocol/
```

定义：

```text
request
response
heartbeat
snapshot
error
```

JSON Schema。

## Task 4

创建 TPF2 最小模组：

```text
tpf2_mod/
```

能正常被游戏加载。

## Task 5

创建 Bridge Probe。

实际测试 TPF2 Lua 是否能够：

```text
读取文件
写入文件
访问固定目录
```

## Task 6

如果文件通信成功：

实现：

```text
ping
```

协议：

```text
Python
→ ping
→ TPF2
→ pong
```

## Task 7

实现：

```text
get_game_state
```

作为第一个真正游戏 API。

## Task 8

创建 Python MCP Server Skeleton。

第一个 MCP Tool：

```text
get_bridge_status
```

第二个：

```text
get_game_state
```

---

# 36. 第一阶段验收标准

必须达到：

```text
TPF2 正常启动
↓
模组加载成功
↓
Bridge ready
↓
Python 能发送 ping
↓
TPF2 返回 pong
↓
Python 可以取得 game state
↓
MCP Client 可以调用 get_game_state
```

整个链路：

```text
MCP Client
   ↓
MCP Server
   ↓
Bridge
   ↓
TPF2 Mod
   ↓
TPF2 API
   ↓
TPF2 Mod
   ↓
Bridge
   ↓
MCP Server
   ↓
MCP Client
```

必须实际跑通。

---

# 37. 第一阶段暂时不要实现

暂时禁止花时间实现：

```text
自动铺铁路
自动建站
自动买车
复杂寻路
完整交通图
地形分析
AI 自动经营
几十个 MCP Tools
GUI 美化
```

这些全部放到 Bridge 稳定之后。

---

# 38. README 必须提供

README 至少包含：

```text
项目简介
架构
目录结构
依赖
安装方式
TPF2 模组安装位置
启动 MCP Server
测试 Bridge
测试 MCP
日志位置
FAQ
```

同时给出 Windows 环境命令。

优先考虑：

```text
Windows + Steam Transport Fever 2
```

---

# 39. 最终原则

整个项目始终遵循：

```text
TPF2 API
        ↓
Collector
        ↓
Normalized Model
        ↓
Bridge Protocol
        ↓
MCP
        ↓
LLM
```

不要：

```text
TPF2 Lua table
直接暴露给 LLM
```

也不要：

```text
MCP Tool
直接依赖 TPF2 内部 component 结构
```

核心目标是建立一层长期稳定的：

```text
TPF2 Semantic API
```

未来即使：

```text
TPF2 API 修改
MCP SDK 修改
Bridge Transport 修改
```

也只需要替换其中一层。

---

# 40. 当前立即开始

请先完成：

```text
Phase 0 + Phase 1
```

即：

```text
仓库初始化
目录划分
协议 Schema
最小 TPF2 Mod
Lua IO 能力探测
Bridge MRE
ping/pong
get_game_state
Python Bridge Client
最小 MCP Server
```

完成后停止继续扩展功能。

提交：

```text
1. 完整目录树
2. 所有新增源文件
3. 实际运行日志
4. Bridge 测试结果
5. MCP 调用示例
6. 已确认的 TPF2 Lua 能力
7. 未确认 / 受限制的能力
8. 下一阶段建议
```

如果 Bridge 方案失败，不允许绕过去假装完成 MCP。

必须明确报告：

```text
失败位置
TPF2 Lua 限制
测试证据
尝试过的方案
推荐替代 IPC 设计
```

优先把底层通信链路做可靠，再扩展游戏能力。