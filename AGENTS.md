# Transport Fever 2 MCP

## 本机游戏路径

Transport Fever 2 的 Steam 安装目录：

```text
D:\Steam\steamapps\common\Transport Fever 2
```

TPF2 用户模组目录与 Bridge 目录仍须由实际游戏运行验证，不得把推测路径视为已确认能力。

## Agent 启动与重启游戏

- Agent 可以直接启动 Transport Fever 2，不需要管理员权限。优先通过 Steam 启动，以保留 Steam 环境、启动参数、Mod 配置和云存档行为；App ID 为 `1066780`。
- 启动前先用 `Get-CimInstance Win32_Process -Filter "Name='TransportFever2.exe'"` 检查游戏是否已经运行。已有进程时不得重复启动。
- Steam 路径应优先从当前用户注册表动态发现，不得把本机 `D:\Steam` 写进面向其他用户的程序。Agent 在本机启动游戏可使用：

```powershell
$steamPath = (Get-ItemProperty -LiteralPath 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath
$steamExe = Join-Path $steamPath 'steam.exe'
if (-not (Test-Path -LiteralPath $steamExe -PathType Leaf)) {
    throw "Steam executable not found: $steamExe"
}
Start-Process -FilePath $steamExe -ArgumentList '-applaunch', '1066780'
```

- 这是用户需要操作的可见交互式程序，启动时不要使用 `-WindowStyle Hidden`。Steam 不可用时才直接运行已验证安装目录下的 `TransportFever2.exe`，并将工作目录设为游戏目录：

```powershell
$gameRoot = (Resolve-Path -LiteralPath 'D:\Steam\steamapps\common\Transport Fever 2').Path
Start-Process -FilePath (Join-Path $gameRoot 'TransportFever2.exe') -WorkingDirectory $gameRoot
```

- 启动命令只负责启动游戏，不等于授权启用写操作、原生注入或控制系统。控制系统继续保持 `DISABLED`；只有任务已有明确写入授权且健康检查通过时，才可单独切换到 `ARMED`。
- 启动后应等待并核验 `TransportFever2.exe` 的实际路径、版本哈希、最新 `stdout.txt`、活动 Mod 根目录和 Bridge 心跳，不能仅凭 `Start-Process` 成功返回判断游戏可用。
- 游戏发生新的异常退出时，不得立即循环重启。先保存并检查对应 `crash_dump`、崩溃存档时间和最后一个控制动作，说明原因并将控制恢复为 `DISABLED`。正常日志包含 `Quit requested`、成功保存、`Goodbye` 和 `Shutdown` 时，应归类为正常退出，不得误报为崩溃。
- 已加载原生 Hook 的游戏进程不得热加载第二份控制 DLL。更新版使用 `tpf2_control.next.dll` 暂存；确认游戏进程完全退出后，由 Native Supervisor 原子替换正式 DLL，再启动游戏。

## 路径归属与安装约束

- 路径约束按文件归属划分，不按盘符一刀切：源码开发产生的所有项目文件必须放在项目目录内；作为 Mod 打包或测试时，Mod 运行所需的所有代码、资源、工具和运行数据必须放在该 Mod 的根目录内。不得散落到用户主目录、`AppData`、`Documents`、系统临时目录或其他无关位置。
- 本机当前已知基础路径如下。它们用于本机操作和核验，不得硬编码进面向其他用户发布的程序：

```text
项目目录：D:\tpf2mcp
游戏目录：D:\Steam\steamapps\common\Transport Fever 2
手动 Mod 根目录：D:\Steam\steamapps\common\Transport Fever 2\mods\<mod_folder>
Workshop 暂存 Mod 根目录：D:\Steam\userdata\<steam_user_id>\1066780\local\staging_area\<mod_folder>
Workshop 订阅 Mod 根目录：D:\Steam\steamapps\workshop\content\1066780\<workshop_item_id>
```

- 源码开发阶段，虚拟环境、缓存、诊断、临时构建和发布压缩包分别放在项目目录下的 `.venv/`、`.tmp-*/`、`diagnostics/` 和项目根目录，不得另选一个方便但无归属的目录。
- Mod 打包或发布测试阶段，以实际待测试的 `<active_mod_root>` 为唯一运行根目录。Lua Mod、`mcp_server/`、`tools/`、`ui/`、图片和其他发布资源必须完整位于该目录下；Bridge 请求、响应与状态文件必须位于 `<active_mod_root>\bridge`。
- 发布测试不得让暂存 Mod 引用项目目录里的源码，也不得把 Bridge 或 UI 单独运行数据放回项目目录。这样测试到的是完整、自包含的发布包，而不是开发环境拼接出来的结果。
- `<steam_user_id>`、`<workshop_item_id>` 和实际启用的 `<mod_folder>` 必须动态发现或通过游戏运行验证，不能在代码、文档模板或发布包中写死本机账号 ID。
- 源码工具应优先从当前文件位置、仓库根目录、Steam 配置和已验证的 Mod 位置推导路径。其他用户的安装盘符和 Steam 库可能不同，必须从其实际 Steam/Mod 安装位置动态发现。
- 不得使用 `pip install --user`，也不得无目标地调用全局 `pip install`。源码开发所需环境放在项目目录的 `.venv/`；若发布版以后出现必须随 Mod 提供的 Python 依赖，应将其打包到 Mod 根目录内并让启动器从该位置加载，不得安装到用户级 Python 目录。
- 执行任何写操作前必须解析并核对最终绝对路径：开发操作只能写入项目目录，Mod 构建和发布测试只能写入明确的 Mod 根目录。若工具无法保证目标归属，应停止并向用户说明。
- 允许只读检查游戏或系统在其他位置生成的日志和配置，但不得借此在那里创建、修改或迁移本项目文件。

