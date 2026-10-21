"""Verify ms-auth authorization helpers."""

import pytest
from fastapi import HTTPException

from cmd.api.acl.ms_auth_security import MsAuthPrincipal
from improvement_plan.entity import ImprovementPlan
from internal.http.ms_auth_authorization import (
    ensure_company,
    ensure_external_user,
    ensure_internal_user,
    ensure_plan_belongs_to_principal,
)
from session.entity import Session
from user.entity import User


def principal(id_external_user=1, id_external_company=90):
    """Build a minimal ms-auth principal for authorization unit tests."""
    return MsAuthPrincipal("token", id_external_user, id_external_company, {"id": id_external_user})


class StubUserRepository:
    """Minimal user repository double for authorization tests."""

    def __init__(self, user):
        self.user = user

    def get_user_by_id(self, id_user):
        """Return the scripted user when the internal id matches."""
        if self.user and self.user.id == id_user:
            return self.user
        return None


def test_ensure_external_user_rejects_mismatch():
    """Verify that ensure_external_user rejects a different external user id."""
    with pytest.raises(HTTPException) as exc:
        ensure_external_user(principal(id_external_user=1), 2)
    assert exc.value.status_code == 403


def test_ensure_company_rejects_mismatch():
    """Verify that ensure_company rejects a different company id."""
    with pytest.raises(HTTPException) as exc:
        ensure_company(principal(id_external_company=90), 91)
    assert exc.value.status_code == 403


def test_ensure_internal_user_rejects_foreign_user():
    """Verify that ensure_internal_user rejects another user's internal id."""
    repo = StubUserRepository(User(id="u1", id_external_user=2, role="r", usecase="u"))
    with pytest.raises(HTTPException) as exc:
        ensure_internal_user(principal(id_external_user=1), "u1", repo)
    assert exc.value.status_code == 403


def test_ensure_plan_belongs_to_principal_rejects_foreign_company():
    """Verify that ensure_plan_belongs_to_principal hides another company's plan as not found."""
    plan = ImprovementPlan(id_external_company=91, defined_problem="p", method="m", reasoning="r")
    with pytest.raises(HTTPException) as exc:
        ensure_plan_belongs_to_principal(principal(id_external_company=90), plan)
    assert exc.value.status_code == 404
    assert exc.value.status_code != 403


def test_ensure_plan_belongs_to_principal_allows_matching_company():
    """Verify that ensure_plan_belongs_to_principal accepts a plan for the token company."""
    plan = ImprovementPlan(id_external_company=90, defined_problem="p", method="m", reasoning="r")
    ensure_plan_belongs_to_principal(principal(id_external_company=90), plan)
