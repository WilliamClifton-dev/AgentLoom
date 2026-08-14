import json
from pathlib import Path

from agentloom.skill_catalog import load_skill_catalog, load_skill_provider


def test_upstream_catalog_is_pinned_and_schema_complete() -> None:
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
        assert manifest.source is not None
        assert manifest.source.commit == "7829ffd90d973b6325f5f12f1b1226dcace74443"
        assert manifest.source.license == "MIT"
        assert manifest.source.content_hash.startswith("sha256:")
        assert manifest.compatible_agents
        assert manifest.allowed_tools
        assert manifest.allowed_paths is not None
        assert manifest.risk_level is not None
        for schema_path in (manifest.input_schema, manifest.output_schema):
            resolved_schema = repository_root / schema_path
            schema = json.loads(resolved_schema.read_text(encoding="utf-8"))
            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["additionalProperties"] is False

    published = next(
        manifest for manifest in catalog.skills if manifest.name == "code-review-and-quality"
    )
    assert published.lifecycle_state == "PUBLISHED"
    assert published.risk_level == "L1"
    assert published.evaluation is not None
    assert "tests.execute" in published.permissions
    assert "test-runner:process.exec:test" in (published.allowed_tools or [])
    assert {
        manifest.name
        for manifest in catalog.skills
        if manifest.lifecycle_state == "QUARANTINED"
    } == {
        "debugging-and-error-recovery",
        "test-driven-development",
        "security-and-hardening",
        "using-agent-skills",
    }


def test_published_verifier_skill_has_matching_evaluation_record() -> None:
    repository_root = Path(__file__).parents[1]
    catalog = load_skill_catalog(repository_root / "skills" / "catalog.json")
    manifest = next(
        skill for skill in catalog.skills if skill.name == "code-review-and-quality"
    )
    report_path = (
        repository_root
        / "provenance"
        / "evaluations"
        / "code-review-and-quality-0.0.0-upstream.7829ffd.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert manifest.source is not None
    assert manifest.evaluation is not None
    assert report["skillVersion"] == manifest.version
    assert report["sourceContentHash"] == manifest.source.content_hash
    assert report["verdict"] == "PUBLISHED"
    assert {
        check["evidenceRef"] for check in report["checks"] if check["result"] == "PASSED"
    } == set(manifest.evaluation.agentloom_bench_evidence_refs)


def test_load_skill_provider_uses_the_validated_catalog() -> None:
    repository_root = Path(__file__).parents[1]

    provider = load_skill_provider(repository_root / "skills" / "catalog.json")

    assert provider.provider_id == "local-catalog"
