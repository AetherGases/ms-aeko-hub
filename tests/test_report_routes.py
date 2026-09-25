"""Verify report routes behavior and error handling."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from improvement_plan.entity import ExtractedInventory, ImprovementPlan, InventoryEmission
from improvement_plan.improvement_plan import MalformedPlanError
from internal.http import improvement_plan_handlers

ROUTE = "/aether-api/v1/ai/report"
GET_ROUTE = "/aether-api/v1/ai/report/{id_external_inventory}"

INVENTORY_MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"

REPORT_BODY = {
    "id_external_context_inventory": 502,
    "inventory": INVENTORY_MARKDOWN,
    "id_external_user": 12345,
    "gases": [{"id": 1, "name": "CO2"}],
    "scopes": [{"id": 1, "name": "Escopo 1"}],
    "categories": [{"id": 1, "name": "Combustão estacionária", "classification": None}],
}

EXTRACTED_INVENTORY = ExtractedInventory(
    description="Boiler-dominated inventory",
    start_period="2025-01-01",
    end_period="2025-12-31",
    emissions=[
        InventoryEmission(
            quantity_co2e=12400.0,
            methodology_description="stationary combustion",
            supplier_data_percentage=None,
            gas=1,
            scope=1,
            category=None,
            is_upstream=None,
            is_reduction=False,
        )
    ],
)

EXTRACTED_INVENTORY_JSON = {
    "description": "Boiler-dominated inventory",
    "start_period": "2025-01-01",
    "end_period": "2025-12-31",
    "emissions": [
        {
            "quantity_co2e": 12400.0,
            "methodology_description": "stationary combustion",
            "supplier_data_percentage": None,
            "gas": 1,
            "scope": 1,
            "category": None,
            "is_upstream": None,
            "is_reduction": False,
        }
    ],
}

STORED_PLAN = ImprovementPlan(
    id="65a8b3d6c0f8e1d7f4b2c020",
    id_external_inventory=502,
    defined_problem="high scope 1 emissions",
    method="replace the boiler fleet",
    reasoning="direct combustion dominates the inventory",
)


class StubReportService:
    def __init__(self, inventory=EXTRACTED_INVENTORY, plan=STORED_PLAN, error=None, get_error=None):
        self.inventory = inventory
        self.plan = plan
        self.error = error
        self.get_error = get_error
        self.calls = []
        self.gets = []

    def input_inventory(self, *args, **kwargs):
        """Analyze an inventory with its current plan as context, then store the new plan."""
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.inventory

    def get_by_id_external_inventory(self, id_external_inventory):
        """Retrieve the improvement plan associated with an external inventory identifier."""
        self.gets.append(id_external_inventory)
        if self.get_error is not None:
            raise self.get_error
        return self.plan


class StubUserRepository:
    def __init__(self, db):
        self.db = db


class StubUserService:
    def __init__(self, repository):
        self.repository = repository


@pytest.fixture
def patched_user_service(monkeypatch):
    """Replace the report user service with a test double."""
    monkeypatch.setattr(improvement_plan_handlers, "UserRepository", StubUserRepository)
    monkeypatch.setattr(improvement_plan_handlers, "UserService", StubUserService)
    return StubUserService


def build_analyzer_factory():
    """Build an analyzer factory for the report test application."""
    return lambda: "analyzer"


def build_client(service=None, db="fake-db", analyzer_factory=build_analyzer_factory()):
    """Build a test client or client double with the supplied dependencies."""
    app = FastAPI()
    app.include_router(improvement_plan_handlers.router)
    app.state.db = db
    if analyzer_factory is not None:
        app.state.aeko_inventory_analyzer_factory = analyzer_factory
    if service is not None:
        app.dependency_overrides[improvement_plan_handlers.get_improvement_plan_service] = lambda: service
    return TestClient(app)


def test_input_report_returns_the_structured_inventory(patched_user_service):
    """Verify that input report returns the structured inventory."""
    response = build_client(StubReportService()).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 200
    assert response.json() == EXTRACTED_INVENTORY_JSON
    assert set(response.json()) == {"description", "start_period", "end_period", "emissions"}


def test_input_report_forwards_what_the_flow_needs(patched_user_service):
    """Verify that input report forwards what the flow needs."""
    service = StubReportService()

    build_client(service).post(ROUTE, json=REPORT_BODY)

    args, _kwargs = service.calls[0]
    (
        id_external_inventory,
        inventory,
        id_external_user,
        gases,
        scopes,
        categories,
        user_service,
        analyzer_factory,
    ) = args
    assert (id_external_inventory, inventory, id_external_user) == (502, INVENTORY_MARKDOWN, 12345)
    assert gases == [{"id": 1, "name": "CO2"}]
    assert scopes == [{"id": 1, "name": "Escopo 1"}]
    assert categories == [{"id": 1, "name": "Combustão estacionária", "classification": None}]
    assert isinstance(user_service, StubUserService)
    assert callable(analyzer_factory)


def test_input_report_maps_value_error_to_400(patched_user_service):
    """Verify that input report maps value error to 400."""
    service = StubReportService(error=ValueError("inventory is required to analyze an inventory."))

    response = build_client(service).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 400
    assert response.json()["detail"] == "inventory is required to analyze an inventory."


def test_input_report_maps_a_missing_user_to_404(patched_user_service):
    """Verify that input report maps a missing user to 404."""
    service = StubReportService(error=ValueError("User with id_external_user 12345 not found."))

    response = build_client(service).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 404
    assert response.json()["detail"] == "User with id_external_user 12345 not found."


def test_input_report_maps_a_plan_that_never_took_shape_to_502(patched_user_service):
    """Verify that input report maps a plan that never took shape to 502."""
    service = StubReportService(
        error=MalformedPlanError("The analysis produced no plan in the shape a report is stored in.")
    )

    response = build_client(service).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The analysis produced no plan in the shape a report is stored in."
    )


def test_input_report_maps_unexpected_error_to_500(patched_user_service):
    """Verify that input report maps unexpected error to 500."""
    service = StubReportService(error=RuntimeError("analyzer down"))

    response = build_client(service).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 500
    assert "analyzer down" in response.json()["detail"]


def test_input_report_returns_503_when_database_is_not_initialized():
    """Verify that input report returns 503 when database is not initialized."""
    response = build_client(service=None, db=None).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is not initialized"


def test_input_report_returns_500_when_the_sdk_was_never_configured(patched_user_service):
    """Verify that input report returns 500 when the sdk was never configured."""
    response = build_client(StubReportService(), analyzer_factory=None).post(ROUTE, json=REPORT_BODY)

    assert response.status_code == 500
    assert response.json()["detail"] == "Aeko SDK is not initialized"


@pytest.mark.parametrize(
    "missing",
    [
        "id_external_context_inventory",
        "inventory",
        "id_external_user",
        "gases",
        "scopes",
        "categories",
    ],
)
def test_input_report_requires_every_body_field(missing, patched_user_service):
    """Verify that input report requires every body field."""
    body = {key: value for key, value in REPORT_BODY.items() if key != missing}

    response = build_client(StubReportService()).post(ROUTE, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("field", ["id_external_context_inventory", "id_external_user"])
def test_the_external_identifiers_must_be_numbers(field, patched_user_service):
    """Verify that the external identifiers must be numbers."""
    body = {**REPORT_BODY, field: "not-a-number"}

    response = build_client(StubReportService()).post(ROUTE, json=body)

    assert response.status_code == 422


def test_query_parameters_are_not_the_report_contract(patched_user_service):
    """Verify that query parameters are not the report contract."""
    response = build_client(StubReportService()).post(
        ROUTE,
        params={"id_external_inventory": 502, "id_external_unit": 77, "id_user": "u1"},
    )

    assert response.status_code == 422


def test_duplicate_catalog_ids_are_rejected(patched_user_service):
    """Verify that duplicate catalog ids are rejected."""
    body = {
        **REPORT_BODY,
        "gases": [{"id": 1, "name": "CO2"}, {"id": 1, "name": "CH4"}],
    }

    response = build_client(StubReportService()).post(ROUTE, json=body)

    assert response.status_code == 422


def test_an_unknown_category_classification_is_rejected(patched_user_service):
    """Verify that an unknown category classification is rejected."""
    body = {
        **REPORT_BODY,
        "categories": [{"id": 1, "name": "Purchased goods", "classification": "SIDEWAYS"}],
    }

    response = build_client(StubReportService()).post(ROUTE, json=body)

    assert response.status_code == 422


def test_get_report_returns_the_textual_plan(patched_user_service):
    """Verify that get report returns the textual plan."""
    response = build_client(StubReportService()).get(GET_ROUTE.format(id_external_inventory=502))

    assert response.status_code == 200
    assert response.json() == {
        "defined_problem": "high scope 1 emissions",
        "solving_method": "replace the boiler fleet",
        "reasoning": "direct combustion dominates the inventory",
    }


def test_get_report_asks_for_the_inventory_identifier(patched_user_service):
    """Verify that get report asks for the inventory identifier."""
    service = StubReportService()

    build_client(service).get(GET_ROUTE.format(id_external_inventory=502))

    assert service.gets == [502]


def test_get_report_maps_a_missing_plan_to_404(patched_user_service):
    """Verify that get report maps a missing plan to 404."""
    service = StubReportService(
        get_error=ValueError("Improvement plan with id_external_inventory 502 not found.")
    )

    response = build_client(service).get(GET_ROUTE.format(id_external_inventory=502))

    assert response.status_code == 404


def test_get_report_returns_503_when_database_is_not_initialized():
    """Verify that get report returns 503 when database is not initialized."""
    response = build_client(service=None, db=None).get(GET_ROUTE.format(id_external_inventory=502))

    assert response.status_code == 503


def test_get_report_does_not_require_the_sdk(patched_user_service):
    """Verify that get report does not require the sdk."""
    response = build_client(StubReportService(), analyzer_factory=None).get(
        GET_ROUTE.format(id_external_inventory=502)
    )

    assert response.status_code == 200
