# TPF2 MCP Phase 6：UI 数据绑定与 game.interface 数据源研究

Phase 5 已通过 UI Source Mapping 验收。

当前不要进入写操作。

本阶段核心目标：

**系统定位 TPF2 原生 UI 中已经显示的运营数据究竟从哪里获得，并判断能否通过安全的只读接口提供给 MCP。**

---

## 1. 当前已确认事实

Engine Collector 已可靠取得：

```text
Town
Industry entity
Station Group
Line
Vehicle
Company
Cargo Registry
```

关系：

```text
Line → Station
Vehicle → Line
```

Cargo：

```text
api.res.cargoTypeRep.getAll()
api.res.cargoTypeRep.getName(CargoTypeId)
```

Company：

```text
ACCOUNT.balance
ACCOUNT.loan
```

另外已发现原版 UI/guide 脚本存在：

```lua
game.interface.getEntity(
    game.interface.getPlayer()
).balance
```

以及：

```lua
player.loan
```

这表明：

```text
game.interface
```

可能提供与 UI 当前显示状态更接近的数据视图。

---

# 2. 本阶段原则

禁止猜未知 `api.engine.system.*` 方法签名。

优先研究：

```text
游戏安装目录中的原版 Lua UI / gui / game scripts
```

寻找：

```text
UI 显示值
→ Lua variable
→ game.interface / api.engine / repository
```

的完整数据流。

---

# 3. 建立原版 Lua 源码索引

编写：

```text
tools/index-tpf2-lua-sources.py
```

允许用户指定：

```text
TPF2 game install root
```

扫描：

```text
res/scripts/
res/config/
```

等 Lua 文件。

建立：

```text
diagnostics/ui-source-index.json
```

至少索引：

```text
文件
行号
symbol
game.interface 调用
api.engine 调用
api.res 调用
```

---

# 4. 对 UI 字段进行关键词定位

系统搜索：

```text
balance
loan

frequency
rate
throughput

income
revenue
profit
cost

capacity
power
speed

waiting
cargo
passenger

production
shipment
transport
```

不要只 grep 英文 UI 文本。

同时搜索：

```text
getEntity
getEntities
getPlayer
line
station
vehicle
industry
```

等数据调用。

---

# 5. 建立 UI Binding Trace 文档

生成：

```text
docs/ui-binding-traces.md
```

每个指标采用：

```text
UI FIELD
↓
UI script
↓
function
↓
data access
↓
returned object field
↓
candidate MCP source
```

例如 Company balance：

```text
Finance / Player UI
↓
guidesystem.lua
↓
game.interface.getEntity(...)
↓
player.balance
↓
candidate: game.interface player.balance
```

---

# 6. 调研 game.interface 可用环境

必须明确：

```text
game.interface
```

在哪个 Lua Context 可用。

区分：

```text
ENGINE game-script context

UI game-script context

GUI script context
```

不要假设 engine thread 可以直接调用。

实际 probe：

```lua
type(game)
type(game.interface)
type(game.interface.getEntity)
type(game.interface.getPlayer)
```

分别记录 context。

---

# 7. 如果 game.interface 仅存在 UI Thread

不要试图强行从 Engine Context 调用。

设计：

```text
UI Collector
     ↓
sendScriptEvent
     ↓
Engine/Bridge State
```

或者反向：

```text
Engine request
     ↓
UI event
     ↓
game.interface read
     ↓
script event response
     ↓
Bridge
```

具体以 TPF2 game-script 生命周期能力为准。

---

# 8. 建立双 Context 数据架构

如果 UI 数据必须从 UI context 取得，则 Snapshot 分成：

```text
Engine Snapshot
+
UI Snapshot
```

最后 Normalize：

```text
Normalized World Snapshot
```

例如：

```json
{
  "metadata": {
    "sources": {
      "company.balance": "game.interface",
      "vehicle.line_id": "api.engine.component",
      "cargo_types": "api.res"
    }
  }
}
```

---

# 9. 首先验证 Company Balance

这是最简单的 ground truth。

取得：

