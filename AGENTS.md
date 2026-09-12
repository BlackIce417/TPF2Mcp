# Transport Fever 2 MCP

## 本机游戏路径

Transport Fever 2 的 Steam 安装目录：

```text
D:\Steam\steamapps\common\Transport Fever 2
```

TPF2 用户模组目录与 Bridge 目录仍须由实际游戏运行验证，不得把推测路径视为已确认能力。

## 开发约定

- 按阶段开发，先完成并验证 Bridge MRE，再扩展 MCP 功能。
- MCP Server 与 TPF2 模组必须通过 Bridge Protocol 通信；MCP Tool 不直接操作 Bridge 文件。
- 第一版以只读能力为主；写操作默认禁止，后续须遵循权限等级与 dry-run 约定。
- 对尚未验证的 TPF2 Lua API 能力标记为 `UNKNOWN`，以最小实验和实际日志确认。
