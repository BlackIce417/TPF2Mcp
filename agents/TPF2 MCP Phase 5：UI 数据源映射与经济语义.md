# TPF2 MCP Phase 5：UI 数据源映射与运营数据来源调研

Phase 4 已通过。

当前已通过真实 TPF2 UI 交叉验证：

```text
Line:
name
stop_count
vehicle_count

Vehicle:
name
line relationship

Station Group:
name
served lines
```

UI 同时明确存在但当前 MCP 无法读取：

```text
Vehicle:
capacity
max speed
power
current cargo/load

Line:
income
rate/throughput
frequency
cargo/load

Station:
waiting cargo/passengers

Industry:
production / shipment / transport

Company:
current money / finance
```

当前公开 Component userdata 直接字段 probe 已多次返回 nil。

Phase 5 不再以“猜 userdata 字段名”为主要方法。

本阶段核心方法改为：

```text
TPF2 UI
   ↓
寻找 UI 数据来源
   ↓
定位官方 Lua/system/API 调用
   ↓
验证该 API 是否可从 game script 使用
   ↓
Normalized semantic model
   ↓
MCP
```

---

# 1. 第一任务：定位 TPF2 UI 脚本资源

研究游戏安装目录中的：

```text
res/scripts/
res/config/
UI Lua
```

以及 Base Game 相关 package/resource。

重点搜索：

```text
frequency
rate
income
capacity
waiting
cargo
profit
balance
production
shipment
transport
```

不要只 grep 显示文本。

同时搜索 UI label 对应 locale key。

---

# 2. 建立 UI 数据源研究文档

新增：

```text
docs/ui-data-source-map.md
```

结构：

```text
UI Field
UI Window
UI Script
Function
Underlying API/System
Can Game Script Call It?
Live Verified?
Notes
```

例如：

```text
Frequency
Line Window
...
...
UNKNOWN
NO
...
```

所有结论必须有源码或运行证据。

---

# 3. Line Window 作为最高优先级

Phase 4 已有真实 Ground Truth：

线路 91：

```text
income      $5,906,462
throughput  400
frequency   6 min
cargo       130/368
```

线路 29：

```text
income      -$958,495
throughput  92
frequency   36 min
cargo       49/270
```

线路 35：

```text
income      $30,288,364
throughput  341
frequency   6 min
cargo       200/420 + 39/140
```

优先追踪 UI 如何获得：

```text
frequency
rate / throughput
income
cargo / capacity
```

---

# 4. 不要根据 UI 文本反向解析游戏界面

禁止把：

```text
$30,288,364
6 min
200/420
```

通过截图 OCR 或 UI 文本抓取作为正式 MCP 数据源。

UI Ground Truth 只能用于验证。

正式实现必须找到：

```text
UI 底层 API / system data
```

---

# 5. 搜索 line system

重点研究实际存在的：

```text
api.engine.system.lineSystem
api.engine.system.transportVehicleSystem
api.engine.system.stationSystem
api.engine.system.simCargoSystem
```

具体名称以当前 TPF2 API 为准。

不得自行假设存在。

对找到的 system：

```text
列出函数
参数
返回值
UI 使用位置
game script 可调用性
```

---

# 6. Vehicle Window 数据来源

UI 已验证：

```text
capacity
max speed
power
line
```

选择三个真实车辆：

```text
560638
498863
1282331
```

作为固定 Probe 样本。

查找 UI Vehicle Detail Window 的数据构造流程。

目标找到：

```text
vehicle composition
vehicle model config
capacity
power
top speed
cargo configuration
```

---

# 7. 静态车辆数据与动态车辆数据分开

车辆：

```text
capacity
max speed
power
```

很可能来自：

```text
vehicle model config / vehicle composition
```

而：

```text
current load
state
current cargo
```

属于运行时数据。

必须拆成：

```text
VehicleSpec
VehicleRuntime
```

例如：

```json
{
  "spec": {
    "capacity": 285,
    "max_speed_kmh": 120,
    "power_kw": 9600
  },

  "runtime": {
    "load": null,
    "state": 1
  }
}
```

不要把静态和动态字段混在一个来源中。

---

# 8. Vehicle composition

研究当前：

