from datetime import UTC, datetime
from pathlib import Path

from agentloom.contracts import (
    ToolCallEventRecord,
    ToolExecutionRequest,
    ToolExecutionResult,
    tool_parameter_digest,
)
from agentloom.storage import Database, TaskEventIntegrityError


def tool_request() -> ToolExecutionRequest:
    return ToolExecutionRequest(
        task_id="task-01",
        step_id="step-01",
        agent_name="agentloom-implementer",
        skill_name="test-driven-development",
        skill_version="1.0.0",
        tool_name="test-runner",
        action="process.exec:test",
        parameter_digest=tool_parameter_digest({}),
    )


def tool_result() -> ToolExecutionResult:
    return ToolExecutionResult(
        status="SUCCEEDED",
        evidence_refs=["ev-tool"],
        output_digest="b" * 64,
    )


def tool_event() -> ToolCallEventRecord:
    return ToolCallEventRecord.from_execution(
        event_id="tool-event-01",
        request=tool_request(),
        result=tool_result(),
        provider_id="local-tool",
        grant_id="grant-01",
        actor="agentloom-implementer",
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
    )


def test_tool_call_event_digest_covers_request_and_result() -> None:
    event = tool_event()

    assert event.schema_version == "agentloom.tool-call/v1alpha1"
    assert event.event_type == "TOOL_CALL"
    assert event.correlation_id == "task-01"
    assert event.has_valid_payload_digest()
    assert not event.model_copy(update={"status": "FAILED"}).has_valid_payload_digest()


def test_database_appends_and_replays_tool_call_events(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'events.db'}")
    database.create_schema()

    database.record_tool_call(tool_event())

    events = database.list_tool_calls("task-01")
    assert events == [tool_event()]


def test_database_rejects_tampered_tool_call_event(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'events.db'}")
    database.create_schema()
    database.record_tool_call(tool_event())

    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE tool_calls SET status = 'FAILED' WHERE event_id = 'tool-event-01'"
        )

    try:
        database.list_tool_calls("task-01")
    except TaskEventIntegrityError as error:
        assert "tool call payload digest is invalid" in str(error)
    else:
        raise AssertionError("tampered tool call event was accepted")
