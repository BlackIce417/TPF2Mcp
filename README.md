> **使用前说明：本项目采用远程线程注入方式，将 `tpf2_control.dll` 注入 Transport Fever 2 游戏进程。如果你介意 DLL 注入，请勿使用本项目。**

# TPF2 MCP

让 AI / MCP 客户端能够观察、理解并在受控条件下辅助运营
[Transport Fever 2](https://www.transportfever2.com/) 的本地 Mod 项目。

它把游戏内 Lua Mod、Python MCP Server 和本地铁路图 UI 连接起来：先读懂
路网与运营状态，再给出有依据的建议；涉及游戏修改时，必须走可审计的受控
任务流程。

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

## 能做什么

- 从正在运行的存档读取线路、车站、车辆、客货运与动态运行数据。
- 在浏览器中查看全网铁路图、站场局部图、列车位置、车站与车辆详情。
- 分析线路运力、候车与货物积压、班次、站外等待和拓扑风险，并生成运行图建议。
- 以受控 Task 方式创建或配置线路、购买并分配车辆、调整停站策略；默认不允许写入游戏。

## 项目组成

- `tpf2_mod/`：Transport Fever 2 Lua Mod 源码。
- `mcp_server/`：Python stdio MCP Server 与 Bridge 客户端。
- `ui/rail-map/`：独立 Vite 铁路调度图前端。
- `tools/`：安装、测试、导出、打包和验收工具。

## 快速体验

1. 在游戏中启用已安装的 `tpf2mcp` Mod，并进入一个存档。
2. 从 Mod 根目录的 `mcp_server/` 启动 MCP Server：

   ```powershell
   python -m pip install -r requirements.txt
   python start_server.py
   ```

3. 需要查看铁路图时启动 FastAPI JSON API：

   ```powershell
   python start_api.py
   ```

4. 另开终端启动前端：

   ```powershell
   cd ..\ui\rail-map
   npm install
   npm run dev
   ```

5. 浏览器打开 `http://127.0.0.1:5173/?view=network`。

Mod 不会自动启动外部进程；MCP Server、FastAPI API 和前端需要单独启动。默认发布包
是只读的。受控写入属于实验性能力，必须显式启用并通过 Task 审批流程执行。

## 文档

- [阶段成果与后续任务](docs/PROJECT_PROGRESS.md)：当前模块入口、三项目标进度及本次验证结果。

- [当前数据与调度能力（2026-09-25 代码复核）](docs/CURRENT_CAPABILITIES.md)：区分历史实测、当前接口、已知缺口和架构目标。
- [本地智能调度算法理论方案](docs/DISPATCH_ALGORITHM_THEORY.md)：区间动态限速、容量约束客货分配、站台—进路联合调度及统一滚动时域架构。

- [功能与受控操作入口](docs/agent-mcp-tools.md)
- [技术参考：架构、开发、安装与发布](docs/technical-reference.md)
- [前端架构与编码规范](docs/frontend-architecture.md)
- [架构说明](docs/architecture.md)
- [最终目标与验收边界](docs/FINAL_GOAL_ACCEPTANCE.md)
- [各阶段开发文档](docs/)

## 当前状态

项目已在真实 TPF2 存档中验证 Bridge、铁路图数据采集、运行状态读取和部分受控
线路/车辆操作。默认原则仍是：数据读取优先，无法由游戏引擎可靠验证的能力不会
伪装成可用功能。
