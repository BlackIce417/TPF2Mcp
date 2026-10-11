# TPF2 MCP 技术参考

本文面向开发、测试和发布维护者。面向普通使用者的项目介绍与启动入口见仓库根目录
[README](../README.md)。

## 架构

```text
MCP client <-> Python stdio MCP server <-> Bridge Protocol <-> TPF2 Lua Mod <-> TPF2 API
```

MCP Tool 不直接访问 Bridge 文件；`BridgeClient` 是 Python 侧唯一的 Bridge 边界。
Lua Mod 通过游戏脚本的 `load` 与周期性 `update` 回调采集并响应协议请求。

源码职责如下：

- `tpf2_mod/`：Lua Mod 与发布图片。
- `mcp_server/`：Python MCP Server、受控操作和数据处理。
- `ui/rail-map/`：独立 Vite 铁路图前端。
- `tools/`：开发、安装、验证、导出和打包脚本。
- `protocol/`、`tests/`、`docs/`：协议、测试与文档。

## 开发环境

开发依赖必须位于仓库根目录的 `.venv/`，不要使用 `pip install --user` 或未激活环境
下的全局安装。项目使用 FastAPI/Uvicorn 提供本机 Web 查询服务，运行状态和命令审计
使用 SQLite。

```powershell
conda env create --prefix .\.venv --file .\environment.yml
conda activate .\.venv
$env:PYTHONPATH = (Resolve-Path .\mcp_server\src).Path
python -m unittest discover -s tests -v
```

若 `.venv` 已存在，先确认它是否属于本项目并以可恢复方式备份，再创建 Conda 环境；
不要直接覆盖其他开发环境。

## 本机 Web 服务

`mcp_server/start_api.py` 启动 Uvicorn 承载的 API-only FastAPI 应用。FastAPI 路由位于
`mcp_server/src/tpf2_mcp/web_app.py`，状态聚合位于 `web_state.py`，SQLite Web 审计
位于 `web_store.py`。后端不挂载或返回前端文件，只在 `127.0.0.1:8765` 提供 JSON API
和 SSE；独立 Vite 前端默认监听 `127.0.0.1:5173` 并代理 `/api`。

写接口的请求和结果追加到活动 Mod 的 `bridge/dispatch/web.sqlite3`。实时位置、完整
路网和游戏快照继续使用带存档、会话和拓扑版本的原子 JSON 文件；HTTP 读取不会把
高频快照重复写入数据库，也不会隐式触发游戏写操作。

本机开发安装使用 `tools/install-mod.ps1`。该脚本用于已确认的游戏 Mod 根目录测试，
不是 Workshop 发布构建方式。运行真实游戏前，需要在游戏内启用 Mod 并重新进入存档，
再验证 Bridge ping 和游戏状态读取。

## 运行与安全模型

发布配置 `allow_write_operations = false`。MCP 的直接 `execute_operation` 不会向 Agent
暴露，且直接调用会被拒绝。

MCP Agent 的线路/车辆受控 Task 写入遵循：

```text
get_operation_capabilities
-> propose_operation
-> validate_operation
-> create_task
-> plan_task
-> approve_task_step
-> continue_task
-> get_task
```

HTTP 工程控制平台与原生租约是另一条已有执行路径，并非所有写入都经过上述 MCP Task 链。原生能力需要控制模式和原生后端门禁；Lua 写开关不能独立代表原生总停用。具体动作语义、当前缺口与区域影子边界见 [当前能力](CURRENT_CAPABILITIES.md)。

每次 `continue_task` 最多执行一个变更，并刷新游戏快照验证后置条件。受控能力与
Agent 工具入口见 [agent-mcp-tools.md](agent-mcp-tools.md)。

已验证的受控操作包括创建线路、设置停站、购买并分配车辆、设置停站策略和确认后
出售车辆。`REMOVE_VEHICLE_FROM_LINE` 仍不可用；未被引擎实际验证的能力应明确标记
为 `UNKNOWN`。

## 发布与 Workshop 测试

创意工坊发布文件夹由源码白名单组装，默认目录名为 `tpf2mcp_1`：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build-workshop-package.ps1
```

构建目标已存在时，脚本会停止而不是覆盖。发布前应完成自动化测试、构建脚本校验、
最终暂存目录层级检查，并从最终 Mod 根目录分别启动 MCP Server、API 与前端验证。

发布包根目录直接包含 Mod 文件、`mcp_server/`、精选 `tools/` 和 `ui/rail-map/`。
Bridge 数据、SQLite、日志、诊断、缓存、存档导出和本机配置均不得进入 Git 或发布包。
发布包不会自动启动 Python；最终用户应在 Mod 根目录的 `mcp_server/` 中执行：

```powershell
python -m pip install -r requirements.txt
python start_server.py
python start_api.py
```

另开终端进入 `ui/rail-map`，执行 `npm install` 和 `npm run dev`，然后打开
`http://127.0.0.1:5173/?view=network`。前端约束见 [frontend-architecture.md](frontend-architecture.md)。

## 延伸文档

- [架构说明](architecture.md)
- [Bridge 协议](bridge.md)
- [最终验收与能力边界](FINAL_GOAL_ACCEPTANCE.md)
- [网络智能分析](PHASE9_NETWORK_INTELLIGENCE.md)
- [决策支持](PHASE10_DECISION_SUPPORT.md)
- [受控操作](PHASE11_CONTROLLED_OPERATIONS.md)
- [任务编排](PHASE12_CLOSED_LOOP_TASKS.md)
- [线路管理](PHASE14_LINE_MANAGEMENT.md)
- [Agent MCP 工具](agent-mcp-tools.md)
