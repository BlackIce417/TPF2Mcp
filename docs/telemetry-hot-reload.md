# Lua 遥测热更新

实现日期：2026-10-18。Lua 5.2 离线行为测试已验证；实际游戏沙箱的 load 可用性和存档重载行为仍需实机确认。

## 首次安装

游戏脚本入口现在使用稳定的 hot_reload.lua 代理。已经运行的旧版本没有此入口，复制文件不能让它在当前 Lua 实例中自动出现。首次安装后重新载入存档；如果引擎保留了旧 Lua 缓存，需要重启一次游戏。以 bridge/heartbeat.json 出现 hot_reload.protocol_version=1 为加载证据。

此后运行中可更新以下模块：common、json、signal_direction、signal_state、operational_telemetry、state、runtime。不支持热换游戏脚本入口、bootstrap 自身、config、控制执行模块、DLL、模型或贴图。配置热刷新目前仍只有既有的写权限机制，不把修改 config 文件解释为热更新。

## 使用

游戏需处于继续执行模拟更新的状态。在已经更新好源码文件的 Mod 目录内执行：

~~~powershell
python tools/hot-reload-telemetry.py --mod-root .
~~~

开发时也可将项目源码发布到指定的已加载 Mod：

~~~powershell
python tools/hot-reload-telemetry.py --mod-root "<active_mod_root>" --source-root "<repository_root>"
~~~

工具检查新鲜心跳及 bootstrap 支持，复制七个白名单模块至 Mod 内的独立版本目录，最后原子替换请求指针。没有活动 bootstrap 时不发布。发布器不是通用 MCP 命令，不操作游戏存档或启用写控制。

bootstrap 最多每两秒检查一次请求（游戏暂停时回调可能停止）。加载全部源文件、核对长度、隔离加载模块、验证接口、迁移瞬态状态后，才切换运行实例。首次成功回调后报告 APPLIED。PUBLISHED_PENDING 只是未等到回执，不代表成功。REJECTED 保留旧实例；新实例回调抛错则 ROLLED_BACK，不会在同一次回调中再执行旧 tick。

此机制加载的是本机可信开发代码，不是安全沙箱。不能撤销任意模块代码已经造成的外部副作用；原生崩溃也无法由 Lua pcall 捕获。因此控制执行模块保持原实例，更新代码必须先通过测试。

## 状态与范围

- 会话 ID、信号清单、已消费请求 ID、计数器、运行采样进度保留。
- dispatcher 与 timetable 不重载，停车看门狗和命令幂等状态继续使用原实例。
- 世界快照等只读缓存可重新建立。路网模块未热换，既有 GUI 轨道资源映射保留。
- 每次热更新保持上一版实例用于回退，不自动重复尝试同一失败版本。
- 启动新游戏脚本实例时不重放旧请求，避免把上一会话的版本包误应用到新会话。
- 从 Mod 当前磁盘文件发布时，重载仍使用这些磁盘文件；指定项目源码发布只改变当前会话，不会顺便覆盖 Mod 的常规安装文件。需要持久化时另行正常同步/安装。
- 包和回执保存在 <active_mod_root>/bridge/hot-reload/；属于运行数据，不提交、不打包。
- 版本包切换本身有一次性的读取/编译成本；平时不扫描全部源码文件。

## 验证

测试覆盖同一 Lua 会话替换、真实 state/collector 依赖重建、会话与命令状态保留、语法错误、不完整包、非白名单模块、运行错误回退、未加载 bootstrap、过期心跳及先写包后发布指针。实际游戏中是否生效以对应 revision 的回执和新一轮遥测为准，不能用文件复制完成代替验收。
