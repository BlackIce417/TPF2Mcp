# 调度系统阶段成果与后续任务

整理日期：2026-10-12。

项目已具备动态观测、独立间距算法和调度动作接口，可以继续开发本地控制算法。当前版本仍是开发阶段：信号区间控制、客货批量改派和联合进站调度均未完成游戏内闭环验收。

## 三项目标进度

| 目标 | 已有实现 | 下一阶段缺口 |
|---|---|---|
| 列车间距与区间限速 | 有向曲线路径投影、整列首尾估算、同向前车匹配、制动速度包络、跨周期控制和租约接口 | 有向信号区间、整列占用、到防护信号机的沿轨距离、制动与延迟标定 |
| 客货流分配 | 容量分配原型、OD 规则、客货实体类型区分、乘客改派历史实验 | 按货物类型过滤、具体车次共享容量、现有队列迁移、逐对象回执和数量守恒 |
| 进站调度 | 站台选择接口、路径成本干预、到站站台及锁定状态观测 | 合法进路候选、站台与咽喉联合预约、锁定时机、吞吐量效果验证 |

## 模块入口

- [列车间距模块](../mcp_server/src/tpf2_mcp/algorithms/train_spacing/README.md)：独立计算引擎、逐周期控制器、离线 JSON 入口和原生接口适配。宿主负责不断取得新帧并调用控制器；模块不自行轮询数据库。
- [信号观测](../mcp_server/src/tpf2_mcp/signal_observations.py)：逐信号索引绑定、方向凭据、会话和新鲜度校验。Lua 采集原始动画状态，公共灯色仍输出 UNKNOWN；不能据此宣称信号区间控制已完成。
- [控制系统](../mcp_server/src/tpf2_mcp/control_system.py)与[原生监督器](../mcp_server/src/tpf2_mcp/native_supervisor.py)：动作编译、限时租约、健康检查及原生控制生命周期。
- [原生控制源码](../native/tpf2_control/tpf2_control.c)：速度、站台、路径成本与 OD 分配接口；构建脚本位于同目录，编译产物不入库。
- [区域调度运行时](../mcp_server/src/tpf2_mcp/dispatch_runtime/)与[协议](../protocol/dispatch/)：观测帧、命令、结果和区域协调基础。
- [Web 架构](frontend-architecture.md)：FastAPI 提供 JSON API，Vite 前端提供路网、站场、运行图与调度区页面；生成数据保存在运行目录。
- [算法理论](DISPATCH_ALGORITHM_THEORY.md)、[实施清单](../agents/INTELLIGENT_DISPATCH_ALGORITHM_TODO.md)与[能力边界](CURRENT_CAPABILITIES.md)：后续开发依据及历史实验的适用范围。

## 间距控制的实现边界

当前算法按前车尾与后车头的净间距计算制动包络，尚未按信号区间占用决定防护目标。首尾位置由车体部件和包围盒沿曲线投影估计，并非游戏直接提供的精确车钩坐标。

原生速度规则已包含 path_index_start 和 path_index_end，可约束路径索引范围；完整的路径代次、方向和边内精确范围仍需贯通，不能把索引范围等同于完整 occurrence 身份。

下一阶段先接入信号状态与方向，再构建有向区间、计算整列占用及到防护信号机的沿轨距离，最后标定制动和采样延迟，并验证限速命中与释放行为。

## 本次验证

- 项目 Python 环境执行 unittest：383 项，382 项通过、1 项跳过。
- Vite 生产构建通过。
- MinGW 构建原生 DLL 和注入器通过；未部署到游戏进程。
- 浏览器集成脚本因本地 CDP 服务未启动而无法执行用例，其特定存档与配套服务验收不计为通过。
- 未启动游戏、注入 DLL 或进行新的实机闭环验证。早期文档中的实测记录保留原日期，不代表本次验收。

Python 测试可在仓库根目录执行：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'mcp_server/src'
$env:TEMP = Join-Path (Get-Location) '.tmp-tests'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
.\.venv\python.exe -m unittest discover -s tests -p 'test_*.py'
npm --prefix ui/rail-map run build
.\native\tpf2_control\build.ps1
```

原生构建需要 MinGW-w64 gcc。测试依赖见 tests/requirements-web.txt 和 tests/requirements-regional.txt。

## 仓库边界

GitHub 保存项目源码、测试、通用协议和公开开发文档。逆向专项笔记、IDA 数据库、反编译结果、分析脚本及证据清单仅保留本地；运行日志、存档导出、Bridge 数据、数据库、本机配置和编译产物也不提交。
