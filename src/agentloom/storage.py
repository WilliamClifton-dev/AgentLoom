"""SQLite-backed metadata storage for the initial single-node deployment."""

from datetime import UTC, datetime
from math import ceil
from uuid import uuid4

from sqlalchemy import JSON, DateTime, String, Text, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from agentloom.contracts import Pagination, TaskCreate, TaskPage, TaskRecord


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
            status="RECEIVED",
            created_at=created_at,
        )
