# TPF2 局部线路图

这是一个纯 JavaScript + SVG 的静态只读视图。直接打开 `index.html`
即可查看最近一次从游戏引擎导出的物理轨道数据。

前端支持鼠标滚轮缩放、按住拖拽平移，以及 `+`、`−`、`复位` 控件；
缩放范围为 50%–800%。左下角标尺的屏幕长度固定，默认 100% 时表示
`50 m`；缩放地图时改变标尺数值，例如 200% 显示 `25 m`、50% 显示
`100 m`。

轨道图不常驻显示 Terminal 圆圈和站台文字。标尺为 `50 m` 或更大时，鼠标
进入车站或站台范围只显示站名；放大到标尺小于 `50 m` 后，站台轨道悬停才
显示对应的 `T1`–`T4` 站台号。类型、长度和 Node ID 保留在右侧台账中。

车站实体包围盒仅作为透明的鼠标命中区域，不绘制边框。地图常驻显示紧凑
站名，鼠标进入车站范围时也会显示站名提示。

左上角的 `局部` / `全网` 用于切换同一页面的两个层级。全网视图启动时只读取
轻量的 `rail-network-manifest.js`，显示线路总览骨架、铁路车站和区域索引；双击
站点可放大到站场级，点击右侧线路可突出显示。线路在相邻停靠站台之间的轨迹
由游戏原始物理轨道图最短路推导，界面会明确标为 `DERIVED`。

原始轨道按 2 km 区域切分到 `rail-network-tiles/`。标尺小于 600 m 时，浏览器
只加载当前视口相交的区域；移出区域或缩回总览会删除相应 SVG 和数据引用。
因此初始页面不再创建近两万个轨道 SVG 对象，局部视图也不会加载全网数据。
全网视图的 100% 总览是最远视角，不能继续缩小；复位始终返回该全局范围。
点击 `+` / `−` 时以屏幕中心为缩放焦点；滚轮缩放以鼠标所在位置为焦点。
区域细节把每个 Terminal 沿同轨型曲线追踪至两端咽喉前道岔，以灰色宽带绘制
站台范围；轨道坐标为引擎原始数据，站台范围与长度来源标记为曲线推导。

全图采集不会加入周期性 world snapshot。加载了新版 Mod 的存档中，显式调用
一次 `BridgeClient.export_rail_network()` 才会生成 Bridge 侧的
`rail-network.json`，随后执行：

```powershell
python tools\export-rail-network-map.py
```

当前实机导出包含 19,035 个物理铁路节点、19,611 条边、130 个铁路站组和
77 条铁路线路；77 条线路全部完成物理图寻路，断开区段为 0。

推荐通过本机只读服务打开页面：

```powershell
python tools\serve-rail-map.py
```

然后访问 `http://127.0.0.1:8765/?view=network`。服务提供按需区域 JSON API
和 SSE 状态流；页面会显示 Bridge 在线状态及 snapshot sequence。Bridge 中的
`rail-network.json` 发生变化时，服务自动重建分片并通知页面刷新。服务不会
自行周期性触发完整游戏铁路扫描，避免影响游戏帧率。

当前样板聚焦 Chiasso station group `552273`。重新读取游戏快照并生成
静态数据：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'mcp_server\src')
python tools\export-static-station-map.py `
  --station-id 552273 `
  --output-directory ui\rail-map
```

数据文件：

- `local-station.json`：便于其他程序读取的标准 JSON。
- `rail-network-data.json`：完整铁路图及线路物理寻路结果（离线诊断源）。
- `rail-network-manifest.js`：浏览器启动时加载的轻量总览与区域索引。
- `rail-network-tiles/`：进入对应区域后才动态加载的原始轨道分片。
- `data.js`：供 `file://` 直接打开的网页读取，避免本地 fetch 限制。
- `ground-truth.json`：截图 OCR 与人工确认的站场实况标注。
- `ground-truth.js`：供本地网页直接读取的同一份实况标注。
- `physical-track-data.json`：从游戏组件读取并裁剪后的真实节点、边、切线和轨型。
- `physical-track-data.js`：供本地网页直接读取的同一份物理轨道数据。
- `preview.png`：Chromium/Edge 无头渲染的验收预览。

## 当前图的语义

- 站名 `Chiasso` 来自截图 OCR。
- 4 个客运站台、2 个高速站台和 2 个普速站台来自用户人工确认。
- 上方两台标为高速、下方两台标为普速，是根据截图作出的视觉方位推断。
- 底部仅保留现有只读快照中的 terminal 与线路停靠关系。
- 当前版本不显示列车、车辆数、班距或 Rate。
- 股道坐标、连接关系、曲线切线和轨型来自游戏引擎组件。
- 黄色道岔点按物理节点的连接度数计算，节点度数大于等于 3。
- `child_station_count` 不是站台数，也不是股道数。

站台长度采用统一优先级：系统直接长度字段、车站 Construction 所属轨道
曲线、Terminal 两侧至咽喉前普通节点的曲线长度。当前 Freestyle 车站未
暴露前两类数据，因此使用第三级几何计算，并以星号标明推导值。信号状态
仍未采集，界面不显示列车或实时占用信息。
