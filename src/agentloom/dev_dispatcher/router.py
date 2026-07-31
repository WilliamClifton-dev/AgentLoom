"""Deterministic model selection for development tasks."""

from agentloom.dev_dispatcher.models import DevelopmentTask, RouteDecision

HIGH_RISK_TAGS = frozenset(
    {
        "architecture",
        "authorization",
        "competition-compliance",
        "credentials",
        "destructive",
        "external-write",
        "identity",
        "irreversible",
        "migration",
        "payment",
        "publication",
        "security",
        "supply-chain",
    }
)


def route_task(task: DevelopmentTask) -> RouteDecision:
    """Apply safety overrides before cost-sensitive routing."""
    risky = sorted(set(task.risk_tags) & HIGH_RISK_TAGS)
    if risky:
        return RouteDecision(
            model="gpt-5.6-sol",
            reasoning_effort="high",
            reason=f"High-risk override: {', '.join(risky)}.",
        )
    if task.kind in {"architecture", "review"} or task.attempts >= 2:
        return RouteDecision(
            model="gpt-5.6-sol",
            reasoning_effort="high",
            reason="Architecture/review work or two failed Terra attempts requires Sol.",
        )
    if task.kind == "mechanical" and task.attempts == 0:
        return RouteDecision(
            model="gpt-5.6-luna",
            reasoning_effort="low",
            reason="Low-risk mechanical work with deterministic acceptance checks.",
        )
    return RouteDecision(
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        reason="Default engineering route or escalation from Luna.",
    )
