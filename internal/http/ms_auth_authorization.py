"""Authorize HTTP requests against the ms-auth principal bound by the dependency."""

from fastapi import HTTPException

from cmd.api.acl.ms_auth_security import MsAuthPrincipal
from improvement_plan.entity import ImprovementPlan
from session.entity import Session
from user.database.repository import Repository as UserRepository
from user.entity import User


def ensure_external_user(principal: MsAuthPrincipal, id_external_user: int) -> None:
    """Reject requests whose path or body names a different external user."""
    if principal.id_external_user != id_external_user:
        raise HTTPException(
            status_code=403,
            detail="id_external_user does not match the access token.",
        )


def ensure_company(principal: MsAuthPrincipal, id_external_company: int) -> None:
    """Reject requests that target a different company than the token."""
    if principal.id_external_company != id_external_company:
        raise HTTPException(
            status_code=403,
            detail="id_external_company does not match the access token.",
        )


def _mongo_user_for_internal_id(repository: UserRepository, id_user: str) -> User:
    """Load the Mongo user for an internal id or raise HTTP 404."""
    user = repository.get_user_by_id(id_user)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def ensure_internal_user(
    principal: MsAuthPrincipal,
    id_user: str,
    repository: UserRepository,
) -> User:
    """Reject requests that reference another user's internal Mongo id."""
    user = _mongo_user_for_internal_id(repository, id_user)
    ensure_external_user(principal, user.id_external_user)
    return user


def ensure_session_belongs_to_principal(
    principal: MsAuthPrincipal,
    session: Session,
    repository: UserRepository,
) -> User:
    """Reject session reads when the session owner does not match the token."""
    return ensure_internal_user(principal, session.id_user, repository)


def ensure_plan_belongs_to_principal(
    principal: MsAuthPrincipal,
    plan: ImprovementPlan,
) -> None:
    """Reject plan reads when the stored company does not match the token."""
    company = plan.id_external_company
    if company is None:
        raise HTTPException(status_code=404, detail="Improvement plan not found.")
    ensure_company(principal, company)
