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
    return MsAuthPrincipal("token", id_external_user, id_external_company, {"id": id_external_user})


class StubUserRepository:
    def __init__(self, user):
        self.user = user

    def get_user_by_id(self, id_user):
        if self.user and self.user.id == id_user:
            return self.user
        return None


def test_ensure_external_user_rejects_mismatch():
    with pytest.raises(HTTPException) as exc:
        ensure_external_user(principal(id_external_user=1), 2)
    assert exc.value.status_code == 403


def test_ensure_company_rejects_mismatch():
    with pytest.raises(HTTPException) as exc:
        ensure_company(principal(id_external_company=90), 91)
    assert exc.value.status_code == 403


def test_ensure_internal_user_rejects_foreign_user():
    repo = StubUserRepository(User(id="u1", id_external_user=2, role="r", usecase="u"))
    with pytest.raises(HTTPException) as exc:
        ensure_internal_user(principal(id_external_user=1), "u1", repo)
    assert exc.value.status_code == 403


def test_ensure_plan_belongs_to_principal_rejects_foreign_company():
    plan = ImprovementPlan(id_external_company=91, defined_problem="p", method="m", reasoning="r")
    with pytest.raises(HTTPException) as exc:
        ensure_plan_belongs_to_principal(principal(id_external_company=90), plan)
    assert exc.value.status_code == 403
