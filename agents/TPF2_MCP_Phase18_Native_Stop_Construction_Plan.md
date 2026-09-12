# TPF2 MCP Phase 18：Native Stop Construction & Arbitrary Line Creation

## 0. Phase 18 定位

Phase 17 已完成：

-   `api.type.Line.new()`
-   `api.cmd.make.createLine()`
-   Line Entity 创建
-   Fresh Snapshot 新 Line 识别
-   `CREATE_LINE_FROM_SOURCE_ROUTE`

当前已验证：

    existing line
          |
          v
    copy native Line.stops
          |
          v
    create new line

但是该能力本质是：

    CLONE_LINE_ROUTE

不是最终目标：

    CREATE_LINE

Phase 18 的核心任务：

    station
       |
       v
    terminal
       |
       v
    native stop userdata
       |
       v
    Line.stops
       |
       v
    createLine()

最终实现：

    start station
    +
    via stations
    +
    end station
            |
            v
    new operational line

------------------------------------------------------------------------

# 1. Phase 18 目标

实现：

用户输入：

``` json
{
  "start_station_id": 100,
  "via_station_ids": [200,300],
  "end_station_id": 400
}
```

MCP 自动：

1.  解析站点；
2.  解析 terminal；
3.  构造 TPF2 原生 stop 对象；
4.  创建 Line；
5.  Fresh Snapshot 验证。

------------------------------------------------------------------------

# 2. 当前能力分类

## 已验证

### CREATE_LINE_FROM_SOURCE_ROUTE

状态：

    PRODUCT_READY

语义：

    复制已有线路路线
    创建新的 Line Entity

------------------------------------------------------------------------

## 未完成

### CREATE_LINE

状态：

    IN_PROGRESS

目标：

    start
    +
    via
    +
    end
    ↓
    native stops
    ↓
    new line

------------------------------------------------------------------------

# 3. Phase 18 主任务

## Native Stop Constructor Discovery

目标：

找到：

    station
     ↓
    terminal
     ↓
    native Stop object

创建链。

------------------------------------------------------------------------

# 4. API Discovery

## 4.1 扫描 api.type

新增 Lua probe：

``` lua
for k,v in pairs(api.type) do
    print(k,type(v))
end
```

重点关注：

    Stop
    LineStop
    Terminal
    Station
    Waypoint
    Route
    Transport

输出：

    diagnostics/api-type-inventory.json

------------------------------------------------------------------------

## 4.2 扫描 api.cmd.make

重点：

    createLine
    addStop
    removeStop
    insertStop
    updateLine
    setStops

输出：

    diagnostics/api-command-inventory.json

------------------------------------------------------------------------

# 5. Line.stops 类型分析

检查：

``` lua
line.stops
```

记录：

-   type(stop)
-   metatable
-   userdata 类型
-   stationGroup
-   terminal

目标：

找到真实 stop 类型。

------------------------------------------------------------------------

# 6. Clone Line 差分分析

利用：

    CREATE_LINE_FROM_SOURCE_ROUTE

比较：

    old line.stops

    new line.stops

目标：

分析 native stop 内部组成。

------------------------------------------------------------------------

# 7. Terminal Resolver

新增：

    LineStopResolver

负责：

    station_id
          |
          v
    stationGroup
          |
          v
    terminal

状态：

    RESOLVED

    AMBIGUOUS_TERMINAL

    STATION_NOT_FOUND

    NO_COMPATIBLE_TERMINAL

禁止：

    默认 terminal=0

------------------------------------------------------------------------

# 8. Native Stop Builder

新增：

    stop_builder.lua

接口：

``` lua
buildNativeStop(
    station_id,
    terminal_id
)
```

要求：

返回：

    userdata

而不是：

``` lua
{
 station=xxx
}
```

------------------------------------------------------------------------

# 9. 最小线路测试

不要直接测试复杂线路。

第一步：

    A → B

流程：

    resolve A

    build stop A


    resolve B

    build stop B


    Line.new()

    line.stops={
     A,
     B
    }


    createLine()

成功条件：

    new line exists

    new line stops == A,B

------------------------------------------------------------------------

# 10. Route Model

新增：

``` python
LineRoute:

    start_station_id

    via_station_ids

    end_station_id

    normalized_stops
```

例如：

输入：

    A
    via=[B,C]
    D

生成：

    [A,B,C,D]

------------------------------------------------------------------------

# 11. 业务 Route 与物理路径分离

LineRoute 表示：

    运营停站

不是：

    轨道 edge path

轨道选择交给：

    TPF2 pathfinder

------------------------------------------------------------------------

# 12. CREATE_LINE Handler 重构

删除：

    source_line_id

改为：

``` python
CreateLineRequest:

    name

    start_station_id

    via_station_ids

    end_station_id

    transport_mode
```

流程：

    Python Resolver

    ↓

    Lua Stop Builder

    ↓

    createLine

    ↓

    Fresh Snapshot

------------------------------------------------------------------------

# 13. CREATE_LINE_GOAL

输入：

``` json
{
 "start_station_id":100,
 "via_station_ids":[200,300],
 "end_station_id":400
}
```

输出：

    new_line_id

验证：

    route matches requested route

------------------------------------------------------------------------

# 14. CREATE_AND_STAFF_LINE

目标：

    CREATE_LINE

    ↓

    BUY

    ↓

    ASSIGN

保持：

    one mutation per continue

例如：

    continue #1 CREATE

    continue #2 BUY

    continue #3 ASSIGN

多辆车：

    CREATE
    BUY
    ASSIGN
    BUY
    ASSIGN

------------------------------------------------------------------------

# 15. Runtime Context

保存：

``` json
{
 "new_line_id":123,

 "vehicle_ids":[456,457],

 "assigned_vehicle_ids":[456,457]
}
```

------------------------------------------------------------------------

# 16. 测试

新增：

    tests/phase18/

包括：

    test_api_inventory.py

    test_stop_builder.py

    test_terminal_resolver.py

    test_route_model.py

    test_create_line.py

    test_create_line_goal.py

    test_create_and_staff.py

    test_clone_line_regression.py

------------------------------------------------------------------------

# 17. Evidence

目录：

    diagnostics/phase18-live/

包含：

    native-stop/

    api-type-inventory.json

    api-command-inventory.json

    stop-sample.json

    stop-construction.json


    create-line-ab/

    before.json

    command.json

    after.json

    verification.json

------------------------------------------------------------------------

# 18. Phase 18 验收标准

最低：

-   API type 扫描完成；
-   API command 扫描完成；
-   找到 native stop 类型；
-   成功构造 native userdata；
-   A-B 新线路创建成功；
-   Fresh Snapshot 获取 new_line_id；
-   route verification 成功；
-   CREATE_LINE 不依赖 source_line_id。

标准：

-   A-B-C via route 成功；
-   CREATE_AND_STAFF_LINE 完成 CREATE + BUY + ASSIGN。

优秀：

-   A-B-C-D；
-   两辆车配置；
-   调度参数控制。

------------------------------------------------------------------------

# 核心判断标准

不是：

    能不能复制线路

而是：

    用户指定已有站点

    ↓

    MCP 自动生成合法 stops

    ↓

    创建新运营线路

    ↓

    配车

    ↓

    验证运营状态

只有做到这一点：

    CREATE_LINE

才真正完成。