```text
A = ACCOUNT.balance
B = game.interface player.balance
C = 游戏 UI 显示现金
```

同一 simulation time 比较：

```text
A == B == C
```

至少采样：

```text
3 个时间点
```

包括：

```text
余额发生变化前后
```

生成：

```text
diagnostics/company-balance-ground-truth.json
```

只有通过后才将：

```text
company.balance
```

正式定义为 UI company cash/balance。

---

# 10. Vehicle Manager 源码追踪

重点找车辆管理窗口。

已知 UI 可以显示：

```text
capacity
top speed
power
```

现在从 UI 脚本反推：

```text
Vehicle UI
↓
entity/model lookup
↓
model/config
↓
capacity
speed
power
```

核心目标首先解决：

```text
Vehicle entity
→ Model
```

映射。

只要拿到 model identifier，很多静态参数就可以从：

```text
api.res.modelRep
```

进一步查询。

---

# 11. 区分静态 Vehicle Spec 与动态 Vehicle State

必须分开：

```text
Vehicle Spec
────────────────
capacity
top_speed
power
tractive_effort
weight
running_cost

Vehicle Runtime
────────────────
line_id
load
cargo
speed
state
position
age
condition
```

不能把 Model Spec 当成实时 Vehicle State。

---

# 12. Line Manager 源码追踪

重点定位 UI 中：

```text
frequency
rate
income/result
throughput
cargo bars
vehicle count
```

每个字段必须追踪到：

```text
具体 Lua object field
```

记录示例：

```text
frequency UI
→ xxx.lua
→ data.frequency
→ data source xxx
```

禁止仅根据名字猜。

---

# 13. Station Window 源码追踪

定位：

```text
waiting passengers
waiting cargo
terminal capacity
line destinations
```

重点研究是否 UI 通过：

```text
game.interface.getEntity(station_id)
```

直接取得：

```text
cargo
waiting
```

如果是，这将比猜 `stationSystem` 方法可靠得多。

---

# 14. Industry Window 源码追踪

定位：

```text
production
shipment
transport
input
output
stock
```

如果 Industry UI 使用：

```text
game.interface.getEntity(industry_id)
```

优先解析其返回结构。

---

# 15. 建立安全 UI Entity Probe

如果：

```text
game.interface.getEntity(id)
```

可安全调用，

不要直接 dump userdata 全对象。

建立白名单 probe：

```text
type
id
name
balance
loan
frequency
rate
capacity
waiting
production
shipment
transport
```

逐字段安全读取。

禁止递归序列化整个 userdata。

---

# 16. Source Provenance 必须进入 Schema

每个新指标记录：

```json
{
  "value": 123,
  "source": "game.interface",
  "verified": true
}
```

正常 Snapshot 不一定每个值都包装 object。

可以使用：

```text
metadata.field_sources
```

例如：

```json
{
  "field_sources": {
    "company.balance": "game.interface.player.balance",
    "line.frequency_seconds": "game.interface.line.frequency"
  }
}
```

---

# 17. 三种可信等级

定义：

```text
LEVEL A — UI_CROSS_VERIFIED

Engine/UI source value
==
同一时间游戏 UI 显示值


LEVEL B — ENGINE_VERIFIED

接口安全可读取、语义明确，
但尚未与 UI 对照


LEVEL C — OBSERVED_ONLY

UI 看到了，
但尚未找到程序数据源
```

MCP 只能默认暴露：

```text
A / B
```

C 保持：

```text
availability=false
```

---

# 18. Line Frequency 第一优先级

这是最容易验证的动态指标之一。

已存在 Phase 4 UI Ground Truth：

```text
Line 91 = 6 min
Line 29 = 36 min
Line 35 = 6 min
```

找到 data source 后，同一存档重新验证。

目标：

```json
{
  "frequency_seconds": 360,
  "availability": {
    "frequency": true
  }
}
```

注意 UI：

```text
6 min
```

可能经过：

```text
rounding / formatting
```

所以验证允许考虑 UI 显示舍入。

记录原始值和 UI format 后结果。

---

# 19. Line Finance 第二优先级

UI 已有：

