继续当前 TPF2 MCP 项目，但现在不要扩展任何 Town、Industry、Station、Line、Vehicle、Analysis 功能。

当前代码审查结论：

- Python 单元测试已经通过；
- 工程分层基本符合设计；
- 当前尚未完成 TPF2 实机 Bridge 验证；
- Phase 1 暂时不得标记为完成。

本轮只处理以下事项。

## 1. 修复硬编码 bridge 路径

当前：

```lua
C:/Users/Anakin/AppData/Roaming/Transport Fever 2/tpf2_mcp_bridge
```

属于不可接受的开发机硬编码。

Windows 环境目标路径为：

```text
%APPDATA%\Transport Fever 2\tpf2_mcp_bridge
```

研究 TPF2 Lua 是否存在可靠方式直接获取 userdata/config 路径。

如果没有经过实际验证的 Lua API，不允许自行假设。

若无法从游戏 Lua 环境动态获得，则修改：

```text
tools/install-mod.ps1
```

使安装脚本：

1. 读取 `$env:APPDATA`；
2. 创建 bridge 目录；
3. 将 Windows 路径转换成 Lua 可使用的 `/` 路径；
4. 安装模组时自动生成对应 `config.lua`；
5. Python 和 Lua 必须指向同一目录。

安装完成后输出：

```text
Mod directory:
Bridge directory:
Generated Lua config:
```

禁止保留任何：

```text
C:/Users/Anakin
```

这样的开发机路径。

---

## 2. 增强 Probe

当前 probe 需要实际验证：

```text
require
io.open write
io.open read
os.rename
os.remove
absolute path
api availability
api.engine availability
api.engine.util.getWorld
api.engine.util.getPlayer
```

heartbeat 中增加：

```json
{
  "probe": {
    "lua_version": "...",
    "require": true,
    "io_open": true,
    "io_read": true,
    "io_write": true,
    "os_rename": true,
    "os_remove": true,
    "absolute_path": true,
    "api": true,
    "api_engine": true,
    "get_world": true,
    "get_player": true
  }
}
```

每个测试必须独立 `pcall`。

一个能力失败不能导致整个模组退出。

---

## 3. 修正 bridge_ready 定义

目前：

```lua
bridge_ready = probe.io_read and probe.io_write
```

定义过于宽松。

对于当前文件 IPC，至少应该要求：

```text
io_read
io_write
rename
absolute_path
```

全部成功。

如果使用新的不依赖 rename 的协议，则根据实际实现重新定义。

---

## 4. 增加明确的 Bridge Protocol 校验

Lua 收到 command 后检查：

```text
schema_version
request_id
command
params
```

缺失字段不得进入 dispatcher。

例如：

```text
INVALID_REQUEST
UNSUPPORTED_SCHEMA_VERSION
UNKNOWN_COMMAND
```

不要让：

```lua
command.request_id
```

等字段在完全未校验状态下直接参与逻辑。

---

## 5. Phase 1 暂时只允许两个 command

保持：

```text
ping
get_game_state
```

禁止增加其他命令。

`get_game_state` 当前只需要证明：

```text
game script
→ api.engine
→ getWorld()
→ getPlayer()
```

工作。

暂时不要求实现完整 World Snapshot。

---

## 6. 增加 Bridge 集成测试脚本

增加：

```text
tools/test-live-bridge.ps1
```

依次执行：

```text
status
ping
game-state
```

输出必须清晰。

例如：

```text
[1/3] bridge status ... PASS
[2/3] ping/pong ...... PASS
[3/3] get_game_state . PASS
```

失败时打印：

```text
bridge path
heartbeat state
timeout
probe result
```

---

## 7. 增加日志采集辅助脚本

增加：

```text
tools/collect-diagnostics.ps1
```

收集：

```text
heartbeat.json
command.json
response.json
state.json
Transport Fever 2 stdout.txt
```

复制到：

```text
diagnostics/<timestamp>/
```

注意不要删除原始文件。

---

## 8. MCP 暂时维持现有实现

本轮不要为了升级 MCP SDK 重构整个项目。

当前 hand-written stdio MCP server 可暂时作为 Phase 1 MRE。

但是必须在：

```text
docs/architecture.md
```

记录：

```text
Current implementation:
legacy/minimal MCP compatibility layer

Planned:
official MCP SDK migration after live bridge validation
```

同时不要把：

```text
2025-03-26
```

描述为最新 MCP 协议。

后续 Phase 2 再统一迁移官方 MCP SDK。

---

## 9. 增加真实 Live Test 与 Mock Test 区分

所有测试结果必须明确区分：

```text
OFFLINE TEST
MOCK TEST
LIVE TPF2 TEST
```

绝对不允许：

```text
MockBridge PASS
```

被描述成：

```text
TPF2 Bridge PASS
```

---

## 10. 更新 docs/tpf2-api-notes.md

运行游戏之前保持：

```text
UNKNOWN
```

运行游戏之后才能修改。

每一项记录：

```text
Capability
Result
TPF2 version
Observed output
Evidence/log
```

---

# 本轮验收标准

必须在真实 Transport Fever 2 中完成：

```text
启动 TPF2
   ↓
加载测试存档
   ↓
tpf2_mcp game script 被加载
   ↓
heartbeat.json 出现
   ↓
bridge_ready = true
   ↓
Python status 成功
   ↓
Python ping
   ↓
Lua pong
   ↓
Python get_game_state
   ↓
Lua 调用 api.engine.util.getWorld()
   ↓
Lua 调用 api.engine.util.getPlayer()
   ↓
返回 Python
   ↓
MCP tools/call get_game_state 成功
```

---

# 必须提交的证据

本轮完成后提供：

```text
1. 修改后的完整目录树

2. 所有修改文件

3. python unit test 输出

4. tools/test-live-bridge.ps1 输出

5. heartbeat.json

6. ping 对应 command.json

7. ping 对应 response.json

8. get_game_state 对应 state.json

9. get_game_state 对应 response.json

10. TPF2 stdout.txt 中所有 [tpf2-mcp] 日志

11. docs/tpf2-api-notes.md 更新结果

12. 当前仍然 UNKNOWN 的能力
```

如果没有真实 Transport Fever 2 环境可运行，则明确写：

```text
LIVE TPF2 TEST NOT PERFORMED
```

不得伪造日志或用 MockBridge 代替。

---

# 暂时禁止

本轮禁止实现：

```text
town collector
industry collector
station collector
line collector
vehicle collector
finance collector

find_unprofitable_lines
find_overcrowded_stations

pause_game
rename_line
buy_vehicle
build_track

复杂 GUI
```

本轮唯一目的：

```text
把真实 TPF2 ↔ Python ↔ MCP 的最小链路跑通。
```

完成这个链路后停止扩展，等待下一阶段审查。