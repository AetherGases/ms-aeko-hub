"""Verify ms-auth profile client behavior and error handling."""

import json

import pytest
import requests

PROFILE_ADDRESS = {
    "id": 5,
    "zipCode": "01310100",
    "state": "SP",
    "city": "Sao Paulo",
    "neighborhood": "Bela Vista",
    "street": "Av Paulista",
    "number": 1000,
    "complement": "10o andar",
}

PROFILE_PAYLOAD = {
    "id": 1,
    "cpf": "12345678901",
    "email": "caio@example.com",
    "name": "Caio Marcos",
    "phone": "11999999999",
    "image": {"id": 10, "name": "profile.jpg", "path": "/images/profiles/profile.jpg"},
    "permissions": [],
    "enterprise": {
        "id": 90,
        "name": "Aether Industria SA",
        "tradeName": "Aether",
        "cnpj": "12345678000199",
        "address": PROFILE_ADDRESS,
    },
    "unit": {
        "id": 1,
        "cnae": "6201500",
        "cnpj": "12345678000199",
        "isActive": True,
        "address": PROFILE_ADDRESS,
    },
}


class FakeResponse:
    """Stands in for `requests.Response`."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload if payload is not None else {})

    def json(self):
        """Return the scripted JSON response body."""
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class RecordingRequest:
    """Captures every call `requests.request` would have made."""

    def __init__(self, response=None, error=None):
        self.response = response if response is not None else FakeResponse(payload={"ok": True})
        self.error = error
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture
def profile_env(monkeypatch):
    """Set test auth microservice environment variables for profile calls."""
    monkeypatch.setenv("AUTH_MS_BASE_URL", "http://auth.test")
    monkeypatch.setenv("MS_HTTP_TIMEOUT", "60")


@pytest.fixture
def recorded_request(monkeypatch, profile_env):
    """Replace profile HTTP requests with a call recorder."""
    from cmd.api.integrations import ms_auth_http, profile_api

    request = RecordingRequest(FakeResponse(payload=PROFILE_PAYLOAD))
    monkeypatch.setattr(ms_auth_http.requests, "request", request)
    return request


def test_get_profile_uses_authorization_bearer_and_empty_body(recorded_request):
    """Verify that get profile uses the Authorization header and an empty JSON body."""
    from cmd.api.integrations import profile_api

    profile_api.get_profile("ms-access")

    call = recorded_request.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "http://auth.test/api/profile"
    assert call["headers"]["Authorization"] == "Bearer ms-access"
    assert "Authentication" not in call["headers"]
    assert call["json"] == {}
    assert call["timeout"] == 60.0


def test_get_profile_returns_the_ms_payload_as_is(recorded_request):
    """Verify that get profile returns the ms payload as is."""
    from cmd.api.integrations import profile_api

    assert profile_api.get_profile("ms-access") == PROFILE_PAYLOAD


def test_profile_id_returns_the_positive_integer_id():
    """Verify that profile id returns the positive integer id."""
    from cmd.api.integrations.profile_api import profile_id

    assert profile_id({"id": 1, "cpf": "12345678901"}) == 1
    assert profile_id({"id": "12"}) == 12


@pytest.mark.parametrize("payload", [{}, {"id": True}, {"id": 0}, {"id": -1}, {"id": "x"}])
def test_profile_id_rejects_an_unusable_id(payload):
    """Verify that profile id rejects an unusable id."""
    from cmd.api.integrations.profile_api import profile_id

    with pytest.raises(ValueError):
        profile_id(payload)


def test_profile_enterprise_id_reads_the_nested_enterprise_id():
    """Verify that profile enterprise id reads enterprise.id from the ms-auth payload."""
    from cmd.api.integrations.profile_api import profile_enterprise_id

    assert profile_enterprise_id(PROFILE_PAYLOAD) == 90


def test_sign_in_profile_sync_keeps_only_the_company_id():
    """Verify that sign in profile sync keeps only the company id for Mongo."""

    from cmd.api.integrations.profile_api import sign_in_profile_sync

    assert sign_in_profile_sync(PROFILE_PAYLOAD) == {"id_external_company": 90}


def test_profile_tool_catalog_merges_role_and_usecase():
    """Verify that profile tool catalog merges role and usecase from Mongo."""

    from cmd.api.integrations.profile_api import profile_tool_catalog

    catalog = profile_tool_catalog(PROFILE_PAYLOAD, role="analyst", usecase="inventory")
    assert catalog["id"] == 1
    assert catalog["enterprise"] == PROFILE_PAYLOAD["enterprise"]
    assert catalog["role"] == "analyst"
    assert catalog["usecase"] == "inventory"


@pytest.mark.parametrize("env_var", ["AUTH_MS_BASE_URL", "MS_HTTP_TIMEOUT"])
def test_get_profile_raises_naming_a_missing_env_var(monkeypatch, profile_env, env_var):
    """Verify that get profile raises naming a missing env var."""
    monkeypatch.delenv(env_var, raising=False)
    from cmd.api.integrations import profile_api

    with pytest.raises(RuntimeError) as error:
        profile_api.get_profile("ms-access")
    assert env_var in str(error.value)


@pytest.mark.parametrize("status_code", [401, 500])
def test_get_profile_raises_on_http_error(monkeypatch, profile_env, status_code):
    """Verify that get profile raises on http error."""
    from cmd.api.integrations import ms_auth_http, profile_api

    monkeypatch.setattr(
        ms_auth_http.requests,
        "request",
        RecordingRequest(FakeResponse(status_code=status_code, payload={"message": "denied"})),
    )
    with pytest.raises(profile_api.ProfileError):
        profile_api.get_profile("ms-access")


def test_get_profile_raises_on_transport_error(monkeypatch, profile_env):
    """Verify that get profile raises on transport error."""
    from cmd.api.integrations import ms_auth_http, profile_api

    monkeypatch.setattr(
        ms_auth_http.requests,
        "request",
        RecordingRequest(error=requests.ConnectionError("down")),
    )
    with pytest.raises(profile_api.ProfileError):
        profile_api.get_profile("ms-access")
