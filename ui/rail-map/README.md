# TPF2 局部线路图

这是一个 HTML 模板 + JavaScript + SVG 的只读视图。通过本机 HTTP 服务打开
`index.html`，即可查看最近一次从游戏引擎导出的物理轨道数据。

## 前端文件分工

- `index.html`：站场图页面结构，不放样式和业务脚本。
- `network.css`：站场图全部样式。
- `network-page.js`：站场图页面级事件，例如页面导航。
- `template-runtime.js`：加载外部 HTML 模板并提供字段、插槽填充工具。
- `templates/*.html`：侧栏、详情、表格行等可人工维护的 HTML 结构与固定文字。
- `vendor/jquery-4.0.0.min.js`：本地固定版本的 jQuery 完整构建。
- `network-app.js`：全网路网 SVG 渲染、交互和动态数据绑定，不存放侧栏 HTML。
- `timetable.html`：运行图页面结构，不放样式和业务脚本。
- `timetable.css`：运行图全部样式。
- `timetable-page.js`：运行图页面级事件，例如返回站场图。
- `timetable.js`：运行图的数据读取、计算和 SVG 绘制，列表与详情来自 HTML 模板。
- `app.js`：按所选车站加载静态站场拓扑缓存，并绘制局部预览。

HTML 内禁止新增 `<style>`、`style` 属性、无 `src` 的 `<script>` 和 `onclick` 等内联事件。
页面中需要调整文字或字段容器时改 HTML，需要调整外观时改对应 CSS，需要调整
数据和行为时改对应 JS。`rail-network-*.js/json`、`rail-network-tiles/` 和
`station-previews/` 是生成数据，不属于手工维护的页面代码。

从 jQuery 接入后的新功能开始，DOM 查询与修改、事件绑定和 HTTP 请求统一使用
jQuery。现有原生 JavaScript 暂不做批量重构，后续在修改相应模块时逐步迁移。

外部模板通过 `fetch` 按启动顺序一次性载入，因此不再支持双击 `index.html` 的
`file://` 运行方式；请使用下文的 `serve-rail-map.py`。模板仅包含侧栏 DOM，轨道、
站台、道岔、车辆和信号等坐标图形仍由 JavaScript 根据游戏数据动态创建 SVG。

前端支持鼠标滚轮缩放、按住拖拽平移，以及 `+`、`−`、`复位` 控件；
缩放范围为 50%–800%。左下角标尺的屏幕长度固定，默认 100% 时表示
`50 m`；缩放地图时改变标尺数值，例如 200% 显示 `25 m`、50% 显示
`100 m`。

轨道图不常驻显示 Terminal 圆圈和站台文字。标尺为 `50 m` 或更大时，鼠标
进入车站或站台范围只显示站名；放大到标尺小于 `50 m` 后，悬停物理站台才
显示对应的 `P1`–`Pn` 站台号。右侧台账同时列出物理站台与其 `T1`–`Tn`
到发面映射、类型、长度和 Node ID。

车站实体包围盒仅作为透明的鼠标命中区域，不绘制边框。地图常驻显示紧凑
站名，鼠标进入车站范围时也会显示站名提示。

左上角的 `局部` / `全网` 用于切换同一页面的两个层级。全网视图启动时只读取
轻量的 `rail-network-manifest.js`，显示线路总览骨架、铁路车站和区域索引；双击
站点可放大到站场级。右侧线路列表仅显示线路名称和停站数量，点击不触发地图
操作。全网和局部图只使用统一颜色绘制物理路网，不渲染最短路推导的彩色线路
覆盖层，也不提供线路选择高亮。

原始轨道按 2 km 区域切分到 `rail-network-tiles/`。标尺小于 600 m 时，浏览器
只加载当前视口相交的区域；移出区域或缩回总览会删除相应 SVG 和数据引用。
因此初始页面不再创建近两万个轨道 SVG 对象，局部视图也不会加载全网数据。
全网视图的 100% 总览是最远视角，不能继续缩小；复位始终返回该全局范围。
点击 `+` / `−` 时以屏幕中心为缩放焦点；滚轮缩放以鼠标所在位置为焦点。
区域细节先把 Terminal 还原为物理站台，再以灰色宽带绘制站台范围。相邻股道
间的正常 `5 m` 线间距不再判为岛式站台；只有存在站台宽度的大间距，并且两个
到发面朝向该间距时才合并为岛式站台。侧式站台按一倍宽度、岛式站台按两倍
宽度绘制；悬停岛式站台时显示中部分界线，并根据鼠标所在一侧显示对应到发面
的站台号。轨道坐标仍为引擎原始数据，推导结果会在数据中标记来源。

