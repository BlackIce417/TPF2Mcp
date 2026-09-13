function data()
    return {
        info = {
            minorVersion = 0,
            severityAdd = "NONE",
            severityRemove = "NONE",
            name = _("TPF2_MCP_NAME"),
            description = _("TPF2_MCP_DESCRIPTION"),
            tags = { "Script Mod", "MCP" },
            authors = { { name = "BlackIce", role = "CREATOR" } },
        },
        runFn = function(settings)
            print("[tpf2-mcp][INFO] mod configuration loaded")
        end,
    }
end
