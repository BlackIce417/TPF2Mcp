# 工程目录与维护约定

## Python

`mcp_server/start_server.py`、`start_http_server.py`、`start_api.py` 保留为外部启动入口。
包内部不再通过旧的扁平模块路径导入；调用者使用以下分类路径。

| 目录 | 职责 |
| --- | --- |
| `entrypoints/` | HTTP、stdio、CLI 传输与启动 |
| `mcp/` | JSON-RPC 分发、工具描述、输入结构及业务绑定 |
| `services/` | 列车、停站、移动、需求和线路业务；包含仍被 Web 使用的 operations/tasks |
| `transport/` | Loader/Controller IPC、遥测协议解析与通信适配 |
| `repositories/` | 世界目录、资产快照、存档范围与缓存 |
| `algorithms/` | 拓扑、占用、间距、区域和分析算法 |
| `web/` | FastAPI 页面数据接口及 Web 状态 |
| `common/` | 配置、审计、日志、公共命令契约 |

世界数据读取在 `repositories/world.py`；MCP 工具定义在 `mcp/world_mcp.py`。
移动和需求业务在 `services/movement.py`、`services/demand.py`，对应 MCP 模块只负责接口绑定。
`mcp/legacy_adapter.py` 仅为显式 MockBridge 调用保留历史契约，生产入口不会加载旧 Planning/Task 工具。
仍被 Web/CLI 引用的实现不能仅因未在 MCP 暴露就归档。

## 调度 Skill

提示词入口为项目或完整 Mod 根目录下的 `skills/tpf2-dispatch/SKILL.md`。
`get_dispatch_rules` 无参数，只读返回该文件和 `references/` 下的 Markdown 文件内容；
返回路径统一相对于项目或 Mod 根目录，不依赖启动时的工作目录。
接口定义在 `mcp/rules_mcp.py`，文件读取在 `repositories/dispatch_rules.py`。
每次调用重新读取，修改规则无需重启服务；文件缺失时返回 `DISPATCH_RULES_UNAVAILABLE`。

## Lua

游戏要求的入口仍在 `tpf2_mod/res/config/game_script/`，Lua 模块位于
`tpf2_mod/res/scripts/tpf2_mcp/`：

```text
runtime/        main.lua、hot_reload.lua、state.lua
collectors/     世界资产、需求、信号和静态列车元数据
  probes/       仍被运行入口引用的诊断探针
operations/     游戏命令、停站策略、倒车和看门狗
transport/      native_loader.lua
codecs/         json.lua、binary.lua
config/         settings.lua
```

本机写权限覆盖文件仍是 `res/scripts/tpf2_mcp/local_config.lua`，不纳入发布包。
目录移动同时更新 require、热重载白名单和配置路径识别。旧 bootstrap 与新模块路径不兼容，
因此这次整理后的 Mod 需要完整更新并重新加载游戏脚本；不要把新版热重载包投递给旧布局 bootstrap。

## Native

仓库的 `native/tpf2_native/tpf2_native.slnx` 是唯一维护和构建入口，不从仓库外的 VS 副本取源码。

- Controller：`hooks/` 是 Detour 框架，`telemetry/` 是只读采集，`control/` 是控制业务，`ipc/` 是通信。
- Loader：`lifecycle/` 管理 DLL 生命周期，`lua/` 是 Lua ABI 和导出入口，`ipc/` 是共享内存。
- `shared/` 保存两个项目共用的二进制协议与导出声明。
- DLL 名称和共享内存协议保持原样。生成物输出到 `.tmp-build/native/`，不进入源码目录或 Git。

## 工具和发布

| 入口 | 用途 |
| --- | --- |
| `tools/build/build-native.ps1` | 统一编译两个 DLL |
| `tools/build/build-native-mod.ps1` | 组装纯原生 Mod |
| `tools/build/build-workshop-package.ps1` | 按白名单组装完整 Mod，默认只读 |
| `tools/build/build-release-package.py` | 生成源码包，排除二进制、日志、缓存和历史文件 |
| `tools/install/install-mod.ps1` | 安装 Mod；游戏运行中拒绝替换 |
| `tools/web/start-web.ps1` | 启动 Web API 和独立前端 |
| `tools/diagnostics/` | 可复用的采集、验证和诊断工具 |
| `tools/visualization/` | 地图导出和通用绘图 |

所有构建器从自身位置推导仓库根目录，不硬编码本机源码盘符；打包不包含旧注入器。
运行路径统一见[完整 Mod 部署与运行路径](../usage/deployment.md)。发布运行时以 Mod 根目录为唯一归属，
运行状态、命令记录和资产缓存使用 `var/`，日志使用 `logs/mcp/`；Web 状态统一为 `var/mcp/`。
源码开发的分析记录使用 `diagnostics/`，临时构建使用 `.tmp-*/`，均不随 Mod 发布。

## 历史文件

`old/` 已加入 `.gitignore`。历史计划、阶段文档、一次性实机测试、IDA 脚本及确认无入口引用的
Python 模块归档在这里，不参与生产启动或发布。保留于本机不等于继续支持直接运行；需要时应先恢复相应版本及依赖。
逐文件映射见 `docs/development/directory-migration.json`。归档原来被跟踪的文件后，后续提交会移除旧路径；内容可从 Git 历史找回。
