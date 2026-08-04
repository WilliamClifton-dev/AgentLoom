"""SQLite-backed metadata storage for the initial single-node deployment."""

from datetime import UTC, datetime
from math import ceil
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from agentloom.contracts import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalRecord,
    ApprovalStatus,
    EscalatedRiskLevel,
    Pagination,
    TaskCreate,
    TaskEventRecord,
    TaskPage,
    TaskRecord,
    TaskStatus,
    TaskTransition,
)

VALID_TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    "RECEIVED": frozenset({"PLANNED", "BLOCKED_PLATFORM"}),
    "PLANNED": frozenset({"INVESTIGATING", "BLOCKED_PLATFORM"}),
    "INVESTIGATING": frozenset({"BLOCKED", "IMPLEMENTING", "BLOCKED_PLATFORM"}),
    "BLOCKED": frozenset({"INVESTIGATING", "BLOCKED_PLATFORM"}),
    "IMPLEMENTING": frozenset(
        {"AWAITING_APPROVAL", "VERIFYING", "BLOCKED_PLATFORM"}
    ),
    "AWAITING_APPROVAL": frozenset(
        {"IMPLEMENTING", "LEARNING", "BLOCKED_PLATFORM"}
    ),
    "VERIFYING": frozenset(
        {"IMPLEMENTING", "ROLLING_BACK", "LEARNING", "BLOCKED_PLATFORM"}
    ),
    "ROLLING_BACK": frozenset({"ROLLED_BACK", "BLOCKED_PLATFORM"}),
    "ROLLED_BACK": frozenset({"IMPLEMENTING", "LEARNING", "BLOCKED_PLATFORM"}),
    "LEARNING": frozenset({"COMPLETED", "FAILED", "CANCELLED"}),
    "COMPLETED": frozenset(),
    "FAILED": frozenset(),
    "CANCELLED": frozenset(),
    "BLOCKED_PLATFORM": frozenset({"PLANNED"}),
}


class VersionConflict(Exception):
    def __init__(self, current_plan_version: int) -> None:
        self.current_plan_version = current_plan_version
        super().__init__("task plan version is stale")


class InvalidStateTransition(Exception):
    def __init__(self, current_status: TaskStatus, requested_status: TaskStatus) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(f"cannot transition from {current_status} to {requested_status}")


class ApprovalVersionConflict(Exception):
    """Raised when an approval decision does not match the current version."""


