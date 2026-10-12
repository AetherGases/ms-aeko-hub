"""Verify upload ticket HTTP routes behavior and error handling."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cmd.api.integrations.cloudinary_api import CloudinaryError
from internal.http import upload_ticket_handlers
from tests.ms_auth_doubles import override_ms_auth
from upload_ticket.entity import STATE_UPLOADED, UploadTicket

SIGNATURE_ROUTE = (
    "/ai/user/{id_external_user}/inventory-upload/{ticket}/signature"
)
COMPLETE_ROUTE = (
    "/ai/user/{id_external_user}/inventory-upload/{ticket}/complete"
)

SIGNATURE_PAYLOAD = {
    "signature": "a1b2c3d4e5f6",
    "timestamp": 1728067200,
    "apiKey": "123456789012345",
    "cloudName": "meu-cloud",
    "cloudinaryFolder": "uploads",
    "cloudinaryResourceType": "image",
}

TICKET_ID = "opaque-ticket-token"
USER_ID = 12345
OTHER_USER_ID = 99999
UPLOAD_PATH = "https://cloudinary.example/uploads/file.xlsx"


class StubUploadTicketService:
    def __init__(
        self,
        signature_result=None,
        signature_error=None,
        confirm_result=None,
        confirm_error=None,
        get_result=None,
        get_error=None,
    ):
        self.signature_result = signature_result
        self.signature_error = signature_error
        self.confirm_result = confirm_result
        self.confirm_error = confirm_error
        self.get_result = get_result
        self.get_error = get_error
        self.signature_calls = []
        self.confirm_calls = []
        self.get_calls = []

    def get(self, id_external_user, ticket):
        """Return or raise the scripted ticket lookup result."""
        self.get_calls.append(
            {"id_external_user": id_external_user, "ticket": ticket}
        )
        if self.get_error is not None:
            raise self.get_error
        return self.get_result

    def signature_for(self, id_external_user, ticket):
        """Return or raise the scripted signature result."""
        self.signature_calls.append(
            {"id_external_user": id_external_user, "ticket": ticket}
        )
        if self.signature_error is not None:
            raise self.signature_error
        return self.signature_result

    def confirm_path(self, id_external_user, ticket, path):
        """Record the path confirmation call and return or raise its scripted result."""
        self.confirm_calls.append(
            {
                "id_external_user": id_external_user,
                "ticket": ticket,
                "path": path,
            }
        )
        if self.confirm_error is not None:
            raise self.confirm_error
        return self.confirm_result

    def create(self, *args, **kwargs):
        """Reject ticket creation because these route tests never create tickets."""
        raise NotImplementedError

    def mark_consumed(self, *args, **kwargs):
        """Reject consumption because these route tests never consume tickets."""
        raise NotImplementedError

    def created_inventory_ids(self, *args, **kwargs):
        """Reject inventory lookup because these route tests never list created inventories."""
        raise NotImplementedError


def build_client(service=None, redis="fake-redis"):
    """Build a test client with the supplied upload ticket dependencies."""
    app = FastAPI()
    app.include_router(upload_ticket_handlers.router)
    app.state.redis = redis
    override_ms_auth(app)
    if service is not None:
        app.dependency_overrides[upload_ticket_handlers.get_ticket_service] = lambda: service
    return TestClient(app)


def uploaded_ticket():
    """Build an upload ticket fixture in the uploaded state."""
    return UploadTicket(
        ticket=TICKET_ID,
        id_external_user=USER_ID,
        name="inventory",
        file_name="file.xlsx",
        file_type="XLSX",
        path=UPLOAD_PATH,
        state=STATE_UPLOADED,
        inventory_id=None,
    )


def waiting_ticket():
    """Build an upload ticket fixture in the waiting-for-upload state."""
    return UploadTicket(
        ticket=TICKET_ID,
        id_external_user=USER_ID,
        name="inventory",
        file_name="file.xlsx",
        file_type="XLSX",
        path=None,
        state="waiting_for_upload",
        inventory_id=None,
    )


def test_get_signature_returns_cloudinary_fields():
    """Verify that get signature returns the Cloudinary signature payload."""
    service = StubUploadTicketService(
        get_result=waiting_ticket(),
        signature_result=SIGNATURE_PAYLOAD,
    )
    response = build_client(service).get(
        SIGNATURE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 200
    assert response.json() == SIGNATURE_PAYLOAD
    assert service.signature_calls == [
        {"id_external_user": USER_ID, "ticket": TICKET_ID}
    ]


def test_get_signature_for_another_user_returns_403_without_calling_signature_for():
    """Verify that get signature for another user returns 403 without calling signature_for."""
    service = StubUploadTicketService(
        get_error=ValueError("Upload ticket not found.")
    )
    response = build_client(service).get(
        SIGNATURE_ROUTE.format(id_external_user=OTHER_USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 403
    assert "id_external_user" in response.json()["detail"]
    assert service.signature_calls == []


def test_post_complete_stores_path_and_returns_uploaded_state():
    """Verify that post complete stores the path and returns uploaded state."""
    service = StubUploadTicketService(confirm_result=uploaded_ticket())
    response = build_client(service).post(
        COMPLETE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID),
        json={"path": UPLOAD_PATH},
    )

    assert response.status_code == 200
    assert response.json() == {"ticket": TICKET_ID, "state": STATE_UPLOADED}
    assert service.confirm_calls == [
        {
            "id_external_user": USER_ID,
            "ticket": TICKET_ID,
            "path": UPLOAD_PATH,
        }
    ]


def test_get_signature_maps_non_not_found_value_error_to_400():
    """Verify that get signature maps a value error without 'not found' to 400."""
    service = StubUploadTicketService(
        get_result=uploaded_ticket(),
        signature_error=ValueError("Upload ticket is not waiting for upload."),
    )
    response = build_client(service).get(
        SIGNATURE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload ticket is not waiting for upload."


def test_get_signature_for_consumed_ticket_maps_not_found_to_404():
    """Verify that the production consumed-ticket error maps to 404."""
    service = StubUploadTicketService(
        get_error=ValueError("Upload ticket not found.")
    )
    response = build_client(service).get(
        SIGNATURE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Upload ticket not found."
    assert service.signature_calls == []


def test_get_signature_maps_cloudinary_error_to_502():
    """Verify that get signature maps CloudinaryError to 502."""
    service = StubUploadTicketService(
        get_result=waiting_ticket(),
        signature_error=CloudinaryError("Cloudinary microservice unavailable."),
    )
    response = build_client(service).get(
        SIGNATURE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Cloudinary microservice unavailable."


def test_get_signature_returns_503_when_redis_is_not_initialized():
    """Verify that get signature returns 503 when redis is not initialized."""
    response = build_client(service=None, redis=None).get(
        SIGNATURE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID)
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Redis is not initialized"


def test_post_complete_maps_value_error_to_400():
    """Verify that post complete maps non-not-found value error to 400."""
    service = StubUploadTicketService(
        confirm_error=ValueError("Upload ticket path is already set.")
    )
    response = build_client(service).post(
        COMPLETE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID),
        json={"path": UPLOAD_PATH},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Upload ticket path is already set."


def test_post_complete_maps_not_found_to_404():
    """Verify that post complete maps not found value error to 404."""
    service = StubUploadTicketService(
        confirm_error=ValueError("Upload ticket not found.")
    )
    response = build_client(service).post(
        COMPLETE_ROUTE.format(id_external_user=USER_ID, ticket=TICKET_ID),
        json={"path": UPLOAD_PATH},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Upload ticket not found."
