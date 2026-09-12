# TPF2 MCP Phase 19 验收分析与 Phase 20 规划

## Phase 19 总结

Phase 19 已经完成线路运营控制的重要突破。

核心成果：

-   SET_LINE_STOPS 已经 Live Verified；
-   线路停站修改能力已经打通；
-   Phase 18 的 Native Stop Resolution 能力成功复用；
-   项目从"创建线路"进入"管理线路"阶段。

------------------------------------------------------------------------

# Phase 19 验收结果

## 1. SET_LINE_STOPS 已验证

当前能力：

    existing line
          |
          v
    new route definition
          |
          v
    native stop resolution
          |
          v
    updateLine()
          |
          v
    fresh snapshot verification

验证结果：

    POSTCONDITION_VERIFIED

------------------------------------------------------------------------

## 2. Live Evidence

验证线路：

    line_id = 1735075

修改前：

    A-B

目标：

    A-B-C

最终：

    observed_route == requested_route

验证方式：

    before snapshot

    ↓

    mutation

    ↓

    fresh snapshot

    ↓

    compare route

该方式符合 MCP mutation verification 设计。

------------------------------------------------------------------------

# 3. SET_LINE_STOPS Handler

当前流程：

    LineRouteRequest

    ↓

    LineStopResolver

    ↓

    resolve_station_stop()

    ↓

    build expected stops

    ↓

    updateLine()

    ↓

    verify route

与 Phase 18 的：

    station
     ↓
    terminal
     ↓
    native stop

链路一致。

------------------------------------------------------------------------

# 当前能力矩阵

  能力                            状态
  ------------------------------- ------------------
  CREATE_LINE_FROM_SOURCE_ROUTE   ✅ Product Ready
  CREATE_LINE                     ✅ Product Ready
  Native Stop Resolution          ✅ Verified
  CREATE_LINE_GOAL                ✅ Verified
  CREATE_AND_STAFF_LINE           ✅ Product Ready
  SET_LINE_STOPS                  ✅ Product Ready
  BUY_VEHICLE                     ✅ Product Ready
  ASSIGN_VEHICLE_TO_LINE          ✅ Product Ready
  Scheduling Control              🟡 未完成
  REMOVE_VEHICLE_FROM_LINE        🟡 未完成
  SELL_VEHICLE                    🟡 未完成

------------------------------------------------------------------------

# 当前存在的问题

## 1. README 状态需要更新

旧描述：

    read-only milestone

已经不符合当前状态。

当前已经支持：

    CREATE_LINE

    BUY

    ASSIGN

    SET_LINE_STOPS

需要更新 capability 文档。

------------------------------------------------------------------------

## 2. Evidence 需要补齐

当前：

    phase19-live/

     └─ set-line-stops/

建议补充：

    phase19-live/

     ├─ create-line/

     ├─ create-and-staff/

     └─ set-line-stops/

形成完整生命周期证据：

    创建线路

    ↓

    配置停站

    ↓

    购买车辆

    ↓

    分配车辆

------------------------------------------------------------------------

# Phase 20：AI Line Management & Optimization

## 总目标

从：

    AI 创建线路

升级为：

    AI 管理和优化线路

最终覆盖：

    新建线路

    修改线路

    车辆配置

    线路优化

    调度策略

------------------------------------------------------------------------

# Phase 20 P0：CREATE_AND_CONFIGURE_LINE_GOAL

目标：

把已有能力组合成完整业务目标。

流程：

    CREATE_LINE

    ↓

    SET_LINE_STOPS

    ↓

    BUY

    ↓

    ASSIGN

    ↓

    VERIFY

------------------------------------------------------------------------

输入：

``` json
{
  "start_station_id":100,

  "via_station_ids":[
    200,
    300
  ],

  "end_station_id":400,

  "vehicle_count":2
}
```

------------------------------------------------------------------------

输出：

    new_line_id

    configured_route

    assigned_vehicle_ids

------------------------------------------------------------------------

# Phase 20 P1：REMOVE_VEHICLE_FROM_LINE

目标：

实现车辆调度调整。

语义：

    vehicle

    ↓

    remove assignment

    ↓

    vehicle becomes available

不是：

    sell vehicle

------------------------------------------------------------------------

用途：

-   调整线路运力；
-   更换车型；
-   临时调度。

------------------------------------------------------------------------

# Phase 20 P2：SELL_VEHICLE

最后实现。

原因：

SELL 属于 destructive operation。

需要：

-   confirmation；
-   audit log；
-   状态验证。

流程：

    select vehicle

    ↓

    confirm sell

    ↓

    execute

    ↓

    fresh snapshot

    ↓

    verify removed

------------------------------------------------------------------------

# Phase 20 P3：Scheduling Control

目标：

让 AI 可以调整运营策略。

重点探索：

    minimum load

    wait policy

    frequency

    departure interval

    terminal behavior

------------------------------------------------------------------------

目标：

AI 可以：

    增加班次

    减少车辆

    调整等待策略

    优化线路效率

------------------------------------------------------------------------

# Phase 20 P4：AI 自动线路优化

最终能力：

输入：

    城市网络状态

    已有线路

    站点分布

    车辆资源

    运营数据

输出：

    推荐线路

    调整已有线路

    增加/减少车辆

    修改停站

    调整运营策略

------------------------------------------------------------------------

# 项目阶段判断

## Phase 18

解决：

    AI 创建线路

能力：

    station

    ↓

    terminal

    ↓

    native stop

    ↓

    CREATE_LINE

------------------------------------------------------------------------

## Phase 19

解决：

    AI 修改线路

能力：

    SET_LINE_STOPS

------------------------------------------------------------------------

## 当前完成度

已完成：

    创建线路       ✅

    修改停站       ✅

    买车           ✅

    配车           ✅

未完成：

    卖车           ❌

    调度策略       ❌

    自动线路规划   ❌

------------------------------------------------------------------------

# 下一阶段核心方向

Phase 20 不再重点研究底层 Line 创建。

重点进入：

    AI 运营管理层

目标：

从：

    MCP 控制 TPF2

升级为：

    AI 管理交通运营系统