```text
TRANSPORT_VEHICLE
```

是否存在关联 vehicle/config/model entity 的方式。

如需要从：

```text
vehicle entity
→ vehicle configuration
→ multiple models
```

聚合 capacity：

必须验证组合规则。

火车可能由：

```text
locomotive
coach
coach
coach
```

组成。

总 capacity：

```text
sum(passenger/cargo capacity)
```

只有确认 TPF2 UI 也是这样计算后才使用。

---

# 9. Station Window

使用 Ground Truth：

```text
513573
710901
608523
```

定位：

```text
station waiting
cargo waiting
passenger waiting
```

UI 数据来源。

特别注意：

```text
Station Group
Station
Terminal
Cargo waiting
```

可能分别属于不同层级。

建立准确映射：

```text
Station Group
  ↓
Stations
  ↓
Terminals
  ↓
Waiting Cargo
```

如真实结构如此。

---

# 10. Waiting aggregation

如果等待量绑定 Terminal：

必须明确：

```text
station_group.waiting_total
```

如何计算。

例如：

```text
sum(all child station terminal waiting)
```

但必须根据 UI 逻辑验证。

不要自己定义一套和 UI 不一样的计算方式。

---

# 11. Cargo Registry 正式实现

Phase 4 已实机确认：

```text
cargo registry entry_count = 17
```

并有：

```text
LOGS
COAL
IRON_ORE
```

现在正式实现：

```python
CargoRegistry
```

目标：

```json
{
  "cargo_key": "IRON_ORE",
  "display_name": "...",
  "index": ...
}
```

优先使用真实 repository。

禁止维护一份未经验证的固定 cargo list。

---

# 12. Cargo Registry MCP Resource

增加：

```text
tpf2://cargo-types
```

和 Tool：

```text
get_cargo_types
```

用于 Agent 理解当前游戏/模组实际存在的 cargo。

这对未来兼容其他产业 Mod 很重要。

---

# 13. 必须考虑 Mod-added Cargo

Cargo Registry 不能假设永远只有 Vanilla 17 个。

当前 Live Test：

```text
17
```

只是当前存档/模组环境。

设计必须支持：

```text
N cargo types
```

动态枚举。

---

# 14. Line cargo/load

如果 Line UI 的：

```text
130/368
```

来源于车辆总载荷/容量，则找到实际计算链。

明确这两个值的语义：

```text
current load?
average?
rate?
capacity?
vehicle sum?
```

不要因为格式像：

```text
load/capacity
```

就直接这么命名。

---

# 15. Line frequency

找到 UI 调用后明确单位：

```text
seconds
game milliseconds
ticks
```

Normalized：

```json
{
  "frequency_seconds": 360
}
```

UI：

```text
6 min
```

只作为显示层。

---

# 16. Line income

必须明确：

```text
income
```

UI 的时间窗口是什么：

```text
current year?
last 12 months?
rolling period?
lifetime?
```

如果找到 raw history：

保留：

```text
raw_financial_history
```

然后建立：

```text
display_income
```

对应 UI。

不能笼统命名：

```text
profit
```

---

# 17. Company Finance UI

追踪公司余额显示页面的数据源。

当前：

```text
loan = 0
balance = 0
```

需要验证：

```text
balance
```

是否真正对应 UI 现金。

选择当前存档，在 UI 中人工记录：

```text
cash
loan
```

加入：

```text
ui-ground-truth-company.json
```

再做对照。

---

# 18. Industry UI

选择：

```text
Oil refinery
Fuel refinery
Forest
```

至少 3 种 Industry。

UI 人工记录：

```text
industry type
production
shipment
transport
input
output
```

然后定位 Industry Window Lua 数据来源。

---

# 19. Industry Type 优先找 Config Identity

不要把显示名称作为正式类型。

寻找：

```text
construction file
industry config
production recipe
resource key
```

任何稳定内部 identifier。

目标：

```json
{
  "industry_type": "OIL_REFINERY",
  "raw_config_id": "..."
}
```

---

# 20. Industry Recipe

如果找到 production config：

构建：

```json
{
  "inputs": [
    {
      "cargo": "CRUDE",
      "amount": 2
    }
  ],

  "outputs": [
    {
      "cargo": "OIL",
      "amount": 1
    }
  ]
}
```

