from agentloom.dev_dispatcher.models import DevelopmentTask
from agentloom.dev_dispatcher.router import route_task


def task(**overrides: object) -> DevelopmentTask:
    values: dict[str, object] = {
        "id": "TASK-001",
        "title": "Implement task API",
        "objective": "Add a normal internal API with tests.",
        "acceptance_commands": ["python -m pytest"],
    }
    values.update(overrides)
    return DevelopmentTask.model_validate(values)


def test_routes_mechanical_work_to_luna_low() -> None:
    decision = route_task(task(kind="mechanical"))
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-luna", "low")


def test_routes_normal_implementation_to_terra_medium() -> None:
    decision = route_task(task())
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-terra", "medium")


def test_security_override_routes_to_sol_high() -> None:
    decision = route_task(task(risk_tags=["credentials"], kind="mechanical"))
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-sol", "high")


def test_luna_failure_escalates_to_terra() -> None:
    decision = route_task(task(kind="mechanical", attempts=1))
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-terra", "medium")


def test_two_terra_failures_escalate_to_sol() -> None:
    decision = route_task(task(attempts=2))
    assert (decision.model, decision.reasoning_effort) == ("gpt-5.6-sol", "high")
