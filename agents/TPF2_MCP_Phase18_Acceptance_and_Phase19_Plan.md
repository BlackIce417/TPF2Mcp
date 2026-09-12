# TPF2 MCP Phase 18 验收分析与 Phase 19 规划

## Phase 18 总结

Phase 18 已经超过原计划目标，核心问题已经解决。

之前的关键瓶颈：

    station
     ↓
    terminal
     ↓
    native stop userdata
     ↓
    Line.stops
     ↓
    createLine

已经打通。

------------------------------------------------------------------------

# 当前 Phase 18 实际成果

## 1. Native Stop 构造问题解决

之前方案：

    自行构造 Stop userdata

存在问题：

-   userdata 类型不匹配；
-   engine 拒绝 Line.stops；
-   Lua/Python bridge 不可靠。

最终采用：

    已有 native LINE.stops
            |
            v
    复制合法 stop descriptor
            |
            v
    修改临时 Line
            |
            v
    createLine()

优势：

-   使用游戏认可的 native 对象；
-   避免自行伪造 userdata；
-   与 TPF2 engine 兼容。

------------------------------------------------------------------------

# 2. CREATE_LINE 业务语义完成转换

之前：

    source_line_id
          |
          v
    clone existing line

实际属于：

    CREATE_LINE_FROM_SOURCE_ROUTE

现在：

    start_station_id

    via_station_ids

    end_station_id

            |

            v

    native stops

            |

            v

    new Line

已经符合：

    AI 新建线路

定义。

------------------------------------------------------------------------

# 3. Live 验证结果

## A-B

状态：

    POSTCONDITION_VERIFIED

结果：

    line_id = 1790269

------------------------------------------------------------------------

## A-B-C

状态：

    POSTCONDITION_VERIFIED

支持：

    explicit terminals

并正确处理：

    AMBIGUOUS_TERMINAL

------------------------------------------------------------------------

## CREATE_AND_STAFF_LINE

完整流程：

    CREATE_LINE

    ↓

    BUY

    ↓

    ASSIGN

验证成功。

结果：

    line_id = 1695630

    vehicles:

    1733153
    621964

状态：

    POSTCONDITION_VERIFIED

------------------------------------------------------------------------

# 当前能力矩阵

  能力                            状态
  ------------------------------- ------------------
  CREATE_LINE_FROM_SOURCE_ROUTE   ✅ Verified
  Native Stop Construction        ✅ Verified
  Station → Terminal Resolver     ✅ Verified
  CREATE_LINE A-B                 ✅ Product Ready
  CREATE_LINE A-B-C               ✅ Product Ready
  CREATE_AND_STAFF_LINE           ✅ Product Ready
  SET_LINE_STOPS                  🟡 下一阶段
  Scheduling Control              🟡 下一阶段

------------------------------------------------------------------------

# 代码评价

## stop_builder.lua

当前方案：

    build_stop()

通过：

    寻找已有 Line.stops

    ↓

    返回合法 native stop

避免：

-   userdata 序列化；
-   自造错误对象；
-   bridge 类型转换问题。

方向正确。

------------------------------------------------------------------------

## LineStopResolver

设计正确：

原则：

    不猜 terminal

如果：

    station
     |
     + terminal A
     |
     + terminal B

没有可靠规则：

返回：

    AMBIGUOUS_TERMINAL

而不是：

    terminal = 0

------------------------------------------------------------------------

# 当前限制

## 1. Native Stop Builder 依赖已有线路样本

当前：

    station
     |
    terminal
     |
    查找已有 native stop

如果：

    某 station 存在

    但是没有任何 line 使用

可能：

    NO_OBSERVED_NATIVE_STOP

失败。

后续增强：

寻找：

    Terminal → Stop descriptor factory

或者：

    LineStop constructor

------------------------------------------------------------------------

# Phase 19 建议

名称：

# Phase 19：AI Line Operations

目标：

从：

    AI 创建线路

进入：

    AI 管理线路

------------------------------------------------------------------------

# P0：Phase 18 产品化整理

任务：

-   更新 capability registry；
-   更新 README；
-   补充 evidence manifest；
-   标记 Product Ready；
-   清理旧 CREATE_LINE placeholder。

------------------------------------------------------------------------

# P1：SET_LINE_STOPS

目标：

修改已有线路停站。

流程：

    existing line

    ↓

    new route

    ↓

    build native stops

    ↓

    replace Line.stops

    ↓

    updateLine()

    ↓

    verification

复用：

    native stop builder

------------------------------------------------------------------------

# P2：CREATE_AND_CONFIGURE_LINE_GOAL

一次完成：

    CREATE_LINE

    ↓

    BUY

    ↓

    ASSIGN

    ↓

    SET_LINE_STOPS

形成完整运营配置。

------------------------------------------------------------------------

# P3：运营策略控制

探索：

    minimum load

    wait policy

    frequency related controls

    terminal behavior

目标：

让 AI 不仅创建线路，还能调整运营。

------------------------------------------------------------------------

# P4：AI 自动规划线路

输入：

    城市需求

    已有站点

    覆盖目标

    车辆预算

输出：

    推荐线路

    创建线路

    车辆配置

    运营策略

------------------------------------------------------------------------

# 当前项目阶段判断

项目已经从：

    MCP 控制 TPF2

进入：

    AI 运营管理层

阶段。

Phase 18 完成后，核心闭环：

    已有站点

    ↓

    解析 terminal

    ↓

    构造 native stops

    ↓

    CREATE_LINE

    ↓

    BUY

    ↓

    ASSIGN

    ↓

    验证

已经成立。

下一阶段重点：

从：

    能不能创建线路

转向：

    如何自动运营和优化线路
