"""Expose HTTP endpoints and response models for conversations and messages."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from aeko_metrics.aeko_metrics import IService as IAekoMetricsService
from aeko_metrics.database.repository import Repository as AekoMetricsRepository
from aeko_metrics.service import Service as AekoMetricsService
from session.database.repository import Repository
from session.cache.repository import Repository as CacheRepository
from session.service import Service
from session.session import GuardrailRejectedError, IService

from cmd.memory_generator_worker.constants import REDIS_SCAN_COUNT, SESSION_INACTIVITY_MINUTES
from user.database.repository import Repository as UserRepository

router = APIRouter(tags=["Sessions"])

class SessionResponseData(BaseModel):
    id: str = Field(..., description="Internal session identifier.", json_schema_extra={"example": "65a8b3d6c0f8e1d7f4b2c001"})
    name: str = Field(..., description="Human-readable session name.", json_schema_extra={"example": "Weekly emissions review"})

    model_config = ConfigDict(frozen=True)

class MessageResponseData(BaseModel):
    input_message: str = Field(..., description="Input text sent to the AI agent.", json_schema_extra={"example": "Summarize this session."})
    output_message: str = Field(..., description="Output returned by the AI agent.", json_schema_extra={"example": "Here is the summary."})
    submitted_at: datetime = Field(..., description="Timestamp when the message was submitted.", json_schema_extra={"example": "2026-07-26T14:30:00Z"})

    model_config = ConfigDict(frozen=True)


class UserCostResponseData(BaseModel):
    id_external_user: int = Field(..., description="External user identifier whose runs were billed.", json_schema_extra={"example": 12345})
    cost_usd: float = Field(..., description="USD spent by this user in the requested window.", json_schema_extra={"example": 0.25})

    model_config = ConfigDict(frozen=True)


class CompanyCostResponseData(BaseModel):
    id_external_company: int = Field(..., description="External company identifier snapshotted on the billed runs.", json_schema_extra={"example": 90})
    cost_usd: float = Field(..., description="USD spent by every user of this company in the requested window.", json_schema_extra={"example": 0.45})
    users: list[UserCostResponseData] = Field(..., description="Per-user USD totals inside the same window.")

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
        Repository(database),
        cache_repository,
        inactivity_minutes=SESSION_INACTIVITY_MINUTES,
    )


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
    n: int = Query(..., description="Number of trailing days to include.", examples=[7]),
    id_external_company: int = Query(..., description="External company identifier snapshotted on billed runs.", examples=[90]),
    service: IAekoMetricsService = Depends(get_aeko_metrics_service),
) -> CompanyCostResponseData:
    """Return USD spent by a company's users over the trailing n days."""
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
        raise HTTPException(status_code=500, detail=f"Error retrieving company cost: {exc}") from exc


@router.get(
    "/ai/sessions/user/{id_user}",
    response_model=list[SessionResponseData],
    summary="List sessions for a user",
    description="Returns all sessions associated with the internal user identifier.",
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
        404: {"description": "No sessions found for the given user."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_user_sessions(
    id_user: str = Path(..., description="Internal user identifier.", examples=["65a8b3d6c0f8e1d7f4b2c010"]),
    service: IService = Depends(get_session_service),
) -> list[SessionResponseData]:
    """Retrieve the sessions belonging to a user."""
    try:
        sessions = service.get_user_sessions(id_user)
        return [SessionResponseData(id=session.id, name=session.name) for session in sessions]
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user sessions: {exc}") from exc

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
    id_session: str = Path(..., description="Internal session identifier.", examples=["65a8b3d6c0f8e1d7f4b2c001"]),
    service: IService = Depends(get_session_service),
) -> list[MessageResponseData]:
    """Retrieve the stored messages for a session."""
    try:
        messages = service.get_session_messages(id_session)
        return [
            MessageResponseData(
                input_message=message.input,
                output_message=message.output,
                submitted_at=message.submitted_at
            )
            for message in messages
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving session messages: {exc}") from exc

@router.post(
    "/ai/user/session/message",
    summary="Send a message to the AI session",
    description="Creates or continues a session message exchange using the current Aeko messenger instance.",
    tags=["Sessions"],
    responses={
        200: {
            "description": "Message processed successfully.",
            "content": {
                "application/json": {
                    "example": {
                        "input_message": "Summarize this session.",
                        "output_message": "Here is the summary.",
                        "submitted_at": "2026-07-26T14:30:00Z",
                    }
                }
            },
        },
        400: {"description": "The request body is missing required fields or is invalid."},
        502: {"description": "Neither the output guardrail nor the response checker approved a draft, so the run produced no answer."},
        500: {"description": "The Aeko SDK is not initialized or an unexpected error occurred."},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["id_session", "input", "id_user"],
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
                            "id_user": {
                                "type": "string",
                                "description": "Internal user identifier.",
                                "example": "65a8b3d6c0f8e1d7f4b2c010",
                            },
                        },
                    },
                    "example": {
                        "id_session": "65a8b3d6c0f8e1d7f4b2c001",
                        "input": "Summarize this session.",
                        "id_user": "65a8b3d6c0f8e1d7f4b2c010",
                    },
                }
            },
        }
    },
)
async def send_message(
    request: Request,
    service: IService = Depends(get_session_service),
):
    """Send a conversation turn and persist the approved response with its run metrics."""
    body = await request.json()

    id_session = body.get("id_session")
    input = body.get("input", "")
    id_user = body.get("id_user", "")
    aeko_messenger_factory = request.app.state._state.get("aeko_messenger_factory")
    aeko_session_factory = request.app.state._state.get("aeko_session_factory")

    if not aeko_messenger_factory or not aeko_session_factory:
        raise HTTPException(status_code=500, detail="Aeko SDK is not initialized")

    try:
        message = await run_in_threadpool(
            service.send_message,
            id_session,
            input,
            id_user,
            aeko_messenger_factory,
            aeko_session_factory,
            UserRepository(request.app.state.db),
        )
        return MessageResponseData(
            input_message=message.input,
            output_message=message.output,
            submitted_at=message.submitted_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GuardrailRejectedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error sending message: {exc}") from exc
