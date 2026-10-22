"""Expose HTTP endpoints and response models for conversations and messages."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from internal.http.ms_auth_authorization import (
    ensure_company,
    ensure_external_user,
    ensure_internal_user,
    ensure_session_belongs_to_principal,
)
from internal.http.ms_auth_dependencies import MsAuth, require_ms_auth_principal
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from aeko_metrics.aeko_metrics import IService as IAekoMetricsService
from aeko_metrics.database.repository import Repository as AekoMetricsRepository
from aeko_metrics.service import Service as AekoMetricsService
from session.database.repository import Repository as SessionRepository
from session.cache.repository import Repository as CacheRepository
from session.service import Service
from session.session import GuardrailRejectedError, IService

from cmd.memory_generator_worker.constants import (
    REDIS_SCAN_COUNT,
    SESSION_INACTIVITY_MINUTES,
)
from internal.http.constants import MESSAGE_INPUT_MAX_LENGTH, UNEXPECTED_SERVER_ERROR
from internal.shared import Module, log_failure
from user.database.repository import Repository as UserRepository
from user.service import Service as UserService

router = APIRouter(tags=["Sessions"], dependencies=[Depends(require_ms_auth_principal)])


def _positive_external_id(value, field_name: str) -> int:
    """Accept a positive integer or numeric string and reject bools or other values."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a positive integer.")

    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "" or not stripped.isdigit():
            raise ValueError(f"{field_name} must be a positive integer.")
        parsed = int(stripped)
    else:
        raise ValueError(f"{field_name} must be a positive integer.")

    if parsed <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")

    return parsed


def _bounded_message_input(value) -> str:
    """Accept a string up to MESSAGE_INPUT_MAX_LENGTH characters."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("input must be a string.")
    if len(value) > MESSAGE_INPUT_MAX_LENGTH:
        raise ValueError("input exceeds the maximum length.")
    return value


def _internal_server_error(exc: Exception, operation_name: str) -> HTTPException:
    """Log an unexpected failure and return a stable HTTP 500."""
    log_failure(Module.REQUEST, f"{operation_name}: {type(exc).__name__}: {exc}")
    return HTTPException(status_code=500, detail=UNEXPECTED_SERVER_ERROR)


class SessionResponseData(BaseModel):
    id: str = Field(
        ...,
        description="Internal session identifier.",
        json_schema_extra={"example": "65a8b3d6c0f8e1d7f4b2c001"},
    )
    name: str = Field(
        ...,
        description="Human-readable session name.",
        json_schema_extra={"example": "Weekly emissions review"},
    )

    model_config = ConfigDict(frozen=True)


class MessageResponseData(BaseModel):
    input_message: str = Field(
        ...,
        description="Input text sent to the AI agent.",
        json_schema_extra={"example": "Summarize this session."},
    )
    output_message: str = Field(
        ...,
        description="Output returned by the AI agent.",
        json_schema_extra={"example": "Here is the summary."},
    )
    submitted_at: datetime = Field(
        ...,
        description="Timestamp when the message was submitted.",
        json_schema_extra={"example": "2026-07-26T14:30:00Z"},
    )

    model_config = ConfigDict(frozen=True)


class SendMessageResponseData(MessageResponseData):
    id_session: str = Field(
        ...,
        description="Internal session identifier of the conversation turn.",
        json_schema_extra={"example": "65a8b3d6c0f8e1d7f4b2c001"},
    )
    session_name: str = Field(
        ...,
        description="Human-readable session name after the turn was stored.",
        json_schema_extra={"example": "Weekly emissions review"},
    )


class UserCostResponseData(BaseModel):
    id_external_user: int = Field(
        ...,
        description="External user identifier whose runs were billed.",
        json_schema_extra={"example": 12345},
    )
    cost_usd: float = Field(
        ...,
        description="USD spent by this user in the requested window.",
        json_schema_extra={"example": 0.25},
    )

    model_config = ConfigDict(frozen=True)


class CompanyCostResponseData(BaseModel):
    id_external_company: int = Field(
        ...,
        description="External company identifier snapshotted on the billed runs.",
        json_schema_extra={"example": 90},
    )
    cost_usd: float = Field(
        ...,
        description="USD spent by every user of this company in the requested window.",
        json_schema_extra={"example": 0.45},
    )
    users: list[UserCostResponseData] = Field(
        ..., description="Per-user USD totals inside the same window."
    )

    model_config = ConfigDict(frozen=True)


def get_session_service(request: Request) -> IService:
    """Build the session service from the application database and cache, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    redis = getattr(request.app.state, "redis", None)
    cache_repository = None
    if redis is not None:
        cache_repository = CacheRepository(redis, scan_count=REDIS_SCAN_COUNT)
    return Service(
        SessionRepository(database),
        cache_repository,
        inactivity_minutes=SESSION_INACTIVITY_MINUTES,
    )


