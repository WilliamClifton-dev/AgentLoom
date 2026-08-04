"""Deterministic coordinator for the bounded software-repair lifecycle."""

from agentloom.contracts import (
    TaskRecord,
    TaskStatus,
    TaskTransition,
    WorkflowCompletionOutcome,
    WorkflowVerificationOutcome,
)
from agentloom.storage import Database


class TaskNotFound(Exception):
    """Raised when a workflow operation targets an unknown task."""


class RepairWorkflow:
    """Drive one repair task through explicit, evidence-producing stages."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def start(self, task_id: str) -> TaskRecord:
        self._move(task_id, "PLANNED", "Coordinator produced the repair plan.")
        return self._move(
            task_id,
            "INVESTIGATING",
            "Investigator started evidence collection.",
        )

    def record_investigation(self, task_id: str, *, sufficient: bool) -> TaskRecord:
        status: TaskStatus = "IMPLEMENTING" if sufficient else "BLOCKED"
        reason = (
            "Investigation reached the evidence threshold."
            if sufficient
            else "Investigation lacks sufficient evidence to implement safely."
        )
        return self._move(task_id, status, reason)

    def resume_investigation(self, task_id: str) -> TaskRecord:
        return self._move(
            task_id,
            "INVESTIGATING",
            "Investigator resumed after input was supplied.",
        )

    def record_implementation(
        self, task_id: str, *, requires_approval: bool
    ) -> TaskRecord:
        status: TaskStatus = "AWAITING_APPROVAL" if requires_approval else "VERIFYING"
        reason = (
            "Implementation requires explicit human approval."
            if requires_approval
            else "Implementer produced a frozen patch for independent verification."
        )
        return self._move(task_id, status, reason)

    def record_approval(self, task_id: str, *, approved: bool) -> TaskRecord:
        status: TaskStatus = "IMPLEMENTING" if approved else "LEARNING"
        reason = (
            "Human approved the implementation."
            if approved
            else "Human rejected the implementation."
        )
        return self._move(task_id, status, reason)

    def record_verification(
        self,
        task_id: str,
        *,
        outcome: WorkflowVerificationOutcome,
    ) -> TaskRecord:
        if outcome == "PASSED":
            return self._move(task_id, "LEARNING", "Independent verification passed.")
        return self._move(
            task_id,
            "ROLLING_BACK",
            f"Independent verification returned {outcome}; rollback is required.",
        )

    def rollback(self, task_id: str, *, retry: bool) -> TaskRecord:
        self._move(
            task_id,
            "ROLLED_BACK",
            "Implementer workspace was restored to the clean snapshot.",
        )
        status: TaskStatus = "IMPLEMENTING" if retry else "LEARNING"
        reason = (
            "Rollback completed; retry budget permits another implementation attempt."
            if retry
            else "Rollback completed; no further implementation attempt is permitted."
        )
        return self._move(task_id, status, reason)

    def finish(
        self, task_id: str, *, outcome: WorkflowCompletionOutcome
    ) -> TaskRecord:
        status: TaskStatus = "COMPLETED" if outcome == "PASSED" else outcome
        return self._move(task_id, status, "Learning record finalized.")

    def _move(self, task_id: str, status: TaskStatus, reason: str) -> TaskRecord:
        task = self.database.get_task(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        updated = self.database.transition_task(
            task_id,
            TaskTransition(
                expected_plan_version=task.plan_version,
                status=status,
                reason=reason,
            ),
        )
        if updated is None:
            raise TaskNotFound(task_id)
        return updated
