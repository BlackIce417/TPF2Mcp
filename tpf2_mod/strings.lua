function data()
    return {
        en = {
            TPF2_MCP_NAME = "tpf2mcp",
            TPF2_MCP_DESCRIPTION = [[Connects Transport Fever 2 to an external MCP client. Python 3.11 or newer is required.

All paths are relative to this Mod's installation root. Prepare your own Python environment with dependencies listed in mcp_server/requirements.txt.

Then run:
python mcp_server/start_http_server.py

Connect to http://127.0.0.1:8766/mcp. For stdio MCP use python mcp_server/start_server.py.
Dispatch commands and receipts: logs/dispatch/. Service errors: logs/mcp/. Per-tool-call and HTTP access logs are disabled. State and caches: var/. See docs/usage/deployment.md.

Web API: in the same directory run:
python mcp_server/start_api.py
In another terminal at the same Mod root, run npm --prefix ui/rail-map install and npm --prefix ui/rail-map run dev, then open http://127.0.0.1:5173/?view=network. The published package is read-only by default.]],
        },
        zh = {
            TPF2_MCP_NAME = "tpf2mcp",
            TPF2_MCP_DESCRIPTION = [[用于将 Transport Fever 2 连接到外部 MCP 客户端，需要 Python 3.11 或更高版本。

所有路径均相对于本 Mod 安装根目录。用户自行准备 Python 环境，依赖清单为 mcp_server/requirements.txt。

然后执行：
python mcp_server/start_http_server.py

MCP 连接地址为 http://127.0.0.1:8766/mcp。stdio MCP 使用 python mcp_server/start_server.py。
调度命令与回执写入 logs/dispatch/，服务异常写入 logs/mcp/；全量工具调用和 HTTP 访问日志暂时关闭。状态和缓存写入 var/。详见 docs/usage/deployment.md。

Web API：在同一目录执行：
python mcp_server/start_api.py
另开终端，在同一个 Mod 根目录执行 npm --prefix ui/rail-map install 和 npm --prefix ui/rail-map run dev，然后打开 http://127.0.0.1:5173/?view=network。发布包默认只读。]],
        },
    }
end