```text
Line 91   5,906,462
Line 29   -958,495
Line 35   30,288,364
```

必须查明这个值实际是：

```text
income
balance
profit
rate
annual result
rolling result
```

不能直接叫：

```text
profit
```

直到 UI 源码明确其语义。

这是本阶段非常重要的一点。

---

# 20. Station Waiting 第三优先级

找到：

```text
waiting count
```

后必须确认是：

```text
当前 total waiting
某 terminal waiting
某 cargo waiting
```

然后再设计 MCP schema。

不要过早统一成：

```text
waiting_total
```

---

# 21. Industry Production 第四优先级

查清：

```text
Production
Shipment
Transport
```

三个 TPF2 UI 指标的真实来源和单位。

不要自己使用：

```text
shipment / production
```

构造所谓 transport rate。

---

# 22. 不要通过 UI 文本抓取解决

禁止采用：

```text
屏幕 OCR
窗口文字复制
像素识别
```

作为正式 MCP 数据源。

UI 源码只用于：

```text
反推真实结构化数据绑定。
```

最终数据仍应来自：

```text
game.interface
api.engine
api.res
```

等结构化 API。

---

# 23. Cargo Registry 保持现状

当前：

```text
17 cargo types
```

已经 Live Verified。

不要重新硬编码。

修正：

```text
display_name
```

语义：

如果：

```text
getName()
```

返回的仍是内部 key，而不是本地化 UI 文本，

不要错误描述成：

```text
localized display name
```

需要继续验证 localization layer。

---

# 24. 修正 Tool Description

当前：

```text
get_game_state
```

仍写：

```text
schema-v2
```

改掉。

不要在 tool description 固定旧 schema version。

---

# 25. Diagnostics Bundle 规范化

本阶段所有 Live 验证必须保存在：

```text
diagnostics/<timestamp>/
```

至少：

```text
world-state.json
heartbeat.json

ui-source-probe.json
operations-probe.json

company-balance-ground-truth.json
ui-binding-verification.json

mcp-session.jsonl

stdout.txt
manifest.json
```

最终 ZIP 必须实际包含该目录。

acceptance 文档不得引用不存在的文件。

---

# 26. Phase 6 MCP Tool 暂时不要大量新增

找到可靠指标以后只扩展现有：

```text
get_vehicle_operating_state
get_station_operating_state
get_line_operating_summary
```

例如 Line frequency 验证后：

```json
{
  "operations": {
    "frequency_seconds": 360
  },

  "availability": {
    "frequency": true
  }
}
```

不要增加：

```text
get_line_frequency
get_frequency
query_frequency
```

之类重复 Tool。

---

# 27. Phase 6 第一验收目标

至少突破下面四项中的两项：

```text
Vehicle capacity
Line frequency
Station waiting
Industry production
```

并且必须满足：

```text
结构化数据源找到
+
Live API Probe PASS
+
同一存档 UI 对照 PASS
+
MCP E2E PASS
```

---

# 28. 最理想目标

最终达到：

```text
Company balance    UI_CROSS_VERIFIED
Vehicle capacity   UI_CROSS_VERIFIED
Line frequency     UI_CROSS_VERIFIED
Station waiting    UI_CROSS_VERIFIED
```

产业 production 如果仍未突破：

```text
允许继续 UNKNOWN
```

---

# 29. 仍然 READ ONLY

Phase 6 禁止：

```text
修改线路
买车
卖车
贷款
建站
铺轨
改变游戏速度
```

本阶段只解决：

```text
“游戏 UI 明明知道这些值，
MCP 怎样从正确的数据源获得这些值？”
```

---

# Phase 6 核心思想

不要继续盲猜：

```text
api.engine component
```

里的字段。

现在换一个方向：

```text
TPF2 原生 UI
      ↓
找到它显示数字的 Lua 代码
      ↓
追踪数据 binding
      ↓
定位 game.interface / engine source
      ↓
建立安全只读 Collector
      ↓
和 UI 同时刻交叉验证
      ↓
最后才暴露给 MCP
```

这将是下一阶段最有价值的工作。