"""Load the versioned upstream Skill catalog through strict contracts."""

from pathlib import Path

from agentloom.contracts import SkillCatalog


def load_skill_catalog(path: Path) -> SkillCatalog:
    return SkillCatalog.model_validate_json(path.read_text(encoding="utf-8"))
