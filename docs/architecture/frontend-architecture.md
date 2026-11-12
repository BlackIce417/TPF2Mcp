# 前端架构与编码规范

本项目采用真正的前后端分离：`ui/rail-map/` 是独立 Vite 前端，`mcp_server/` 是
FastAPI JSON API。浏览器不从 Python 获取页面、脚本或样式，Python 也不得生成 HTML
或 JavaScript 数据包装器。

规范基线采用 MDN 的 [JavaScript modules](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules)
与 [`<template>` 元素](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/template)，
后端边界采用 FastAPI 的 [静态文件说明](https://fastapi.tiangolo.com/tutorial/static-files/)中
“挂载是独立子应用”的定义；本项目选择不在 API 进程挂载前端。

## 目录职责

```text
ui/rail-map/
├─ src/*.html             多页面入口与页面语义结构
├─ src/pages/network/     站场图入口与领域模块
├─ src/pages/regions/     调度区页面、地图、侧栏和运行状态
├─ src/pages/timetable/   运行图入口与领域模块
├─ src/shared/            无业务归属的浏览器模块
├─ src/styles/            页面样式
├─ src/templates/         可复用 HTML 片段
├─ public/vendor/         固定版本的浏览器第三方库
├─ package.json           前端命令与依赖
└─ vite.config.mjs        开发代理与构建配置

mcp_server/src/tpf2_mcp/
├─ web_app.py             仅定义 /api 路由
├─ web_state.py           业务状态与 Bridge 适配
└─ web_store.py           SQLite 存储

var/rail-map/             后端生成的路网、瓦片和车站预览缓存；不属于前端源码
```

## 强制规则

1. Python 不得包含 `<!doctype>`、`<html>`、`<script>`、`<style>` 或内联事件字符串。
2. FastAPI 不挂载前端目录；业务结果只通过 `/api/*` 返回 JSON，状态流使用 SSE。
3. HTML 不写内联样式、内联脚本或 `onclick` 等事件属性。
4. 新 JavaScript 使用 ES Modules；入口文件只负责组装，HTTP、状态和视图分模块。
5. API 调用集中在共享 HTTP 客户端或页面数据层，必须处理超时、非 2xx 和无效响应。
6. 动态文本使用 `textContent`；固定结构使用 HTML `<template>`，不得用字符串拼 HTML。
7. Python 导出器只生成 JSON；前端不得再依赖 `window.X = {...}` 形式的生成脚本。
8. 修改边界时同步更新自动化测试和本文件。
9. 调度区复用全局路网的简化概览底图，区域颜色由后端在生成阶段合并到概览
   矢量链；放大后与全局路网一样按视口加载 `/api/rail/tile/*`，并按 edge 区间
   归属着色。精细层使用 `src/shared/pixi-viewport.js`，缩回远景时卸载瓦片。

## DOM 与 Sidebar 约定

- HTML 管结构，CSS 管样式，JavaScript 管数据和行为。页面标题、统计字段、详情区、
  空状态、工具栏和 Sidebar 分区必须预先存在于页面 HTML 或模板中。
- JavaScript 通过明确的业务 `id` 定位固定节点，只更新 `textContent`、属性、显隐和
  状态 class；禁止通过父子层级或复杂选择器猜测固定字段的位置。
- 只有数量无法预先确定的线路、车辆、车站、边界、日志以及地图图元允许动态创建。
  动态列表应具有固定的 HTML 容器，重复项优先使用 `<template>`。
- 所有侧栏使用 `app-sidebar`，右侧栏增加 `app-sidebar-r`，左侧栏增加
  `app-sidebar-l`，并叠加页面业务 class。公共侧栏样式只放在
  `src/styles/sidebar.css`。
- 页面字段命名采用业务前缀，例如 `dispatch-region-name`、
  `dispatch-runtime-train-count`。从页面显示文字应能通过 DOM `id` 或 API JSON 字段名
  快速追踪到负责填充它的模块。

数据流保持单向：

```text
FastAPI /api/* -> shared/http.js（或页面 api 模块） -> JSON
    -> page/sidebar 模块 -> 已存在的 HTML DOM
```

## 本地运行

后端：

```powershell
conda run -p .\.venv python .\mcp_server\start_api.py
```

前端使用另一终端：

```powershell
cd .\ui\rail-map
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173/?view=network`。Vite 将 `/api` 代理到
`http://127.0.0.1:8765`。生产构建执行 `npm run build`，输出在 `dist/`，仍应由独立
前端服务器部署，不得重新塞回 Python 源码。

需要连接其他 API 端口时，在启动 Vite 前设置 `TPF2_API_TARGET`，例如
`$env:TPF2_API_TARGET='http://127.0.0.1:8766'`。