## 开发约定

- 按阶段开发，先完成并验证 Bridge MRE，再扩展 MCP 功能。
- MCP Server 与 TPF2 模组必须通过 Bridge Protocol 通信；MCP Tool 不直接操作 Bridge 文件。
- 第一版以只读能力为主；写操作默认禁止，后续须遵循权限等级与 dry-run 约定。
- 对尚未验证的 TPF2 Lua API 能力标记为 `UNKNOWN`，以最小实验和实际日志确认。

## Web 前后端与开发启动

- Web 前后端必须保持分离。后端是 FastAPI，只提供 `/api/*` JSON、OpenAPI 和 SSE，禁止在 Python 中拼接 HTML/JavaScript，也禁止用 FastAPI `StaticFiles` 挂载前端。
- 前端位于 `ui/rail-map/`，当前技术栈是原生 HTML、CSS、JavaScript ES Modules 与 Vite；没有使用 Vue。源码统一位于 `ui/rail-map/src/`，按 `pages/`、`shared/`、`styles/`、`templates/` 拆分；固定结构使用 HTML `<template>`，禁止内联 `<style>`、内联脚本、`style` 属性和 `onclick` 等内联事件。
- HTML 或 HTML 模板负责固定界面结构，CSS 负责样式，JavaScript 只负责 API 请求、向已有 DOM 填充数据、显隐、事件和页面状态；禁止用大量 `createElement()`、`appendElement()` 或字符串拼接动态搭建整个页面。只有数量不确定的线路、车辆、日志、车站等列表项和图形元素可以动态创建。
- 每个独立功能区域和单值字段必须使用明确、可全局搜索的业务 `id`；`class` 只用于样式复用，禁止依赖复杂 DOM 层级定位固定字段。Sidebar 统一使用 `app-sidebar` 以及方位类 `app-sidebar-r` / `app-sidebar-l`，再叠加业务 class；公共样式放在 `styles/sidebar.css`，业务差异保留在页面样式中。
- 前端数据流固定为 `FastAPI /api/* -> pages/*/api 或 shared/http.js -> JSON -> 页面/组件 JS -> 既有 HTML DOM`。新增或重构页面时优先降低动态 DOM 拼装和代码分散程度，使页面字段可以通过 DOM `id` 或 API 字段名直接定位。
- 后端生成的路网 JSON、瓦片和车站预览统一放在项目或 Mod 根目录的 `var/rail-map/`，不得再写入 `ui/rail-map/`。浏览器只能通过 FastAPI `/api/*` 获取这些数据。
- 调度区总览复用全局路网生成阶段的简化物理底图；轨道归属在 `dispatch_regions.py` 编译时合并为按区域着色的概览矢量链。放大后必须复用 `/api/rail/tile/*` 原始路网瓦片和 `ui/rail-map/src/shared/pixi-viewport.js`，按生成数据中的 edge 区间归属着色；不得从完整轨道曲线生成常驻覆盖层。拖动使用 `requestAnimationFrame` 合帧，不得在交互帧重建轨道几何。
- Python 数据导出器只能生成 JSON，不得生成 `window.X = {...}` 形式的 JavaScript 数据包装器。详细规范见 `docs/frontend-architecture.md`。
- 首次开发先创建仓库内 Conda 环境并安装前端依赖：

```powershell
conda env create --prefix .\.venv --file .\environment.yml
npm --prefix .\ui\rail-map install
```

- 日常开发推荐从仓库根目录一键启动 API 与前端；该脚本只管理自己创建的两个子进程：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\start-web.ps1
```

- 默认访问 `http://127.0.0.1:5173/?view=network`，FastAPI 文档位于 `http://127.0.0.1:8765/api/docs`。若端口已被旧进程占用，启动脚本必须报出 PID，不得擅自终止用户已有进程。
- 需要分别调试时，使用两个终端运行：

```powershell
conda run -p .\.venv python .\mcp_server\start_api.py
npm --prefix .\ui\rail-map run dev
```

## 仓库与发布包的边界

