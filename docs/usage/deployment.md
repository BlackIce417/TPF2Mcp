# 完整 Mod 部署与运行路径

本文与 README 使用同一套路径约定：`<mod_root>` 是实际安装的 Mod 文件夹，
例如游戏 `mods/` 下的 `tpf2mcp_1/`。本机已有安装若名为 `tpf2_mcp_1/`，更新时保留该目录名。
下表所有路径和启动命令均相对于 `<mod_root>`，不取决于终端从哪里启动。

| 相对路径 | 用途 |
| --- | --- |
| `mod.lua`、`strings.lua`、`res/` | 游戏 Mod 入口与 Lua |
| `native/tpf2_loader.dll` | Lua 加载的 Loader |
| `native/tpf2_control.dll` | Loader 加载的 Controller |
| `mcp_server/` | Python MCP、Web API 与依赖清单 |
| `start-mcp.ps1` | 使用用户选择的 Python 启动 HTTP MCP |
| `skills/tpf2-dispatch/SKILL.md` | 调度提示词 |
| `tools/`、`ui/rail-map/`、`docs/` | 配套工具、前端源码、文档 |
| `logs/dispatch/<服务启动时间>.jsonl` | 实际调度发令及关联回执，含对象、动作、原因和定位依据 |
| `logs/mcp/<服务启动时间>.jsonl` | 服务启动记录；全量工具调用日志暂时关闭 |
| `logs/mcp/<同一启动时间>.http.log` | 服务日志和异常；逐请求访问日志暂时关闭 |
| `var/mcp/` | MCP/Web 状态、数据库和运行图绑定 |
| `var/lua-control-commands/` | Lua 控制命令回执与持久去重记录 |
| `var/train-movement-commands/` | 原生移动命令回执与去重记录 |
| `var/rail-map/asset-cache/` | 从共享内存读取的静态资产 JSON 分析缓存 |
| `var/rail-map/` | 生成的铁路地图、瓦片与站场预览 |
| `var/tmp/`、`var/python-cache/` | 启动器为进程指定的临时与 Python 缓存目录 |
| `bridge/` | 原生状态、热重载及保留模块的兼容运行目录 |
| `res/scripts/tpf2_mcp/local_config.lua` | 本机权限配置，更新时保留，不随公共包发布 |

共享内存通道名称中的 `state.json`、`command-response.json` 等是通道键，
不表示每次通信都向磁盘写同名文件。静态资产的分析副本由 Python 写到表中的 asset-cache。

## 安装与启动

1. 把完整 ZIP 解压到游戏 `mods/`，形成 `<mod_root>/mod.lua`，不能额外套一层目录。
2. 用户自行准备 Python 3.11+ 及 `mcp_server/requirements.txt` 中的依赖；不需要克隆源码仓库。
3. 启用 Mod 并加载存档。在 Mod 根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-mcp.ps1
```

可用 `-Python <python可执行文件>` 指定自己的环境。启动器不安装依赖、不创建虚拟环境。
直接执行 `python mcp_server/start_http_server.py` 也会将日志和业务状态写入此 Mod 内。
MCP 地址为 `http://127.0.0.1:8766/mcp`，健康检查为 `http://127.0.0.1:8766/health`。
stdio 客户端执行 `python mcp_server/start_server.py`。
Mod 不会自动启动外部 Python 服务。

Web API 和前端按需分别启动：

```powershell
python mcp_server/start_api.py
npm --prefix ui/rail-map install
npm --prefix ui/rail-map run dev
```

Web API 为 `http://127.0.0.1:8765/api/docs`，前端为 `http://127.0.0.1:5173/?view=network`。

## 更新

退出整个游戏并停止此 Mod 的 Python 服务，再完整更新程序文件。
保留 `logs/`、`var/`、`bridge/` 和 `local_config.lua`；旧 `tpf2_mcp_state/` 的数据迁入 `var/mcp/`。
两份 DLL 被占用时停止更新，避免出现新版 Lua/Python 与旧 Loader 混用。
公共包保持只读默认值；本机已有权限配置只在本机保留。

## 路径实现与源码开发

Python 默认运行路径由 `common/paths.py` 从自身安装位置统一解析；
打包后归属此 Mod，源码调试时归属源码根目录。
`TPF2_MCP_STATE_DIR` 只能选择所属根目录内部的路径，打包服务不会被旧环境变量指向其他 Mod。
Web 状态原目录 `tpf2_mcp_state/` 已统一为 `var/mcp/`。
开发用 `.tmp-*/`、`.venv/`、`diagnostics/` 和历史 `old/` 不随 Mod 发布。
