"""Load the versioned upstream Skill catalog through strict contracts."""

from hashlib import sha256
from pathlib import Path

from agentloom.capabilities import CatalogSkillProvider
from agentloom.contracts import SkillCatalog


def canonical_skill_source_digest(encoded: bytes) -> str:
    """Hash Skill source bytes after Git-compatible LF normalization."""

    canonical = encoded.replace(b"\r\n", b"\n")
    return f"sha256:{sha256(canonical).hexdigest()}"


def load_skill_catalog(path: Path) -> SkillCatalog:
    return SkillCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def load_skill_provider(path: Path) -> CatalogSkillProvider:
    """Load a validated local catalog and expose it through the SkillProvider contract."""
    return CatalogSkillProvider(load_skill_catalog(path))