全图采集不会加入周期性 world snapshot。加载了新版 Mod 的存档中，显式调用
一次 `BridgeClient.export_rail_network()` 才会生成 Bridge 侧的
`rail-network.json`，随后执行：

```powershell
python tools\export-rail-network-map.py
```

当前实机导出包含 19,878 个物理铁路节点、20,401 条边、86 个铁路站组和
46 条铁路线路；46 条线路全部完成物理图寻路，断开区段为 0。

推荐通过本机只读服务打开页面：

```powershell
python tools\serve-rail-map.py
```

然后访问 `http://127.0.0.1:8765/?view=network`。服务提供按需区域 JSON API
和 SSE 状态流；页面会显示 Bridge 在线状态及 snapshot sequence。Bridge 中的
`rail-network.json` 发生变化时，服务自动重建分片并通知页面刷新。服务不会
自行周期性触发完整游戏铁路扫描，避免影响游戏帧率。

Bridge 产生当前存档的铁路拓扑后，`export-rail-network-map.py` 会遍历全部车站，
为每个车站生成一份独立的静态物理拓扑缓存。全网选择车站后点击“局部”，页面
按 Station Group ID 直接读取对应缓存；未选择车站时不会进入旧的默认站场，而是
提示“请选择对应车站”。局部图不读取列车位置、占用或动态遥测。

TPF2 会把同一模块化车站中的客运和货运设施拆成不同 Station Group。局部缓存
以共同的 `construction_entity_id` 重新归并物理车站，因此选择其中任意一个站组
都会同时显示该 Construction 内的客运与货运站台；不同 Construction 即使同名，
也不会被错误合并。

手工重新生成全网、分片和全部车站缓存：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'mcp_server\src')
python tools\export-rail-network-map.py
```

数据文件：

- `rail-network-data.json`：完整铁路图及线路物理寻路结果（离线诊断源）。
- `rail-network-manifest.js`：浏览器启动时加载的轻量总览与区域索引。
- `rail-network-tiles/`：进入对应区域后才动态加载的原始轨道分片。
- `station-previews/manifest.json`：当前存档全部车站缓存索引。
- `station-previews/station-<ID>.json`：指定车站的轨道、站台、道岔和局部台账。

## 局部图的语义

- 每份局部图绑定当前存档的 `save_id` 和一个 Station Group ID。
- 轨道节点、边、切线、站台中心线和拓扑来自 Bridge 的游戏引擎导出。
- 图的窗口由车站边界向外扩展，保留站场咽喉和相邻线路上下文。
- 局部图是生成后存盘的静态拓扑，不显示列车、占用或实时信号状态。
- 股道坐标、连接关系、曲线切线和轨型来自游戏引擎组件。
- `terminals` 表示可办理到发的站台面，`platforms` 表示前端绘制的一座物理站台；
  岛式站台通常由两个 Terminal 面合并为一个 Platform，不能按两个站台绘制。
- 黄色道岔点按物理节点的连接度数计算，节点度数大于等于 3。
- `child_station_count` 不是站台数，也不是股道数。

站台长度采用统一优先级：系统直接长度字段、车站 Construction 所属轨道
曲线、Terminal 两侧至咽喉前普通节点的曲线长度。当前 Freestyle 车站未
暴露前两类数据，因此使用第三级几何计算，并以星号标明推导值。信号状态
仍未采集，界面不显示列车或实时占用信息。

固定车站 Mod 不能直接把 construction 的轨道边长度当作旅客站台名义长度。
当前按已安装资源校正：`hhz.con` 的 216 m 轨道边对应 220 m 有效站台；
`CRST_HM.con` 的 228/456 m 图遍历结果对应 `CRST_WA_450.mdl` 的 450 m；
汉口的 456 m 对应 `PlaLen` 的 450 m 档位；武汉的 484 m（含两端连接边）对应
主体轨道的 480 m。原始轨道跨度保存在 `platform_track_span_m`，前端只显示
`platform_length_m` 的名义值；Freestyle Station 仍保留实测曲线长度。

标准模块站另按 construction 语义校正：`modular_station.con` 与
`CRST_modular_station.con` 的每节站台均为 `40 m`。游戏导出的可行驶轨道
中心线可能在站台两端各内缩约 `1 m`，因此中心线测量值仅用于推导模块数，
最终长度使用“模块数 × 40 m”；原测量值保存在 `platform_track_span_m`，
模块长度和数量分别保存在 `platform_module_length_m` 与
`platform_module_count`。客运和货运站台独立计算，不互相套用最长值。
