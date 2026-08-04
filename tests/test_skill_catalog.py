import json
from pathlib import Path

from agentloom.skill_catalog import load_skill_catalog


def test_quarantined_upstream_catalog_is_pinned_and_schema_complete() -> None:
    repository_root = Path(__file__).parents[1]
    catalog = load_skill_catalog(repository_root / "skills" / "catalog.json")

    assert {manifest.name for manifest in catalog.skills} == {
        "debugging-and-error-recovery",
        "test-driven-development",
        "code-review-and-quality",
        "security-and-hardening",
        "using-agent-skills",
    }
    for manifest in catalog.skills:
        assert manifest.lifecycle_state == "QUARANTINED"
        assert manifest.source is not None
        assert manifest.source.commit == "7829ffd90d973b6325f5f12f1b1226dcace74443"
        assert manifest.source.license == "MIT"
        assert manifest.source.content_hash.startswith("sha256:")
        assert manifest.compatible_agents
        assert manifest.allowed_tools
        assert manifest.allowed_paths is not None
        assert manifest.risk_level is not None
        assert manifest.evaluation is None
        for schema_path in (manifest.input_schema, manifest.output_schema):
            resolved_schema = repository_root / schema_path
            schema = json.loads(resolved_schema.read_text(encoding="utf-8"))
            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["additionalProperties"] is False
