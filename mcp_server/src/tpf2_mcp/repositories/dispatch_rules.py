"""Read the dispatch skill relative to the source or packaged Mod root."""
from pathlib import Path
from tpf2_mcp.common.paths import runtime_root


SKILL_DIRECTORY = Path("skills/tpf2-dispatch")


class DispatchRulesError(RuntimeError):
    pass


def get_dispatch_rules(root: Path | None = None) -> dict:
    root = (root if root is not None else runtime_root()).resolve()
    directory = root / SKILL_DIRECTORY
    entrypoint = directory / "SKILL.md"
    try:
        files = [entrypoint, *sorted((directory / "references").rglob("*.md"))]
        documents = []
        for file in files:
            # Do not follow a link outside the packaged skill directory.
            if not file.resolve().is_relative_to(directory.resolve()):
                raise DispatchRulesError("DISPATCH_RULES_INVALID: reference leaves skill directory")
            if not file.resolve().is_relative_to(root):
                raise DispatchRulesError("DISPATCH_RULES_INVALID: skill leaves project root")
            documents.append({"path": file.relative_to(root).as_posix(),
                              "content": file.read_text(encoding="utf-8-sig")})
    except (OSError, UnicodeError) as exc:
        raise DispatchRulesError("DISPATCH_RULES_UNAVAILABLE: cannot read skills/tpf2-dispatch") from exc
    return {"skill_directory": SKILL_DIRECTORY.as_posix(),
            "entrypoint": (SKILL_DIRECTORY / "SKILL.md").as_posix(),
            "documents": documents}
