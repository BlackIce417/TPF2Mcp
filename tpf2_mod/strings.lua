function data()
    return {
        en = {
            TPF2_MCP_NAME = "tpf2mcp",
            TPF2_MCP_DESCRIPTION = [[Connects Transport Fever 2 to an external MCP client. Python 3.11 or newer is required.

Startup: open a terminal in this Mod's mcp_server directory. On first use run:
python -m pip install -r requirements.txt

Then run:
python start_server.py

This is a stdio MCP server. Configure the same directory and command in your MCP client.

Web UI: in the same directory run:
python start_ui.py
Then open http://127.0.0.1:8765/?view=network in a browser. Keep this terminal open while using the UI. The published package is read-only by default.]],
        },
        zh = {
            TPF2_MCP_NAME = "tpf2mcp",
            TPF2_MCP_DESCRIPTION = [[用于将 Transport Fever 2 连接到外部 MCP 客户端，需要 Python 3.11 或更高版本。

启动方法：打开终端，切换到本 Mod 安装目录下的 mcp_server 文件夹。首次使用请执行：
python -m pip install -r requirements.txt

然后执行：
python start_server.py

这是 stdio MCP 服务；请在 MCP 客户端中配置相同的工作目录和命令。

查看前端：在同一目录执行：
python start_ui.py
然后用浏览器打开 http://127.0.0.1:8765/?view=network。使用前端期间请保持该终端运行。发布包默认只读。]],
        },
    }
end
