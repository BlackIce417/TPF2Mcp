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

Web API: in the same directory run:
python start_api.py
In another terminal, enter ui/rail-map, run npm install and npm run dev, then open http://127.0.0.1:5173/?view=network. Keep both terminals open. The published package is read-only by default.]],
        },
        zh = {
            TPF2_MCP_NAME = "tpf2mcp",
            TPF2_MCP_DESCRIPTION = [[用于将 Transport Fever 2 连接到外部 MCP 客户端，需要 Python 3.11 或更高版本。

启动方法：打开终端，切换到本 Mod 安装目录下的 mcp_server 文件夹。首次使用请执行：
python -m pip install -r requirements.txt

然后执行：
python start_server.py

这是 stdio MCP 服务；请在 MCP 客户端中配置相同的工作目录和命令。

Web API：在同一目录执行：
python start_api.py
另开终端进入 ui/rail-map，执行 npm install 和 npm run dev，然后用浏览器打开 http://127.0.0.1:5173/?view=network。使用期间请保持两个终端运行。发布包默认只读。]],
        },
    }
end
