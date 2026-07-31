"""Atomic JSON task ledger and dependency selection."""

import os
from pathlib import Path

from agentloom.dev_dispatcher.models import DevelopmentBacklog, DevelopmentTask, TaskStatus


class BacklogStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()

    def load(self) -> DevelopmentBacklog:
        return DevelopmentBacklog.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(self, backlog: DevelopmentBacklog) -> None:
        self._validate_dependencies(backlog)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = backlog.model_dump_json(indent=2) + "\n"
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self.path)
        finally:
            temp_path.unlink(missing_ok=True)

    def next_ready(self) -> DevelopmentTask:
        backlog = self.load()
        completed = {task.id for task in backlog.tasks if task.status == "completed"}
        ready = [
            task
            for task in backlog.tasks
            if task.status in {"pending", "failed"}
            and task.attempts < 3
            and set(task.dependencies) <= completed
        ]
        if not ready:
            raise LookupError("No ready development task")
        return min(ready, key=lambda task: (task.priority, task.id))

    def transition(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        error: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        increment_attempts: bool = False,
    ) -> DevelopmentTask:
        backlog = self.load()
        for index, task in enumerate(backlog.tasks):
            if task.id != task_id:
                continue
            updates: dict[str, object] = {"status": status, "last_error": error}
            if model is not None:
                updates["selected_model"] = model
            if effort is not None:
                updates["reasoning_effort"] = effort
            if increment_attempts:
                updates["attempts"] = task.attempts + 1
            changed = task.model_copy(update=updates)
            backlog.tasks[index] = changed
            self.save(backlog)
            return changed
        raise KeyError(f"Unknown task: {task_id}")

    def recover_interrupted(self) -> list[str]:
        backlog = self.load()
        recovered: list[str] = []
        for index, task in enumerate(backlog.tasks):
            if task.status != "running":
                continue
            attempts = task.attempts + 1
            backlog.tasks[index] = task.model_copy(
                update={
                    "status": "blocked" if attempts >= 3 else "failed",
                    "attempts": attempts,
                    "last_error": "Previous dispatcher process ended before completion.",
                }
            )
            recovered.append(task.id)
        if recovered:
            self.save(backlog)
        return recovered

    @staticmethod
    def _validate_dependencies(backlog: DevelopmentBacklog) -> None:
        ids = [task.id for task in backlog.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task id")
        known = set(ids)
        for task in backlog.tasks:
            unknown = set(task.dependencies) - known
            if unknown:
                raise ValueError(f"unknown dependency for {task.id}: {sorted(unknown)}")
            if task.id in task.dependencies:
                raise ValueError(f"task cannot depend on itself: {task.id}")
