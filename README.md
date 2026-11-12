# TPF2 MCP

让 AI / MCP 客户端能够观察、理解并在受控条件下辅助运营
[Transport Fever 2](https://www.transportfever2.com/) 的本地 Mod 项目。

当前主线通过游戏内 Lua Mod、原生 Loader/Controller DLL 和 Python MCP Server，
向 AI 提供世界目录、完整铁路网、列车遥测以及临时限速/停车控制。
HTTP MCP 采用 Streamable HTTP，可供多个本机客户端连接同一个服务。

## 功能展示

### 全网调度总览

<p align="center">
  <img src="https://raw.githubusercontent.com/BlackIce417/TPF2Mcp/image-hosting/docs/images/system-overview.png" alt="TPF2 MCP system overview" width="100%" />
</p>

从一个页面查看全网铁路拓扑、车站、线路、AI 运行图建议、MCP 工作日志和 Bridge
实时状态。地图以游戏引擎原始轨道坐标绘制，并按缩放层级呈现全网与局部站场信息。

### 路网、站场与实时运行

<p align="center">
  <img src="https://raw.githubusercontent.com/BlackIce417/TPF2Mcp/image-hosting/docs/images/bridge-crossing-detail.png" alt="Bridge crossing detail" width="100%" />
</p>

多层线路跨越：系统依据轨道三维数据识别上下跨关系，并在俯视图中保留桥梁结构。

<p align="center">
  <img src="https://raw.githubusercontent.com/BlackIce417/TPF2Mcp/image-hosting/docs/images/station-layout-preview.png" alt="Station layout preview" width="100%" />
</p>

武汉站局部站场图：可查看站台、咽喉、道岔、站台长度和原生节点信息。

<p align="center">
  <img src="https://raw.githubusercontent.com/BlackIce417/TPF2Mcp/image-hosting/docs/images/live-train-telemetry.png" alt="Live train telemetry" width="100%" />
</p>

运行中列车在物理轨道上的实时位置、速度与状态。

<p align="center">
  <img src="https://raw.githubusercontent.com/BlackIce417/TPF2Mcp/image-hosting/docs/images/nine-hour-mcp-operations-summary.png" alt="Nine-hour MCP operations summary" width="100%" />
</p>

一次连续九小时的 MCP 运营过程：需求监控、编组约束校验、加车、停站时间调整和异常恢复。

PS. 以上UI预览图为旧功能，暂时没有与新的MCP功能同步，强行启动可能会有问题，后续会修复的。

## 能做什么

当前生产 MCP 暴露 **35 个工具**。数据和 Lua 命令回执读取 Loader 共享内存，限速与强制移动走 Controller；停站策略和官方停车、倒车命令走 Lua 执行器。
上方图片保留项目已有功能与历史实验展示，不代表其中每项能力均已迁入当前 MCP。

| 工具 | 已实现功能 |
| --- | --- |
| `get_bridge_status` | 检查 Loader、Controller 命令通道和世界目录状态 |
| `get_dispatch_rules` | 读取随 Mod 发布的 `skills/tpf2-dispatch/` 调度提示词和规则 |
| `get_train_control_snapshot` | 全部列车或指定 `display_name` 的运行数据，可选单节车辆数据 |
| `set_train_speed_limit` | 对列车前方路径窗口设置临时限速；速度为 0 时请求停车 |
| `cancel_train_speed_limit` | 根据 `command_id` 撤销本 MCP 进程创建的规则 |
| `get_active_train_controls` | 查询当前进程记录的未过期控制 |
| `get_world_catalog_status` | 世界快照时间、采集器状态及实体/路网数量 |
| `get_towns` / `get_town` | 城市列表与单个城市 |
| `get_industries` / `get_industry` | 产业列表与单个产业 |
| `get_stations` / `get_station` | 站组列表与单个站组 |
| `get_lines` / `get_line` | 线路列表与单条线路 |
| `get_rail_network` | 完整铁路网摘要和分区分页数据 |
| `get_full_network_topology` | 车站（含咽喉区）、道岔、信号机及带长度的有向拓扑边 |
| `get_train_routes` | 按 `line_id` 导出所属列车、停站顺序、主选/备选站台、装载模式、等待时间，以及各列车已采路径窗口的拓扑映射 |
| `set_line_stop_policy` | 修改指定线路一次停站的装载方式及最小/最大等待时间 |
| `add_line_stop_platform` / `remove_line_stop_platform` | 增删指定线路某次停站允许使用的站台，保留其他停站和策略 |
| `hold_train_at_station` / `release_train_from_hold` | 对已经在站内等待的列车扣停/放行；扣停10–600秒后自动解除 |
| `stop_train` / `resume_train` | 官方停车标志控制；临时停车5–120秒后自动解除 |
| `reverse_train` / `get_train_direction` | 官方倒车操作与方向状态查询 |
| `move_train_distance` / `move_train_route` | 沿当前路径或指定原生路径强制移动至目标位置，属于实验性控制 |
| `release_train_movement` / `get_train_movement` / `get_train_movement_context` | 释放强制移动、查询执行状态及当前路径上下文 |
| `get_cargo_types` | 当前游戏的货物类型ID、资源键及显示名称 |
| `get_line_demand` | 线路旅客/货物的等待量、在车量、等待时间、起讫停站和货物分类 |
| `get_station_waiting_state` | 车站各线路的候车人数、待运货物及分类，可指定 `line_id` |

实体列表支持 `offset`、`limit`、`name_contains`，单个实体使用 `entity_id`。
铁路网通过 `section` 选择 `summary`、`nodes`、`edges`、`stations`、`lines`、`depots`，
按返回的 `next_offset` 读取后续页。完整路网在这里指铁路网，不包含完整道路网络。

`get_train_routes` 的 `vehicle_ids` 可关联列车遥测；可选 `vehicle_id` 筛选同线路中的单列车。
`topology_id` 用于匹配拓扑版本，实际路径中的 `edge_id`、`node_id` 引用该拓扑。
停站顺序循环执行；站台号按子车站的终端索引加一导出，并保留原始索引。
线路配置和路径分别携带采样时间。实际轨道走向只覆盖已采窗口，未解析部分明确标记，
`full_line_track_path_available=false` 表示尚不提供全线完整轨道路径。

停站、站台和停车控制工具默认 `dry_run=true`，仅预览。实际执行需设置 `dry_run=false`，
并提供 `confirmation="<工具名大写>:<command_id>"` 和 `reason`，同时通过 Mod 的写权限开关及操作白名单。
停站配置使用 `line_id + stop_index`（从0起始）定位，装载模式为 `LOAD_IF_AVAILABLE`、`FULL_LOAD_ANY`、`FULL_LOAD_ALL`。
列车控制使用 `display_name`，名称重复时补充 `vehicle_id`。所有命令回读确认，
`ACCEPTED_UNVERIFIED` 和 `OUTCOME_UNKNOWN` 不代表效果已验证；停车标志生效也不代表列车速度已经为零。
命令回执和同一 `command_id` 的防重记录保存在 `var/lua-control-commands/`，重试不会重复下发。
Lua 请求通过 Loader 的共享内存命令槽发送，二进制头包含命令号、请求序列、长度和截止时间；
Loader 校验后在游戏更新回调中交给 Lua 执行。回执从 `command-response.json` 固定共享内存通道读取。
此通道不读写 `bridge/command.json`，也不回退到命令文件或响应文件。
需要 Loader ABI 3 和 Lua 命令协议2；旧 Loader 常驻期间须重启游戏后加载新版。发布默认写权限仍为关闭。

列车遥测包括显示名称、所属线路、长度、当前速度、技术最高速度、轨道/命令限速、
加速度、载客与货量、轨道边位置及前方路径摘要。采样目标为 5 Hz，实际频率取决于游戏更新回调。
高频列车数据由 Controller 在引擎更新回调中直接采集，经 Loader 写入原有二进制和 JSON 通道；Lua 保留低频名称和按需静态资源采集。
127列列车、2209节车体的测试存档中，原 Lua 三个高频阶段平均 CPU 耗时合计约523ms；迁移后原生采集加共享内存发布的墙钟耗时中位约31.3ms，20秒实测约4.94Hz。两项耗时使用不同计时口径，详见[原生遥测说明](docs/architecture/native-train-telemetry.md)。
未验证的数值通常返回 `null`；二进制载荷计数沿用 v1 协议，无法确认的车厢旅客数以0配合未验证标志表示，不能当作已确认无人。部分产业类型等字段仍可能为 `UNKNOWN`。
世界目录、路网和信号资产在存档加载后发布一次，后续按需刷新；采集或共享内存发布失败会退避重试。
换档会生成新的会话标识并重建目录、路网和信号批次；Python拒绝跨会话数据及失败采集器的空结果，同会话静态资产不因年龄自动失效。
线路路径与列车动态接口提供 `session_id` / `topology_id`，调用方应按同一拓扑版本关联。

客货需求按查询采集，复用最长2秒的同会话缓存，`force_refresh=true` 可强制重采。
每条线路、每类实体默认扫描上限20000，可用 `maximum_entities` 设置100–50000。
站点连接线路和需求的停站索引取自实时组件，聚合前后核对线路走向；多个线路依次采集，返回采样时间范围，非原子快照。
必须检查 `quality`：截断数量是已扫描部分，缺失返回 `null` 或错误，归属不明不会伪装为完整的0。
站内统计仅覆盖已经分配给线路、且OD起点可归属本站的实体，不代表未分配线路的完整车站库存。
旅客单位为人；货物暂为 `SIM_CARGO` 实体数，物理单位未实机核验。

旧文件 Bridge 的排图、网络分析、模拟、购买车辆与 Task/Operation
流程尚未完成迁移，已从生产 MCP 隔离。当前也不暴露旧 `tpf2://` resources。

## 原生通信与控制

Lua 在游戏内加载 `tpf2_loader.dll`，静态采集结果及 Controller 的原生动态采集结果通过 Loader 的双缓冲共享内存导出。
Loader 通过 `LoadLibrary` 加载 Controller，并监听热重载事件。
Python 使用 `ControllerCommandClient`，通过共享内存命令队列与内核事件下发控制。
源码工程名为 `tpf2_controller`，当前 Mod 包中的 DLL 名为 `tpf2_control.dll`。

`set_train_speed_limit` 参数示例：

```json
{
  "command_id": "dispatch-001",
  "display_name": "列车3",
  "speed_kmh": 30,
  "lookahead_edges": 24,
  "expires_in_seconds": 20,
  "confirmation": "APPLY_SPEED_LIMIT:dispatch-001",
  "reason": {
    "kind": "FRONT_TRAIN_TOO_CLOSE",
    "distance_threshold_m": 500
  }
}
```

速度允许 0–500 km/h，且不得超过列车技术最高速度；0 会发送停车 `hold`。
作用范围为前方 1–192 条路径边（默认 24），有效期 5–120 秒（默认 20）。
服务端检查路径窗口新鲜度和路径索引；同名列车会被拒绝。同一进程内重复的 `command_id` 会去重。

`reason` 必填，支持两类原因：

- `FRONT_TRAIN_TOO_CLOSE` + `distance_threshold_m`：记录“与前车距离过近，小于xx米，减速/停车”。
- `WAIT_ENTRY_SIGNAL` + `waiting_for_train`（列车显示名称）：记录“等待进站信号机开放，减速/停车待避列车x”。

速度为 0 时记录“停车”，大于 0 时记录“减速”。原因由调用方提供，不代表服务端已自动核实车距或信号状态。
撤销使用 `cancel_train_speed_limit`，传入 `command_id` 和 `confirmation: "CANCEL_SPEED_LIMIT:<command_id>"`，
日志原因固定为“取消限速命令”。

控制记录保存在 MCP 进程内存中，重启后不恢复；活跃控制查询不是 Controller 的全量规则查询。
Controller 到期后不再应用该规则，列车驶出指定路径范围也不再受该规则限制。

## 调度命令日志

实际发出调度命令时，写入按服务启动时间命名的 UTF-8 JSONL 文件：

```text
logs/dispatch/YYYY-MM-DD_HH-MM-SS_微秒.jsonl
```

本文所有运行路径均相对于同一个 **Mod 安装根目录**，不相对于终端当前目录。
日志记录实际发令的对象、动作、范围、原因、命令编号和回执状态。发令前记 `SUBMITTING`，随后关联结果；
结果未知不代表已执行成功。只读查询、预览、前置校验拒绝及去重重试不会新增发令记录。
原先的全量工具调用日志和 HTTP 逐请求访问日志暂时关闭；`logs/mcp/` 保留服务启动、运行和异常日志。
确认串和常见凭据字段会脱敏，完整遥测结果不会整份写入日志。运行日志不纳入发布包或 Git。
状态、命令记录和缓存统一存入 `var/`；完整目录表见[部署与运行路径](docs/usage/deployment.md)。

## 项目组成

- `tpf2_mod/`：Transport Fever 2 Lua Mod 源码。
- `mcp_server/`：按入口、MCP、业务、通信、仓库、算法和 Web 分层的 Python 服务。
- `native/tpf2_native/`：Visual Studio 解决方案及 `tpf2_loader`、`tpf2_controller` 两个 C++ 工程源码。
- `ui/rail-map/`：独立 Vite 铁路调度图前端。
- `tools/`：按 `build/`、`install/`、`web/`、`diagnostics/`、`visualization/` 分类的开发工具。
- `old/`：本机历史归档，已被 Git 忽略，不参与启动和发布。

详细目录职责、启动和构建入口见[工程目录约定](docs/architecture/project-layout.md)，文档索引见 [docs/README.md](docs/README.md)。

## 快速体验

1. 在 Windows x64 游戏中启用含 Loader/Controller DLL 的 `tpf2mcp` Mod，并进入存档。
   原生 DLL 必须与当前游戏版本匹配。
2. 完整 Mod 已包含 Python 服务、Lua、DLL、skill、前端源码、工具和文档，使用你自行准备的 Python 3.11+ 环境。
   Python 依赖清单为 `mcp_server/requirements.txt`；本项目不安装或管理你的 Python 环境。
   从 **Mod 安装根目录** 启动：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start-mcp.ps1
   ```

   启动器使用当前环境的 `python`，可用 `-Python <python可执行文件>` 指定解释器。
   也可直接执行 `python mcp_server/start_http_server.py`。
   客户端选择 **Streamable HTTP**，填写 `http://127.0.0.1:8766/mcp`。
   健康检查为 `http://127.0.0.1:8766/health`；游戏连接状态使用 `get_bridge_status` 核验。
   可用 `--port` 或 `TPF2_MCP_HTTP_PORT` 修改端口。接口变更后客户端应重新连接刷新工具定义。
   可选设置 `TPF2_MCP_HTTP_TOKEN`，客户端携带 `Authorization: Bearer <token>`。
   默认仅监听本机；云端客户端无法直接访问本机 `127.0.0.1`。

   stdio 入口 `mcp_server/start_server.py` 仍保留，由客户端作为子进程启动。
   多客户端共享控制状态使用同一个 HTTP 服务。

3. 铁路图属于独立组件，部分数据访问仍待迁移到新链路。
   需要启动 Web API 时，在同一个 Mod 根目录执行：

   ```powershell
   python mcp_server/start_api.py
   ```

4. 另开终端启动前端：

   ```powershell
   npm --prefix ui/rail-map install
   npm --prefix ui/rail-map run dev
   ```

5. 浏览器打开 `http://127.0.0.1:5173/?view=network`。

Mod 不会自动启动外部进程；MCP Server、FastAPI API 和前端需要单独启动。
当前 MCP 限速使用命令编号、原因与显式确认串，不走隔离中的旧 Task 审批流程。

## 构建完整 Mod

使用 Visual Studio C++ 工具链构建 `native/tpf2_native/tpf2_native.slnx`。
从源码根目录构建完整发布包：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build\build-workshop-package.ps1
```

脚本生成一个完整的 `tpf2mcp_1/` Mod 目录及同级 `tpf2mcp_1-release.zip`。
ZIP 第一层就是 Mod 文件夹，解压到游戏的 `mods/` 下即可。已有安装保留原目录名，以保持存档的 Mod 标识。
完整包默认关闭写权限，不包含用户 Python 环境、node_modules、运行日志、缓存、本地权限配置或测试资料。
`build-native-mod.ps1` 仅用于原生开发测试，不作为用户安装包。


## 当前状态

当前共享内存世界目录、铁路网、列车遥测和原生限速已在真实存档中验证。
上方文档目录中仍包含旧文件 Bridge、历史运营实验与尚未迁移的设计，当前生产能力以本文工具清单为准。
源码、测试及两个 C++ 工程纳入 Git；DLL、构建产物和运行数据暂不纳入。

本项目暂时处于未完工状态。
