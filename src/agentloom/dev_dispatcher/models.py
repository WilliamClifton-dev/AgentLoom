"""Strict contracts for the development dispatcher."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ModelId = Literal["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
ReasoningEffort = Literal["low", "medium", "high"]
TaskKind = Literal["mechanical", "implementation", "architecture", "review"]
TaskStatus = Literal["pending", "running", "completed", "failed", "blocked"]


class DispatcherModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DevelopmentTask(DispatcherModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_-]{2,63}$")
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=4000)
    kind: TaskKind = "implementation"
    priority: int = Field(default=100, ge=0, le=1000)
    dependencies: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    acceptance_commands: list[str] = Field(min_length=1, max_length=10)
    allowed_paths: list[str] = Field(default_factory=list)
    status: TaskStatus = "pending"
    attempts: int = Field(default=0, ge=0, le=3)
    last_error: str | None = Field(default=None, max_length=1000)
    selected_model: ModelId | None = None
    reasoning_effort: ReasoningEffort | None = None

    @field_validator("risk_tags")
    @classmethod
    def normalize_risk_tags(cls, value: list[str]) -> list[str]:
        return [item.casefold() for item in value]


class DevelopmentBacklog(DispatcherModel):
    schema_version: Literal[1] = 1
    tasks: list[DevelopmentTask] = Field(default_factory=list)


class RouteDecision(DispatcherModel):
    model: ModelId
    reasoning_effort: ReasoningEffort
    reason: str = Field(min_length=1, max_length=500)


class ExecutionResult(DispatcherModel):
    return_code: int
    final_message: str = Field(max_length=20_000)
    output_file: str
