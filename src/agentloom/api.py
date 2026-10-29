"""FastAPI control-plane entry point."""

import os
from hmac import compare_digest
from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

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

_INTERNAL_AUTH_ERROR = {
    "error": {
        "code": "INTERNAL_AUTHENTICATION_REQUIRED",
        "message": "A valid internal API bearer token is required.",
        "details": {},
    }
}

INTERNAL_API_TOKEN_ENV = "AGENTLOOM_INTERNAL_API_TOKEN"


class InternalAPIBearerAuthMiddleware:
    """Require a configured bearer token for every internal control-plane route."""

    def __init__(self, app: ASGIApp, token: bytes) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith("/internal/"):
            authorization = Headers(scope=scope).get("authorization", "")
            scheme, separator, supplied_token = authorization.partition(" ")
            if (
                scheme.lower() != "bearer"
                or not separator
                or not compare_digest(supplied_token.encode("utf-8"), self._token)
            ):
                await JSONResponse(
                    status_code=401,
                    content=_INTERNAL_AUTH_ERROR,
                    headers={"WWW-Authenticate": "Bearer"},
                )(scope, receive, send)
                return
        await self._app(scope, receive, send)


def create_app(
    database: Database,
    grant_authorizer: SkillGrantAuthorizer | None = None,
    *,
    internal_api_token: str,
) -> FastAPI:
    if not internal_api_token.isascii() or len(internal_api_token) < 32:
        raise ValueError("internal API token must contain at least 32 ASCII characters")
    app = FastAPI(title="AgentLoom API", version="0.1.0")
    app.add_middleware(
        InternalAPIBearerAuthMiddleware,
        token=internal_api_token.encode("ascii"),
    )

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


def create_app_from_env(database_url: str) -> FastAPI:
    """Build the control-plane app from process configuration.

    The internal bearer token intentionally has no CLI or URL fallback: it must
    be supplied through the process environment or an external secret manager.
    """
    token = os.environ.get(INTERNAL_API_TOKEN_ENV)
    if token is None:
        raise RuntimeError(
            f"{INTERNAL_API_TOKEN_ENV} must be set to start the internal API"
        )
    return create_app(Database(database_url), internal_api_token=token)


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
