"""Load the versioned upstream Skill catalog through strict contracts."""

from pathlib import Path

from agentloom.capabilities import CatalogSkillProvider
from agentloom.contracts import SkillCatalog


def load_skill_catalog(path: Path) -> SkillCatalog:
    return SkillCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def load_skill_provider(path: Path) -> CatalogSkillProvider:
    """Load a validated local catalog and expose it through the SkillProvider contract."""
    return CatalogSkillProvider(load_skill_catalog(path))
