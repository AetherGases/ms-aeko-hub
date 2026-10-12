"""Expose HTTP endpoints for inventory upload ticket handshake."""

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from internal.http.ms_auth_authorization import ensure_external_user
from internal.http.ms_auth_dependencies import MsAuth, require_ms_auth_principal
from pydantic import BaseModel, ConfigDict, Field

from cmd.api.integrations.cloudinary_api import CloudinaryError
from upload_ticket.cache.repository import Repository
from upload_ticket.service import Service
from upload_ticket.upload_ticket import IService

router = APIRouter(tags=["Inventory Upload"], dependencies=[Depends(require_ms_auth_principal)])


class CompleteRequest(BaseModel):
    path: str = Field(
        ...,
        description="Cloudinary storage path returned after the client upload completes.",
        json_schema_extra={"example": "https://cloudinary.example/uploads/file.xlsx"},
    )

    model_config = ConfigDict(frozen=True)


class CompleteResponse(BaseModel):
    ticket: str = Field(
        ...,
        description="Opaque upload ticket identifier.",
        json_schema_extra={"example": "opaque-ticket-token"},
    )
    state: str = Field(
        ...,
        description="Upload ticket state after path confirmation.",
        json_schema_extra={"example": "uploaded"},
    )

    model_config = ConfigDict(frozen=True)


def get_ticket_service(request: Request) -> IService:
    """Build the upload ticket service from the application cache, or raise HTTP 503."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        raise HTTPException(status_code=503, detail="Redis is not initialized")
    return Service(Repository(redis))


def _raise_for_value_error(exc: ValueError) -> None:
    """Translate domain validation errors to HTTP 404 or 400."""
    status_code = 404 if "not found" in str(exc).lower() else 400
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get(
    "/ai/user/{id_external_user}/inventory-upload/{ticket}/signature",
    summary="Redeem an upload ticket for a Cloudinary signature",
    description=(
        "Returns the Cloudinary upload signature for an inventory upload ticket "
        "owned by the given external user."
    ),
    responses={
        200: {
            "description": "Cloudinary upload signature returned.",
            "content": {
                "application/json": {
                    "example": {
                        "signature": "a1b2c3d4e5f6",
                        "timestamp": 1728067200,
                        "apiKey": "123456789012345",
                        "cloudName": "meu-cloud",
                        "cloudinaryFolder": "uploads",
                        "cloudinaryResourceType": "image",
                    }
                }
            },
        },
        404: {"description": "Upload ticket not found for the given user."},
        400: {"description": "The upload ticket is not available for signature redemption."},
        502: {"description": "The Cloudinary microservice could not return a signature."},
        503: {"description": "Redis connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_upload_signature(
    principal: MsAuth,
    id_external_user: int = Path(
        ...,
        description="External user identifier.",
        examples=[12345],
    ),
    ticket: str = Path(
        ...,
        description="Opaque upload ticket identifier.",
        examples=["opaque-ticket-token"],
    ),
    service: IService = Depends(get_ticket_service),
) -> dict:
    """Return the Cloudinary upload signature for a ticket."""
    ensure_external_user(principal, id_external_user)
    try:
        service.get(id_external_user, ticket)
        return service.signature_for(id_external_user, ticket)
    except ValueError as exc:
        _raise_for_value_error(exc)
    except CloudinaryError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving upload signature: {exc}",
        ) from exc


@router.post(
    "/ai/user/{id_external_user}/inventory-upload/{ticket}/complete",
    response_model=CompleteResponse,
    summary="Confirm the uploaded inventory file path",
    description=(
        "Records the Cloudinary storage path for an inventory upload ticket "
        "and marks the ticket as uploaded."
    ),
    responses={
        200: {
            "description": "Upload path stored and ticket marked as uploaded.",
            "content": {
                "application/json": {
                    "example": {
                        "ticket": "opaque-ticket-token",
                        "state": "uploaded",
                    }
                }
            },
        },
        404: {"description": "Upload ticket not found for the given user."},
        400: {"description": "The upload ticket cannot accept a path confirmation."},
        503: {"description": "Redis connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def complete_upload(
    principal: MsAuth,
    body: CompleteRequest,
    id_external_user: int = Path(
        ...,
        description="External user identifier.",
        examples=[12345],
    ),
    ticket: str = Path(
        ...,
        description="Opaque upload ticket identifier.",
        examples=["opaque-ticket-token"],
    ),
    service: IService = Depends(get_ticket_service),
) -> CompleteResponse:
    """Store the uploaded file path and mark the ticket as uploaded."""
    ensure_external_user(principal, id_external_user)
    try:
        updated = service.confirm_path(id_external_user, ticket, body.path)
        return CompleteResponse(ticket=updated.ticket, state=updated.state)
    except ValueError as exc:
        _raise_for_value_error(exc)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Error confirming upload path: {exc}",
        ) from exc
