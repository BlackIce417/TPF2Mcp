"""Discovery metadata for the file-backed dispatch skill."""

DISPATCH_RULES_TOOL = {
    "name": "get_dispatch_rules",
    "title": "获取调度规则",
    "description": (
        "调度前读取项目随附的 skill 提示词与规则。返回 skills/tpf2-dispatch/ 下的 "
        "SKILL.md 和 references/*.md 的相对路径及完整内容；每次调用读取最新文件，"
        "无需连接游戏。规则为决策指导，工具自身的权限和参数校验仍然有效。"
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "outputSchema": {
        "type": "object",
        "required": ["skill_directory", "entrypoint", "documents"],
        "properties": {
            "skill_directory": {"type": "string"},
            "entrypoint": {"type": "string"},
            "documents": {"type": "array", "items": {
                "type": "object", "required": ["path", "content"],
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            }},
        },
    },
}