class ApprovalTaskNotFound(Exception):
    """Raised when an approval cannot be attached to an existing task."""


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    repository_uri: Mapped[str] = mapped_column(Text)
    issue: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON)
    allowed_paths: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="RECEIVED")
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskEventRow(Base):
    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "plan_version"),)

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    from_status: Mapped[str] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    plan_version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.task_id"), index=True)
    grant_id: Mapped[str] = mapped_column(String(64), index=True)
    parameter_digest: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(2))
    route_id: Mapped[str] = mapped_column(String(200))
    rollback_plan_hash: Mapped[str] = mapped_column(String(64))
    action_summary: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    approval_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def create_task(self, request: TaskCreate) -> TaskRecord:
        row = TaskRow(
            task_id=f"task-{uuid4().hex}",
            title=request.title,
            repository_uri=request.repository_uri,
            issue=request.issue,
            acceptance_criteria=request.acceptance_criteria,
            allowed_paths=request.allowed_paths,
            status="RECEIVED",
            plan_version=0,
            created_at=datetime.now(UTC),
        )
        with self._sessions.begin() as session:
            session.add(row)
        return self._to_record(row)

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._sessions() as session:
            row = session.get(TaskRow, task_id)
            return self._to_record(row) if row else None

    def list_tasks(self, *, page: int, page_size: int) -> TaskPage:
        with self._sessions() as session:
            total_items = session.scalar(select(func.count()).select_from(TaskRow)) or 0
            rows = session.scalars(
                select(TaskRow)
                .order_by(TaskRow.created_at.desc(), TaskRow.task_id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            ).all()
        return TaskPage(
            data=[self._to_record(row) for row in rows],
            pagination=Pagination(
                page=page,
                page_size=page_size,
                total_items=total_items,
                total_pages=ceil(total_items / page_size) if total_items else 0,
            ),
        )

    def transition_task(self, task_id: str, transition: TaskTransition) -> TaskRecord | None:
        with self._sessions.begin() as session:
            row = session.get(TaskRow, task_id)
            if row is None:
                return None
            current_status = cast(TaskStatus, row.status)
            if row.plan_version != transition.expected_plan_version:
                raise VersionConflict(row.plan_version)
            if transition.status not in VALID_TASK_TRANSITIONS[current_status]:
                raise InvalidStateTransition(current_status, transition.status)

            result = cast(
                CursorResult[Any],
                session.execute(
                    update(TaskRow)
                    .where(
                        TaskRow.task_id == task_id,
                        TaskRow.plan_version == transition.expected_plan_version,
                    )
                    .values(
                        status=transition.status,
                        plan_version=transition.expected_plan_version + 1,
                    )
                ),
            )
            if result.rowcount != 1:
                session.expire_all()
                current = session.get(TaskRow, task_id)
                raise VersionConflict(current.plan_version if current else 0)
            session.add(
                TaskEventRow(
                    event_id=f"event-{uuid4().hex}",
                    task_id=task_id,
                    from_status=current_status,
                    to_status=transition.status,
                    plan_version=transition.expected_plan_version + 1,
                    reason=transition.reason,
                    created_at=datetime.now(UTC),
                )
            )
            session.expire_all()
            updated = session.get(TaskRow, task_id)
            if updated is None:
                return None
            return self._to_record(updated)

    def list_task_events(self, task_id: str) -> list[TaskEventRecord]:
        with self._sessions() as session:
            rows = session.scalars(
                select(TaskEventRow)
                .where(TaskEventRow.task_id == task_id)
                .order_by(TaskEventRow.plan_version)
            ).all()
        return [self._to_event_record(row) for row in rows]

    def create_approval(self, request: ApprovalCreate) -> ApprovalRecord:
        now = datetime.now(UTC)
        record = ApprovalRecord(
            approval_id=f"approval-{uuid4().hex}",
            task_id=request.task_id,
            grant_id=request.grant_id,
            parameter_digest=request.parameter_digest,
            risk_level=request.risk_level,
            route_id=request.route_id,
            rollback_plan_hash=request.rollback_plan_hash,
            action_summary=request.action_summary,
            requested_by=request.requested_by,
            expires_at=request.expires_at,
            created_at=now,
        )
        row = ApprovalRow(
            approval_id=record.approval_id,
            task_id=record.task_id,
            grant_id=record.grant_id,
            parameter_digest=record.parameter_digest,
            risk_level=record.risk_level,
            route_id=record.route_id,
            rollback_plan_hash=record.rollback_plan_hash,
            action_summary=record.action_summary,
            requested_by=record.requested_by,
            expires_at=record.expires_at,
            status=record.status,
            approval_version=record.approval_version,
            created_at=record.created_at,
        )
        with self._sessions.begin() as session:
            if session.get(TaskRow, record.task_id) is None:
                raise ApprovalTaskNotFound("approval task does not exist")
            session.add(row)
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._sessions() as session:
            row = session.get(ApprovalRow, approval_id)
            return self._to_approval_record(row) if row else None

    def decide_approval(
        self,
        approval_id: str,
        decision: ApprovalDecisionRequest,
    ) -> ApprovalRecord | None:
        with self._sessions.begin() as session:
            row = session.get(ApprovalRow, approval_id)
            if row is None:
                return None
            if row.approval_version != decision.expected_approval_version:
                raise ApprovalVersionConflict("approval version is stale")
            if row.status != "PENDING":
                raise ApprovalVersionConflict("approval is no longer pending")
            now = datetime.now(UTC)
            if now >= _as_utc(row.expires_at):
                row.status = "EXPIRED"
                row.approval_version += 1
            else:
                row.status = decision.status
                row.approval_version += 1
                row.decided_by = decision.actor
                row.decision_reason = decision.reason
                row.decided_at = now
            session.flush()
            return self._to_approval_record(row)

    @staticmethod
    def _to_record(row: TaskRow) -> TaskRecord:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return TaskRecord(
            task_id=row.task_id,
            title=row.title,
            repository_uri=row.repository_uri,
            issue=row.issue,
            acceptance_criteria=row.acceptance_criteria,
            allowed_paths=row.allowed_paths,
            status=cast(TaskStatus, row.status),
            plan_version=row.plan_version,
            created_at=created_at,
        )

    @staticmethod
    def _to_event_record(row: TaskEventRow) -> TaskEventRecord:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return TaskEventRecord(
            event_id=row.event_id,
            task_id=row.task_id,
            from_status=cast(TaskStatus, row.from_status),
            to_status=cast(TaskStatus, row.to_status),
            plan_version=row.plan_version,
            reason=row.reason,
            created_at=created_at,
        )

    @staticmethod
    def _to_approval_record(row: ApprovalRow) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row.approval_id,
            task_id=row.task_id,
            grant_id=row.grant_id,
            parameter_digest=row.parameter_digest,
            risk_level=cast(EscalatedRiskLevel, row.risk_level),
            route_id=row.route_id,
            rollback_plan_hash=row.rollback_plan_hash,
            action_summary=row.action_summary,
            requested_by=row.requested_by,
            expires_at=_as_utc(row.expires_at),
            status=cast(ApprovalStatus, row.status),
            approval_version=row.approval_version,
            created_at=_as_utc(row.created_at),
            decided_by=row.decided_by,
            decision_reason=row.decision_reason,
            decided_at=_as_utc(row.decided_at) if row.decided_at else None,
        )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