def get_user_repository(request: Request) -> UserRepository:
    """Build the user repository from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return UserRepository(database)


def get_session_repository(request: Request) -> SessionRepository:
    """Build the session repository from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return SessionRepository(database)


def get_aeko_metrics_service(request: Request) -> IAekoMetricsService:
    """Build the SDK metrics service from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return AekoMetricsService(AekoMetricsRepository(database))


@router.get(
    "/ai/sessions/cost",
    response_model=CompanyCostResponseData,
    summary="Sum session and SDK cost for a company",
    description="Returns USD spent in the last n days by runs that snapshotted the given company, grouped by external user.",
    responses={
        200: {
            "description": "Company cost for the requested window.",
            "content": {
                "application/json": {
                    "example": {
                        "id_external_company": 90,
                        "cost_usd": 0.45,
                        "users": [
                            {"id_external_user": 1, "cost_usd": 0.25},
                            {"id_external_user": 2, "cost_usd": 0.20},
                        ],
                    }
                }
            },
        },
        400: {"description": "n or id_external_company is invalid."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_company_cost(
    principal: MsAuth,
    n: int = Query(
        ..., description="Number of trailing days to include.", examples=[7]
    ),
    id_external_company: int = Query(
        ...,
        description="External company identifier snapshotted on billed runs.",
        examples=[90],
    ),
    service: IAekoMetricsService = Depends(get_aeko_metrics_service),
) -> CompanyCostResponseData:
    """Return USD spent by a company's users over the trailing n days."""
    ensure_company(principal, id_external_company)
    try:
        result = service.company_cost(n, id_external_company)
        return CompanyCostResponseData(
            id_external_company=result.id_external_company,
            cost_usd=result.cost_usd,
            users=[
                UserCostResponseData(
                    id_external_user=user.id_external_user,
                    cost_usd=user.cost_usd,
                )
                for user in result.users
            ],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _internal_server_error(exc, "Error retrieving company cost") from exc


@router.get(
    "/ai/sessions/user/{id_external_user}",
    response_model=list[SessionResponseData],
    summary="List sessions for a user",
    description="Returns all sessions associated with the external user identifier.",
    responses={
        200: {
            "description": "Sessions found for the user.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "65a8b3d6c0f8e1d7f4b2c001",
                            "name": "Weekly emissions review",
                        }
                    ]
                }
            },
        },
        403: {"description": "The path user does not match the access token."},
        404: {"description": "No sessions found for the given user."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_user_sessions(
    principal: MsAuth,
    id_external_user: int = Path(
        ..., description="External user identifier.", examples=[12345]
    ),
    service: IService = Depends(get_session_service),
    user_repository: UserRepository = Depends(get_user_repository),
) -> list[SessionResponseData]:
    """Retrieve the sessions belonging to a user."""
    ensure_external_user(principal, id_external_user)
    try:
        user = user_repository.get_user(id_external_user)
        sessions = service.get_user_sessions(user.id)
        return [
            SessionResponseData(id=session.id, name=session.name)
            for session in sessions
        ]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise _internal_server_error(exc, "Error retrieving user sessions") from exc


@router.get(
    "/ai/session/{id_session}/messages",
    response_model=list[MessageResponseData],
    summary="List messages for a session",
    description="Returns the message history stored for a specific session.",
    responses={
        200: {
            "description": "Messages found for the session.",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "input_message": "Summarize this session.",
                            "output_message": "Here is the summary.",
                            "submitted_at": "2026-07-26T14:30:00Z",
                        }
                    ]
                }
            },
        },
        400: {"description": "The session identifier is invalid or unavailable."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_session_messages(
    principal: MsAuth,
    id_session: str = Path(
        ...,
        description="Internal session identifier.",
        examples=["65a8b3d6c0f8e1d7f4b2c001"],
    ),
    service: IService = Depends(get_session_service),
    session_repository: SessionRepository = Depends(get_session_repository),
    user_repository: UserRepository = Depends(get_user_repository),
) -> list[MessageResponseData]:
    """Retrieve the stored messages for a session."""
    try:
        session = session_repository.get_session(id_session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _internal_server_error(exc, "Error retrieving session messages") from exc
    ensure_session_belongs_to_principal(principal, session, user_repository)
    try:
        messages = service.get_session_messages(id_session)
        return [
            MessageResponseData(
                input_message=message.input,
                output_message=message.output,
                submitted_at=message.submitted_at,
            )
            for message in messages
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise _internal_server_error(exc, "Error retrieving session messages") from exc


@router.post(
    "/ai/user/session/message",
    summary="Send a message to the AI session",
    description="Creates or continues a session message exchange using the current Aeko messenger instance.",
    tags=["Sessions"],
    response_model=SendMessageResponseData,
    responses={
        200: {
            "description": "Message processed successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "input_message": "Summarize this session.",
                        "output_message": "Here is the summary.",
                        "submitted_at": "2026-07-26T14:30:00Z",
                        "id_session": "65a8b3d6c0f8e1d7f4b2c001",
                        "session_name": "Weekly emissions review",
                    }
                }
            },
        },
        400: {
            "description": "The request body is missing required fields or is invalid."
        },
        422: {
            "description": "Neither the output guardrail nor the response checker approved a draft, so the run produced no answer."
        },
        500: {
            "description": "The Aeko SDK is not initialized or an unexpected error occurred."
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["id_external_user", "id_external_company"],
                        "properties": {
                            "id_session": {
                                "type": "string",
                                "description": "Optional session identifier. Omit or send an empty value to create a new session.",
                                "example": "65a8b3d6c0f8e1d7f4b2c001",
                            },
                            "input": {
                                "type": "string",
                                "description": "Message text to send to the AI agent.",
                                "example": "Summarize this session.",
                            },
                            "id_external_user": {
                                "type": "integer",
                                "description": "External user identifier used to resolve or create the Mongo user.",
                                "example": 12345,
                            },
                            "id_external_company": {
                                "type": "integer",
                                "description": "External company identifier stored when a new user is created.",
                                "example": 90,
                            },
                        },
                    },
                    "example": {
                        "id_session": "65a8b3d6c0f8e1d7f4b2c001",
                        "input": "Summarize this session.",
                        "id_external_user": 12345,
                        "id_external_company": 90,
                    },
                }
            },
        }
    },
)
async def send_message(
    request: Request,
    principal: MsAuth,
    service: IService = Depends(get_session_service),
):
    """Send a conversation turn and persist the approved response with its run metrics."""
    body = await request.json()

    try:
        id_session = body.get("id_session")
        if id_session is not None and not isinstance(id_session, str):
            raise ValueError("id_session must be a string.")
        input = _bounded_message_input(body.get("input", ""))
        id_external_user = _positive_external_id(
            body.get("id_external_user"), "id_external_user"
        )
        id_external_company = _positive_external_id(
            body.get("id_external_company"),
            "id_external_company",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    aeko_messenger_factory = request.app.state._state.get("aeko_messenger_factory")
    aeko_session_factory = request.app.state._state.get("aeko_session_factory")

    if not aeko_messenger_factory or not aeko_session_factory:
        raise HTTPException(status_code=500, detail="Aeko SDK is not initialized")

    ensure_external_user(principal, id_external_user)
    ensure_company(principal, id_external_company)

    user = UserService(UserRepository(request.app.state.db)).get_mongo_user_or_create(
        id_external_user,
        "",
        "",
        id_external_company=id_external_company,
    )

    try:
        result = await run_in_threadpool(
            service.send_message,
            id_session,
            input,
            user.id,
            aeko_messenger_factory,
            aeko_session_factory,
            UserRepository(request.app.state.db),
        )
        return SendMessageResponseData(
            input_message=result.message.input,
            output_message=result.message.output,
            submitted_at=result.message.submitted_at,
            id_session=result.session.id,
            session_name=result.session.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GuardrailRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _internal_server_error(exc, "Error sending message") from exc
