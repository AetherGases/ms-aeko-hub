"""Expose HTTP endpoints and response models for users and memories."""

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from internal.http.ms_auth_authorization import ensure_external_user
from internal.http.ms_auth_dependencies import MsAuth, require_ms_auth_principal
from user.database.repository import Repository as UserRepository
from user.service import Service as UserService
from user.user import IService

router = APIRouter(tags=["Users"], dependencies=[Depends(require_ms_auth_principal)])

class UserResponseData(BaseModel):
    id_external_user: int = Field(..., description="External identifier of the user.", json_schema_extra={"example": 12345})
    role: str = Field(..., description="Role assigned to the user.", json_schema_extra={"example": "analyst"})
    usecase: str = Field(..., description="User use case or profile category.", json_schema_extra={"example": "report_generation"})
    id_external_company: int | None = Field(None, description="External identifier of the user's company.", json_schema_extra={"example": None})

    model_config = ConfigDict(frozen=True)


def get_user_service(request: Request) -> IService:
    """Build the user service from the application database, or raise HTTP 503."""
    database = request.app.state.db
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not initialized")
    return UserService(UserRepository(database))


@router.get(
    "/ai/user/{id_external_user}",
    response_model=UserResponseData,
    summary="Get user by external identifier",
    description="Retrieves a user profile using the external user identifier stored in the core database.",
    responses={
        200: {
            "description": "User profile found.",
            "content": {
                "application/json": {
                    "example": {
                        "id_external_user": 12345,
                        "role": "analyst",
                        "usecase": "report_generation",
                        "id_external_company": None,
                    }
                }
            },
        },
        404: {"description": "User not found."},
        503: {"description": "Database connection is unavailable."},
        500: {"description": "Unexpected server error."},
    },
)
def get_user(
    principal: MsAuth,
    id_external_user: int = Path(..., description="External user identifier.", examples=[12345]),
    service: IService = Depends(get_user_service),
) -> UserResponseData:
    """Retrieve a user by external identifier."""
    ensure_external_user(principal, id_external_user)
    try:
        user = service.get_mongo_user(id_external_user)
        return UserResponseData(
            id_external_user=user.id_external_user,
            role=user.role,
            usecase=user.usecase,
            id_external_company=user.id_external_company,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error retrieving user: {exc}") from exc
