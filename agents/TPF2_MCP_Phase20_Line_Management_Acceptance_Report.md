# TPF2 MCP Phase 20 Line Management 验收分析

## 总体结论

Phase 20 当前版本已经完成了一部分线路管理能力整合，但与 Phase 19
规划中的完整目标相比，仍未完成：

-   REMOVE_VEHICLE_FROM_LINE
-   SELL_VEHICLE
-   Scheduling Control
-   AI Line Optimization

当前版本更像是：

    Phase 19 Line Operations
    +
    Capability Registry 扩展
    +
    运营管理准备

而不是完整 Phase 20。

------------------------------------------------------------------------

# 当前已确认成果

## 1. 工程结构正常

包含：

    mcp_server/

    tpf2_mod/

    diagnostics/

    docs/

    tests/

目录结构保持完整。

------------------------------------------------------------------------

# 2. 已有核心能力保持

当前已有：

  能力                     状态
  ------------------------ --------------
  RENAME_LINE              Verified
  BUY_VEHICLE              Verified
  ASSIGN_VEHICLE_TO_LINE   Verified
  CREATE_LINE              Verified
  SET_LINE_STOPS           已有基础能力

------------------------------------------------------------------------

# 3. Capability Registry

当前：

``` python
SELL_VEHICLE = True
REMOVE_VEHICLE_FROM_LINE = False
```

但是：

README 和 capability matrix 仍显示：

    SELL_VEHICLE No

    REMOVE_VEHICLE_FROM_LINE No

存在状态不同步。

需要统一：

-   registry
-   README
-   evidence
-   capability matrix

------------------------------------------------------------------------

# 当前主要问题

## 1. Phase 20 主目标尚未实现

规划目标：

    CREATE_LINE

    ↓

    SET_LINE_STOPS

    ↓

    BUY

    ↓

    ASSIGN

    ↓

    OPTIMIZE

当前主要停留在：

    CREATE_LINE

    BUY

    ASSIGN

    SET_LINE_STOPS

缺少：

    REMOVE

    SELL

    Scheduling

------------------------------------------------------------------------

# 2. REMOVE_VEHICLE_FROM_LINE

当前状态：

    未验证

需要实现：

目标：

    vehicle

    ↓

    remove from line

    ↓

    vehicle becomes available

注意：

不是：

    SELL

只是解除线路绑定。

------------------------------------------------------------------------

验收要求：

必须：

    before snapshot

    ↓

    remove operation

    ↓

    fresh snapshot

    ↓

    verify vehicle.line_id removed

------------------------------------------------------------------------

# 3. SELL_VEHICLE

当前状态：

    DISCOVERED / NOT VERIFIED

原因：

SELL 属于 destructive operation。

需要：

-   confirmation
-   audit log
-   postcondition verification

流程：

    select vehicle

    ↓

    confirm

    ↓

    sell

    ↓

    fresh snapshot

    ↓

    verify vehicle removed

------------------------------------------------------------------------

# 4. Scheduling Control 未突破

Phase 20 原计划：

    minimum load

    wait policy

    frequency

    departure interval

当前没有看到：

-   command trace
-   live evidence
-   postcondition verification

下一步需要：

    UI action

    ↓

    Lua callback

    ↓

    api.cmd.make

    ↓

    component update

    ↓

    verification

------------------------------------------------------------------------

# 建议 Phase 20 后续调整

## Phase 20.1：Vehicle Lifecycle Management

优先完成：

    REMOVE_VEHICLE_FROM_LINE

    SELL_VEHICLE

原因：

车辆生命周期是线路运营闭环的一部分。

------------------------------------------------------------------------

## Phase 20.2：CREATE_AND_CONFIGURE_LINE_GOAL

整合：

    CREATE_LINE

    ↓

    SET_LINE_STOPS

    ↓

    BUY

    ↓

    ASSIGN

形成：

    AI 创建并配置线路

------------------------------------------------------------------------

## Phase 20.3：Scheduling Control

突破：

    运营参数修改

目标：

AI 可以：

-   调整等待策略；
-   调整运力；
-   优化班次。

------------------------------------------------------------------------

## Phase 20.4：AI Line Optimization

最终目标：

输入：

    网络状态

    线路状态

    车辆资源

    运营数据

输出：

    新增线路建议

    修改线路

    增加车辆

    减少车辆

    调整策略

------------------------------------------------------------------------

# 当前项目阶段

## 已完成

    线路创建        ✅

    线路停站修改    ✅

    车辆购买        ✅

    车辆分配        ✅

## 未完成

    车辆移除        ❌

    车辆出售        ❌

    调度控制        ❌

    自动优化        ❌

------------------------------------------------------------------------

# 下一阶段核心建议

不要继续增加零散 operation。

应该围绕：

    AI Line Management

建立完整生命周期：

    Create

    Configure

    Staff

    Operate

    Optimize

    Retire

其中：

    Create
    Configure
    Staff

已经完成。

下一阶段重点：

    Operate
    Optimize
    Retire
