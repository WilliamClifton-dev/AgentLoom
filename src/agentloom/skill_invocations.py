"""Create-only persistence for immutable Skill invocation closure evidence."""

from pathlib import Path

from agentloom.contracts import SkillInvocationEvidenceRecord


class ImmutableSkillInvocationWriter:
    """Persist one validated invocation without overwriting prior evidence."""

    def __init__(self, evidence_root: Path) -> None:
        self._evidence_root = evidence_root.resolve()

    def __call__(
        self,
        record: SkillInvocationEvidenceRecord,
    ) -> SkillInvocationEvidenceRecord:
        if not record.has_valid_payload_digest():
            raise ValueError("Skill invocation payload digest is invalid")
        self._evidence_root.mkdir(parents=True, exist_ok=True)
        file_name = f"{record.invocation_id}.json"
        output_path = self._evidence_root / file_name
        if output_path.parent != self._evidence_root or output_path.name != file_name:
            raise ValueError("Skill invocation ID is not a safe evidence filename")
        encoded = (
            record.model_dump_json(by_alias=True, indent=2) + "\n"
        ).encode("utf-8")
        with output_path.open("xb") as stream:
            stream.write(encoded)
        return record
