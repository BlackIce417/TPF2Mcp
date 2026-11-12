# 项目文档

- [完整 Mod 部署与运行路径](usage/deployment.md)：所有部署文档统一采用的路径表、启动和更新方式。

- [目录与依赖约定](architecture/project-layout.md)：Python、Lua、C++ 的目录职责和构建入口。
- [线路允许站台增删](usage/line-stop-platforms.md)：参数、编号、主站台接替及执行验证。
- `architecture/`：系统、前端、拓扑与原生遥测设计。
- `development/`：协议、API 核验、开发工具与迁移清单。
- `usage/`：当前功能、调度操作和运行说明。

历史阶段计划和已退出当前工程的文件保存在本机 `old/`，该目录被 Git 忽略。
原来受 Git 跟踪的文件仍可通过版本历史恢复；新检出仓库不依赖 `old/` 运行。
