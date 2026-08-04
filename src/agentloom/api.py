"""FastAPI control-plane entry point."""

from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from agentloom.contracts import (
    ApprovalCreate,
    ApprovalDecisionRequest,
    ApprovalRecord,
    GrantVerificationRequest,
    SkillExecutionGrant,
    TaskCreate,
    TaskPage,
    TaskRecord,
    TaskTransition,
)
from agentloom.policy import PolicyDenied, SkillGrantAuthorizer
from agentloom.storage import (
    ApprovalTaskNotFound,
    ApprovalVersionConflict,
    Database,
    InvalidStateTransition,
    VersionConflict,
)


def create_app(
    database: Database,
    grant_authorizer: SkillGrantAuthorizer | None = None,
) -> FastAPI:
    app = FastAPI(title="AgentLoom API", version="0.1.0")

    @app.post("/api/tasks", response_model=TaskRecord, status_code=201)
    def create_task(request: TaskCreate) -> TaskRecord:
        return database.create_task(request)

    @app.post("/internal/approvals", response_model=ApprovalRecord, status_code=201)
    def create_approval(request: ApprovalCreate) -> ApprovalRecord | JSONResponse:
        try:
            return database.create_approval(request)
        except ApprovalTaskNotFound:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "APPROVAL_TASK_NOT_FOUND",
                        "message": "The approval task was not found.",
                        "details": {"taskId": request.task_id},
                    }
                },
            )

    @app.get("/internal/approvals/{approval_id}", response_model=ApprovalRecord)
    def get_approval(approval_id: str) -> ApprovalRecord | JSONResponse:
        approval = database.get_approval(approval_id)
        if approval is None:
            return _approval_not_found(approval_id)
        return approval

    @app.post(
        "/internal/approvals/{approval_id}/decisions",
        response_model=ApprovalRecord,
    )
    def decide_approval(
        approval_id: str,
        request: ApprovalDecisionRequest,
    ) -> ApprovalRecord | JSONResponse:
        try:
            approval = database.decide_approval(approval_id, request)
        except ApprovalVersionConflict:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "APPROVAL_VERSION_CONFLICT",
                        "message": "Approval is no longer pending at the requested version.",
                        "details": {"approvalId": approval_id},
                    }
                },
            )
        if approval is None:
            return _approval_not_found(approval_id)
        if approval.status == "EXPIRED":
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "APPROVAL_EXPIRED",
                        "message": "Approval expired before a decision could be recorded.",
                        "details": {"approvalId": approval_id},
                    }
                },
            )
        return approval

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

    @app.post("/internal/tasks/{task_id}/transitions", response_model=TaskRecord)
    def transition_task(
        task_id: str,
        request: TaskTransition,
    ) -> TaskRecord | JSONResponse:
        try:
            task = database.transition_task(task_id, request)
        except VersionConflict as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "VERSION_CONFLICT",
                        "message": "Task plan version is stale.",
                        "details": {"currentPlanVersion": exc.current_plan_version},
                    }
                },
            )
        except InvalidStateTransition as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "INVALID_STATE_TRANSITION",
                        "message": str(exc),
                        "details": {
                            "currentStatus": exc.current_status,
                            "requestedStatus": exc.requested_status,
                        },
                    }
                },
            )
        if task is None:
            return _task_not_found(task_id)
        return task

    @app.post(
        "/internal/policy/grants/verify",
        response_model=SkillExecutionGrant,
    )
    def verify_grant(
        request: GrantVerificationRequest,
    ) -> SkillExecutionGrant | JSONResponse:
        if grant_authorizer is None:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "POLICY_BROKER_UNAVAILABLE",
                        "message": "Policy Broker is not configured.",
                        "details": {},
                    }
                },
            )
        try:
            return grant_authorizer.verify(
                request.signed_grant,
                parameter_digest=request.parameter_digest,
            )
        except PolicyDenied as exc:
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": {},
                    }
                },
            )

    return app


def _task_not_found(task_id: str) -> JSONResponse:
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


def _approval_not_found(approval_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "APPROVAL_NOT_FOUND",
                "message": f"Approval '{approval_id}' was not found.",
                "details": {"approvalId": approval_id},
            }
        },
    )
