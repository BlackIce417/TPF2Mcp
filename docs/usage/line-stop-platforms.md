# 线路停站的允许站台

`add_line_stop_platform` 添加允许站台，`remove_line_stop_platform` 删除允许站台。
两者只修改指定线路的一次停站，影响该线路全部列车，不修改列车的临时指定进路。

先从 `get_train_routes` 读取 `stop_index`、`station_id`、`primary_terminal` 和 `allowed_terminals`。
`stop_index` 与 `station_index` 从 0 开始；`platform_number` 为 `terminal_index + 1`，
沿用路线导出接口的编号，不代表游戏里自定义的站台标签。

添加示例（用实际读取到的 ID 和索引替换示例值）：

```json
{
  "command_id": "platform-add-001",
  "reason": "为该次停站增加备选站台",
  "line_id": 100,
  "stop_index": 0,
  "station_id": 200,
  "station_index": 0,
  "platform_number": 3,
  "dry_run": true
}
```

默认只预览。实际执行设置 `dry_run=false`，并传入
`confirmation="ADD_LINE_STOP_PLATFORM:platform-add-001"`。
删除工具使用 `REMOVE_LINE_STOP_PLATFORM:<command_id>`。
实际执行仍受 Mod 写权限与操作白名单控制。

- 添加已允许的站台不会重复添加；删除未配置的站台保持集合不变。
- 删除主站台时，将第一个剩余备选站台提升为主站台；拒绝删除最后一个允许站台。
- 执行前在 Lua 核对车站、原站台集合和停站策略，添加时检查子站、站台存在及客货属性兼容。
- 保留其他停站、途经点、装卸配置和等待策略；执行后回读全停站配置验证。
- 回读时将最新线路目录发布回共享内存；复用已有静态资产，不重新采集城市、产业或路网。
- `POSTCONDITION_VERIFIED` 表示站台配置已核对，不保证列车立即改道或目标站台可达。

命令链路：Python → Loader 共享内存 → Lua 游戏线程 → `updateLine`。
新增命令号：`0x106` 添加，`0x107` 删除。需要更新 Loader 和 Lua，MCP 工具定义随 Python 更新。

本轮完成离线行为测试及 DLL 编译；原生 StationTerminal/vector 绑定和实车改线效果仍需在新版 Mod 中验证。
