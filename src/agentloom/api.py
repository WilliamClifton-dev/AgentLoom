"""FastAPI control-plane entry point."""

from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from agentloom.contracts import TaskCreate, TaskPage, TaskRecord
from agentloom.storage import Database


def create_app(database: Database) -> FastAPI:
    app = FastAPI(title="AgentLoom API", version="0.1.0")

    @app.post("/api/tasks", response_model=TaskRecord, status_code=201)
    def create_task(request: TaskCreate) -> TaskRecord:
        return database.create_task(request)

    @app.get("/api/tasks", response_model=TaskPage)
    def list_tasks(
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    ) -> TaskPage:
        return database.list_tasks(page=page, page_size=page_size)

    @app.get("/api/tasks/{task_id}", response_model=TaskRecord)
    def get_task(task_id: str) -> TaskRecord | JSONResponse:
        task = database.get_task(task_id)
        if task is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "TASK_NOT_FOUND",
                        "message": f"Task '{task_id}' was not found.",
                        "details": {"taskId": task_id},
                    }
                },
            )
        return task

    return app
