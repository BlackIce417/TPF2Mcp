# 车站咽喉自动识别

实现入口：`mcp_server/src/tpf2_mcp/station_throats.py`。
站场预览生成时附带 `throat_model`，局部图将可见候选轨道标青、归属争议轨道标橙，并显示边界连接口。
重新生成站场缓存后生效；不会自动部署安装版 Mod 或开启游戏控制。

## 方法及输出

按共同 Construction 合并物理车站，优先以预处理后的 `platform_edge_ids` 定义站台核心。
从核心边界向外沿二度节点链寻找道岔；核心边不可归入咽喉，也不可用来连接两端咽喉。
缺少核心时退回 Terminal 节点锚定，标记 `CORE_UNAVAILABLE`，此时不能保证排除站台。
对短链相连的道岔进行聚合，合并同站重复候选，检测不同车站对轨道和道岔的共同声明。
长度以三维 Hermite 曲线采样计算，不以轨道碎边数量计算。
输出区域 ID、所属站组、轨道、道岔、连接口、争议元素、边界原因和输入指纹。
归属不明确时保留 `AMBIGUOUS_SHARED_REGION`；普通输出也仅为 `CANDIDATE`。

默认平台至首道岔搜索上限 800 m，道岔间连接链上限 250 m。
这些是可调整的启发式参数，不是铁路规范；长咽喉可能被拆分，紧邻线路所可能被包含。
当前使用无向拓扑确定候选范围，不提供合法进路，不依赖信号灯色，不要求玩家命名。
源路网没有 Construction 边归属时仍可运行；新版 Lua 导出器补充归属及查询质量字段，尚未部署到游戏。
没有找到候选的站列入 `unresolved_stations`，不能解释成没有咽喉。
区域 ID 仅在原始实体不变时稳定；输入的 save_id 缺失时保留为空，禁止据此作为执行控制依据。

## 离线使用

从仓库根目录设置 `PYTHONPATH=mcp_server/src`，使用项目 Python：

```text
.venv/python.exe -B -m tpf2_mcp.station_throats var/rail-map/rail-network-data.json --output var/rail-map/station-throats.json
```

输出路径必须位于项目或打包 Mod 根目录。分析不连接游戏、不改变轨道。

2026-10-29 当前存档离线验证：4,405 节点、4,472 边、16 站组，生成 26 个候选；
各站均有候选。这是覆盖性检查，不是人工边界准确率验收。

## 独立核验页面

主导航「咽喉识别」打开 `throats.html`，支持切站、选择候选、查看接口和边界依据、缩放平移及周边轨道开关。
紫色为站台核心，青色为候选，橙色为归属争议。`/api/station-throats` 返回缓存索引并拒绝跨存档缓存；
几何使用站场预览附带的 `throat_geometry`，补齐普通站场窗口外的候选轨道。
「重新读取缓存」只重读已生成缓存，不触发游戏采集或算法重算。

2026-10-29 修正后：16 站、26 候选、平台重叠边数 0。Almaty 一条候选边超出普通预览窗口，独立页面已补齐。
逐站总览见 `diagnostics/station-throats-review/all-stations.png`，统计见同目录 `audit.json`。
当前仅检查了拓扑形态与平台分离，没有人工标注真值，不能据此给出准确率。
