# 列车间距控制模块

独立的第一版算法；不负责采集游戏数据、启动轮询或开启控制系统。旧的
`tpf2_mcp.train_spacing` 保留兼容导入，原控制系统调用会进入这里的计算引擎。
需要跨周期平滑控制时使用 `TrainSpacingController`。

## 算法

1. 根据有向 MOVE_PATH 建立曲线累计里程。完整车体各部件分别投影到轨道；
   用部件中心和三维包围盒外接球半径估算整列前后端。
2. 在后车前方路径上匹配同向前车，选择尾部间距最小者。不依赖线路 ID，
   两条线路进入相同有向轨道后也能匹配。不能据此处理尚未进入共享轨道的汇入冲突。
3. 净间距 `gap = 前车尾里程 - 后车头里程`，可用距离
   `D = gap - 固定余量 - 定位余量 - 双方投影误差`。
4. 不抵扣前车未来的制动距离，按静止障碍计算后车速度包络：
   `v_limit = max(0, sqrt((b*tau)^2 + 2*b*max(D,0)) - b*tau)`。
   `b = min(导出制动参数, 配置减速度)`；`tau = (配置反应延迟 + 车体帧龄) * 游戏倍速`。
5. 降限速立即生效于输出；提高限速采用死区和每秒最大增量。即使实际车速低于
   建议上限也保留租约，避免一达到目标就撤销限速。每个周期刷新区间和过期时间。

这是简化的制动距离包络，不是完整 Gipps 模型或经过标定的列控安全系统。
默认减速度 0.35 m/s²、反应时间 3 秒、固定余量 20 米、定位余量 5 米，均是
待实测的初值。包围盒端点是估计，不是游戏提供的精确车钩坐标；曲率、路径窗口
和采样延迟仍会影响误差，不能宣称外接球法已给出沿轨端点的严格误差上界。

## 输入与调用

输入为已有 `rail_live.normalize_live_state` 输出的规范化帧，不直接读取数据库。
宿主持续取得新帧并调用 `step`；`sampled_at`、`footprint_sampled_at`、`now` 使用
同一 Unix 秒时间轴。实际帧里应携带 `simulation.speed_multiplier`；省略整个
simulation 时按离线单倍速样例处理，显式未知或暂停倍速会拒绝生成限速。

每列车需要：`entity_id`、`edge_id`、`edge_param`（node0→node1 参数）、
`current_edge_index`、`speed_mps`、完整车体及其时间戳、`brake_decel_mps2`。
路径可用 `route`、`route_window`，或 `path_edge_ids/path_edge_directions`。
方向必须是布尔值，路径必须首尾连接；窗口 start/current index 是原始路径索引。
完整车体可用 `train_envelope`，测试/外部适配也可传 `body_samples`。

```python
from tpf2_mcp.algorithms.train_spacing import TrainSpacingController

controller = TrainSpacingController(network)
result = controller.step(live, now=now)  # 只计算
commands = result['commands']
# 下一帧继续使用同一个 controller；切档或拓扑更新时重新创建。
```

输出包括 `decisions`（原始速度包络或诊断）、`commands`（平滑后的实际建议租约）、
`submitted` 和回调返回值 `receipt`。限速租约包含 vehicle_id、leader_vehicle_id、
edge_ids、path_index_start/end、speed_mps、expires_at、净间距及估计端点里程。
里程是在后车路径上的局部累计值，不是世界坐标。默认租约有效期 5 秒。

## 接口适配

```python
from tpf2_mcp.algorithms.train_spacing import native_batch_sink

# 在现有宿主的发布锁内调用；writer 是宿主持有的 NativeLeaseWriter。
sink = native_batch_sink(writer, generation=next_generation,
                         other_leases=current_other_leases, now=now)
result = controller.step(live, now=now, sink=sink)
```

`sink(commands)` 接收完整的间距租约集合，空集合表示撤销本模块之前的租约。
适配器合并宿主传入的其他租约，过滤旧 `spacing:` 租约，再调用已有
`NativeLeaseWriter.write`。宿主必须串行发布并提供完整的其他租约，不能在现有
ControlSystem 旁再启动一个抢写同一 INI 的发布器。回调异常会上抛，控制器不提交
该周期的历史状态。接口写入成功不等于 DLL 已执行，也不等于列车达到目标车速。

## 离线入口

在项目根目录的 PowerShell 中：

```powershell
$env:PYTHONPATH = 'mcp_server/src'
.\.venv\python.exe -m tpf2_mcp.algorithms.train_spacing --network network.json --live live.json
```

输出 JSON 到 stdout，不写控制文件。默认按帧采样时间回放；`--now` 可检验陈旧帧，
`--policy` 可指定配置 JSON。网络使用已有路网 nodes/edges 数据。

## 当前边界与验证

- 重复边无法唯一判断 occurrence 时返回 `AMBIGUOUS_PATH_OCCURRENCE`。
- 缺失车体/方向/路径、过期观测不当作前方无车。第一版只要帧内有列车观测不完整，
  全帧其他车也暂不生成限速；后续可按已知冲突范围缩小影响。
- 前車部分车体无法投影到后车路径时返回未知，尚未实现跨分岔整列占用图。
- 对向车不是本模块的跟驰目标；对向闭塞、信号和进站冲突仍由游戏或后续模块处理。
- 低于接口最低速度（默认 8 km/h）或列车重叠时返回 `NATIVE_STOP_REQUIRED`，
  不把它改成正值限速；停车处置仍需要宿主/游戏处理。
- 数据无效时输出空命令集合并附拒绝原因，不保证靠租约撤销或到期来安全停车。
- 当前执行字段支持边与路径索引范围；路径 generation、方向和精确边内范围的
  执行一致性仍需后续验证。这一版没有执行游戏内闭环验收。

测试见 `tests/test_train_spacing.py`、`tests/test_train_spacing_module.py` 与现有
控制系统测试，覆盖首尾计算、曲线、反向、重复边、缺失数据、过期、重叠、平滑、
接口实际文件写入/撤销和其他租约保留。
