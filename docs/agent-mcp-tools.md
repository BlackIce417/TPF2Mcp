# TPF2 Agent MCP 工具入口

运营 Agent 不应读取或改写 Bridge 文件，也不应为一次操作临时生成脚本。先读取资源
`tpf2://agent-operations`，再使用以下稳定工具入口：

- `get_dispatch_overview`：游戏、路网、数据能力和安全工作流总览。
- `get_station_dispatch_state(station_id)`：车站、接入线路、相邻节点和可用运营指标。
- `get_line_dispatch_state(line_id)`：线路、车辆、停站结构、诊断及实时客货需求。
- `get_vehicle_dispatch_state(vehicle_id)`：列车速度、运行状态、下一站、容量和实际装载。
- `get_agent_operations_guide`：返回可供模型直接遵循的标准调用顺序。

任何修改必须继续使用既有受控链路：

1. `get_operation_capabilities`
2. `propose_operation`
3. `validate_operation`
4. `create_task` / `plan_task`
5. `approve_task_step`
6. `continue_task`
7. `get_task` 验证后置条件

`execute_operation` 不向 MCP Agent 直接暴露；默认写策略仍为 `MANUAL`，每次继续任务最多执行一个变更。