必须动态读取。

不要硬编码 Vanilla recipe。

---

# 21. Mod Compatibility

所有：

```text
cargo
industry
vehicle
```

语义数据尽量来自 repository/config。

这样未来 Workshop Mod：

```text
新车辆
新产业
新货物
```

仍然能工作。

这是 MCP 项目的重要设计目标。

---

# 22. UI Script 与 Game Script 环境差异

找到 UI API 后，不要直接假设：

```text
game script 可以调用。
```

必须分别测试：

```text
UI thread/state
Engine game script state
```

如果 API 只在 UI 环境可用：

记录：

```text
UI_ONLY
```

然后研究合法的数据桥接方式。

---

# 23. 如需要 UI Thread Collector

如果关键运营数据只存在 UI Lua：

可以设计：

```text
UI Collector
    ↓
game.interface.sendScriptEvent
    ↓
Engine / Bridge
```

或者反向：

```text
Engine
↔
UI event
```

具体根据 TPF2 官方 Game Script/UI event 能力设计。

不要使用 DLL 注入。

---

# 24. UI Collector 必须和 Engine Collector 分离

目录建议：

```text
collectors/
  engine/
  ui/
```

或者：

```text
ui_collectors/
```

不能让：

```text
UI state
Engine state
```

访问方式混在一起。

---

# 25. 数据来源标记

Snapshot v4 开始建议每个高级字段允许带 source metadata。

例如：

```json
{
  "frequency_seconds": 360,

  "_source": {
    "frequency_seconds": "ui_api"
  }
}
```

或者统一 metadata：

```json
{
  "field_sources": {
    "frequency_seconds": "LINE_SYSTEM"
  }
}
```

开发期尤其有价值。

正式 API 可以简化。

---

# 26. Live UI Ground Truth 扩展

继续保留当前截图验证方法。

对于每个新突破字段：

至少验证 3 个样本。

例如 capacity 找到后：

```text
列车42 expected 285
列车45 expected 232
列车145 expected 184
```

必须：

```text
3 / 3 PASS
```

才标记：

```text
LIVE_UI_VERIFIED
```

---

# 27. Phase 5 不要求所有字段成功

研究型阶段允许得到：

```text
AVAILABLE
UI_ONLY
ENGINE_AVAILABLE
UNRESOLVED
```

关键是建立准确的数据源地图。

禁止为了“完成率”提供错误值。

---

# 28. Phase 5 最低成功标准

至少突破以下任意两个：

```text
Vehicle capacity

Line frequency

Station waiting

Line income

Industry production

Company cash
```

并经过 UI Ground Truth 验证。

另外：

```text
Cargo Registry
```

必须正式进入 MCP。

---

# 29. Phase 5 推荐突破顺序

优先：

```text
Vehicle static spec
        ↓
Line frequency
        ↓
Station waiting
        ↓
Company cash
        ↓
Line finance
        ↓
Industry production
```

原因：

Vehicle static spec 很可能最容易从 repository/config 找到。

---

# 30. Phase 5 暂时仍然 READ ONLY

禁止新增：

```text
buy_vehicle
sell_vehicle
edit_line
build_track
build_station
take_loan
```

等写操作。

先把 UI 可见核心状态读取完整。

---

# 31. Phase 5 交付物

提交：

```text
1. docs/ui-data-source-map.md

2. UI Lua/source 搜索结果

3. Vehicle UI data source probe

4. Line UI data source probe

5. Station UI data source probe

6. Company finance UI probe

7. Industry UI probe

8. CargoRegistry implementation

9. get_cargo_types MCP tool/resource

10. 新找到的 API/system 调用

11. UI_ONLY / ENGINE_AVAILABLE 分类

12. Snapshot schema v4（如有新字段）

13. Ground Truth

14. Ground Truth verification

15. Live MCP session

16. Python tests

17. stdout.txt

18. Remaining unresolved fields
```

Phase 5 的核心问题：

```text
“TPF2 UI 已经知道这些数据，
那么 UI 到底从哪里拿到它们？”
```

找到这条数据链，MCP 才能真正获得游戏的运营和经济语义。