- GitHub 仓库是源码仓库，不得为了匹配创意工坊目录而把仓库整体改造成 `tpf2mcp_1`。
- 保持职责分离：`tpf2_mod/` 存放 Lua Mod 源码与发布图片，`mcp_server/` 存放 Python 服务，`ui/` 存放前端源码，`tools/` 存放开发和构建工具，`protocol/`、`tests/`、`docs/` 分别存放协议、测试和文档。
- 创意工坊目录 `tpf2mcp_1/` 是从源码组装出的发布产物，只能由 `tools/build-workshop-package.ps1` 生成；不要把暂存目录中的文件反向复制回源码目录。
- `tpf2_mod/image_00.tga` 和 `tpf2_mod/workshop_preview.jpg` 是发布资源，应纳入 Git。前者必须是 320×180、24 位、未压缩 TGA；后者必须为正方形且小于 1 MiB。
- `mcp_server/requirements.txt`、`start_server.py`、`start_api.py`、兼容入口 `start_ui.py` 以及发布构建脚本属于源码，应纳入 Git。

## 禁止提交或打包的内容

- 不得提交或发布运行时 Bridge 数据、存档导出数据、诊断资料、日志、数据库、缓存、临时文件或本机配置。
- 至少排除：`bridge/`、`tpf2_mcp_state/`、`var/`、`local_config.lua`、`diagnostics/`、`.tmp-*/`、`__pycache__/`、`*.pyc`、`*.log`、`*.sqlite`、`*.sqlite3`、`*.tmp`、生成的铁路 JSON/JS/瓦片和截图。
- `tpf2mcp_1-release.zip`、Steam `staging_area` 以及游戏安装目录中的 Mod 副本均为构建或安装产物，不进入 Git。
- 发布包采用白名单组装。新增运行所需文件时，应修改构建脚本的白名单并补充验证，不能改为复制整个源码目录。
- 本机绝对路径、Steam 用户 ID、隐私数据和密钥不得写入发布包；Mod、Bridge 和 UI 应通过安装位置或明确配置动态发现路径。

## 创意工坊打包规范

- 默认发布文件夹名为 `tpf2mcp_1`，展示名为 `tpf2mcp`，作者为 `BlackIce`；除非用户明确要求，不擅自修改名称、作者或补写其他元数据。
- 使用以下脚本生成 Steam 暂存目录，优先让脚本自动发现 `staging_area`；发现失败时再显式传入路径：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build-workshop-package.ps1
```

- 构建目标已存在时，脚本应停止而不是覆盖。重新构建前必须先确认目标确为本项目生成的 `tpf2mcp_1` 暂存目录，再以可恢复方式备份或清理；不得递归删除未核实的 Steam 目录。
- 发布包根目录应直接包含 `mod.lua`、`strings.lua`、`image_00.tga`、`workshop_preview.jpg` 和 `res/`，并包含运行所需的 `mcp_server/`、精选 `tools/` 与 `ui/rail-map/`；不得额外嵌套一层同名目录。
- 发布配置必须保持 `allow_write_operations = false`。任何写操作版本都需要单独的权限设计、dry-run、测试和用户明确授权。
- Transport Fever 2 加载 Lua Mod 不等于可以自动启动外部 Python 进程。发布说明不得宣称 Bridge 会随 Mod 自动启动，必须保留实际启动方式：

```text
进入本 Mod 的 mcp_server 目录
python -m pip install -r requirements.txt
python start_server.py

查看前端时分别执行：
python start_api.py
进入 ui/rail-map 后执行 npm install 和 npm run dev
浏览器打开 http://127.0.0.1:5173/?view=network
```

- 上述命令是面向最终用户的通用说明，不得写死本机盘符。对源码进行开发验证时使用项目目录内 `.venv` 的 Python；对 Mod 发布包进行测试时，工作目录和被执行脚本必须位于实际待测 Mod 根目录内。当前 `requirements.txt` 没有第三方运行时依赖，不应为了形式执行用户级或全局安装。

## 发布前验证

- 先运行自动化测试，并确认所有测试通过。
- 运行打包脚本，确认图片规格、必需文件、只读默认值以及禁止文件检查全部通过。
- 从最终暂存目录或最终 ZIP 重新检查目录层级；ZIP 的第一层必须是 `tpf2mcp_1/`，其下才是 Mod 文件。
- 在游戏中加载暂存版本并重新进入存档，以实际日志确认 Lua Mod 已运行；不得仅凭目录存在判定加载成功。
- 从发布包内的 `mcp_server` 启动 Bridge，验证 ping 和游戏状态读取；再分别启动 FastAPI 与 Vite，验证 `http://127.0.0.1:5173/?view=network` 可访问且能读取当前数据。
- 首次上传或试投默认使用隐藏／仅自己可见状态。公开发布、更新既有创意工坊条目或改变可见性前，必须得到用户明确确认。
- 验证通过后再制作 release ZIP；ZIP、暂存区和本地安装副本仍不得提交到 GitHub。
