"""Verify inventory ingest tools use upload tickets and domain services safely."""

import pytest
from langchain_core.tools import StructuredTool

from cmd.api.integrations.inventory_api import InventoryError
from cmd.api.tools import constants as tool_constants
from cmd.api.tools import inventory_tools
from improvement_plan.entity import ImprovementPlan
from upload_ticket.entity import UploadTicket


INVENTORY_POST_RESPONSE = {
    "id": 1,
    "name": "relatório",
    "type": "INPUT",
    "status": "PROCESSING",
    "createdAt": "2026-10-04T19:30:00",
    "storageFile": {
        "id": 10,
        "fileName": "inventorio-principal.xlsx",
        "path": "https://cloudinary/sadjasoda",
        "createdAt": "2026-10-04T19:30:00",
    },
}


def uploaded_ticket(*, state="uploaded", path="https://cloudinary/sadjasoda"):
    """Build an upload ticket for second-call tests."""

    return UploadTicket(
        ticket="t1",
        id_external_user=12345,
        name="relatório",
        file_name="inventorio-principal.xlsx",
        file_type="XLSX",
        path=path,
        state=state,
        inventory_id=None,
    )


class StubTickets:
    """Record ticket operations and return scripted ticket data."""

    def __init__(self, *, stored=None):
        self.stored = stored
        self.create_calls = []
        self.get_calls = []
        self.consumed = []
        self.created = {}

    def create(self, id_external_user, name, file_name, file_type):
        """Record ticket creation and return a waiting ticket."""

        self.create_calls.append((id_external_user, name, file_name, file_type))
        return UploadTicket(
            ticket="new-ticket",
            id_external_user=id_external_user,
            name=name,
            file_name=file_name,
            file_type=file_type,
            path=None,
            state="waiting_for_upload",
            inventory_id=None,
        )

    def get(self, id_external_user, ticket):
        """Record and serve one ticket lookup."""

        self.get_calls.append((id_external_user, ticket))
        return self.stored

    def mark_consumed(self, id_external_user, ticket, inventory_id):
        """Record inventory consumption."""

        self.consumed.append((ticket, inventory_id))

    def created_inventory_ids(self, id_external_user):
        """Return inventory identifiers created by one user."""

        return list(self.created.get(id_external_user, []))


class StubCreateInventory:
    """Record inventory creation calls and return a scripted response."""

    def __init__(self):
        self.payload = dict(INVENTORY_POST_RESPONSE)
        self.error = None
        self.calls = []

    def __call__(self, name, file_name, path):
        """Create the scripted inventory or raise its configured error."""

        self.calls.append((name, file_name, path))
        if self.error is not None:
            raise self.error
        return self.payload


class StubPlans:
    """Record improvement-plan reads and return a scripted plan."""

    def __init__(self):
        self.plan = None
        self.missing = False
        self.calls = []

    def get_by_id_external_inventory(self, identifier):
        """Return a plan or represent a still-processing inventory."""

        self.calls.append(identifier)
        if self.missing:
            raise ValueError("Improvement plan not found.")
        return self.plan


@pytest.fixture
def services():
    """Bind fresh inventory tool service doubles."""

    tickets = StubTickets(stored=uploaded_ticket())
    create_inventory = StubCreateInventory()
    plans = StubPlans()
    inventory_tools.configure(
        tickets=tickets,
        create_inventory=create_inventory,
        plans=plans,
    )
    yield tickets, create_inventory, plans
    inventory_tools.configure()


def test_analyze_inventory_first_call_returns_only_ticket_and_waiting_state(services):
    """Return an opaque ticket without exposing upload credentials."""

    tickets, _, _ = services

    result = inventory_tools._analyze_inventory(
        12345,
        name="relatório",
        fileName="inventorio-principal.xlsx",
        fileType="XLSX",
    )

    assert set(result) == {"ticket", "state"}
    assert result == {"ticket": "new-ticket", "state": "waiting_for_upload"}
    assert "signature" not in result and "path" not in result and "apiKey" not in result
    assert tickets.create_calls == [
        (12345, "relatório", "inventorio-principal.xlsx", "XLSX")
    ]


@pytest.mark.parametrize("missing", ["name", "fileName", "fileType"])
def test_analyze_inventory_first_call_requires_upload_metadata(services, missing):
    """Reject missing metadata before creating an upload ticket."""

    tickets, _, _ = services
    arguments = {
        "name": "relatório",
        "fileName": "inventorio-principal.xlsx",
        "fileType": "XLSX",
    }
    arguments[missing] = None

    with pytest.raises(ValueError, match=missing):
        inventory_tools._analyze_inventory(12345, **arguments)

    assert tickets.create_calls == []


def test_analyze_inventory_rejects_unknown_file_type(services):
    """Accept only the two supported upload file types."""

    tickets, _, _ = services

    with pytest.raises(ValueError, match="fileType"):
        inventory_tools._analyze_inventory(
            12345,
            name="relatório",
            fileName="inventory.csv",
            fileType="CSV",
        )

    assert tickets.create_calls == []


def test_analyze_inventory_second_call_posts_inventory_and_strips_storage_file(
    services,
):
    """Submit the uploaded file and expose only the inventory contract."""

    tickets, create_inventory, _ = services

    result = inventory_tools._analyze_inventory(12345, ticket="t1")

    assert result == {
        "id": 1,
        "name": "relatório",
        "type": "INPUT",
        "status": "PROCESSING",
        "createdAt": "2026-10-04T19:30:00",
    }
    assert create_inventory.calls == [
        (
            "relatório",
            "inventorio-principal.xlsx",
            "https://cloudinary/sadjasoda",
        )
    ]
    assert tickets.consumed == [("t1", 1)]
    assert "storageFile" not in result and "path" not in result


def test_analyze_inventory_does_not_consume_when_inventory_post_fails(services):
    """Leave an uploaded ticket reusable when inventory creation fails."""

    tickets, create_inventory, _ = services
    create_inventory.error = InventoryError("down")

    with pytest.raises(RuntimeError, match="Inventory submission failed"):
        inventory_tools._analyze_inventory(12345, ticket="t1")

    assert tickets.consumed == []


def test_analyze_inventory_hides_microservice_details_from_the_model(services):
    """Raise a generic error without URLs and leave the ticket unconsumed."""

    tickets, create_inventory, _ = services
    create_inventory.error = InventoryError(
        "The Inventory microservice answered 500 for "
        "http://inventory.test/api/inventories: down"
    )

    with pytest.raises(RuntimeError) as error:
        inventory_tools._analyze_inventory(12345, ticket="t1")

    message = str(error.value)
    assert "inventory.test" not in message
    assert "http" not in message
    assert "down" not in message
    assert not isinstance(error.value, InventoryError)
    assert tickets.consumed == []


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_analyze_inventory_treats_blank_ticket_as_first_call(services, blank):
    """Create a waiting ticket when ticket is None or blank, without posting inventory."""

    tickets, create_inventory, _ = services

    result = inventory_tools._analyze_inventory(
        12345,
        name="relatório",
        fileName="inventorio-principal.xlsx",
        fileType="XLSX",
        ticket=blank,
    )

    assert result == {"ticket": "new-ticket", "state": "waiting_for_upload"}
    assert tickets.create_calls == [
        (12345, "relatório", "inventorio-principal.xlsx", "XLSX")
    ]
    assert tickets.get_calls == []
    assert create_inventory.calls == []


def test_inventory_tool_descriptions_explain_the_two_call_flow(services):
    """Tell the model that the upload continues in the Aether app and how to poll."""

    tools = {tool.name: tool for tool in inventory_tools.get_inventory_ingest_tools()}
    analyze = tools["analyze_inventory"].description
    polling = tools["get_inventory_analysis"].description

    assert "Aether app" in analyze
    assert "get_inventory_analysis" in analyze
    assert "IMAGE" in analyze and "XLSX" in analyze
    assert "PROCESSING" in polling
    assert "analyze_inventory" in polling


@pytest.mark.parametrize(
    "stored",
    [
        uploaded_ticket(state="waiting_for_upload"),
        uploaded_ticket(path=None),
        uploaded_ticket(path=""),
    ],
)
def test_analyze_inventory_rejects_ticket_not_ready_for_upload(services, stored):
    """Reject tickets without a completed upload before posting inventory."""

    tickets, create_inventory, _ = services
    tickets.stored = stored

    with pytest.raises(ValueError, match="upload"):
        inventory_tools._analyze_inventory(12345, ticket="t1")

    assert create_inventory.calls == []


def test_get_inventory_analysis_processing_when_plan_missing(services):
    """Report processing while the improvement plan does not exist."""

    tickets, _, plans = services
    tickets.created = {12345: [1]}
    plans.missing = True

    assert inventory_tools._get_inventory_analysis(12345, 1) == {"status": "PROCESSING"}


def test_get_inventory_analysis_returns_report_contract(services):
    """Return the stable analysis fields from the improvement plan."""

    tickets, _, plans = services
    tickets.created = {12345: [1]}
    plans.plan = ImprovementPlan(
        id_external_inventory=1,
        defined_problem="high scope 1",
        method="replace boilers",
        reasoning="combustion",
    )

    assert inventory_tools._get_inventory_analysis(12345, 1) == {
        "defined_problem": "high scope 1",
        "solving_method": "replace boilers",
        "reasoning": "combustion",
    }


def test_get_inventory_analysis_rejects_id_not_created_here(services):
    """Reject analysis reads for inventories outside the user's tickets."""

    tickets, _, plans = services
    tickets.created = {12345: []}

    with pytest.raises(ValueError, match="inventory"):
        inventory_tools._get_inventory_analysis(12345, 1)

    assert plans.calls == []


@pytest.mark.parametrize("bad", [None, "", "abc", 0, -1, True, 4.2])
def test_inventory_tools_reject_invalid_user_identifiers(services, bad):
    """Reject invalid user identifiers before calling dependencies."""

    tickets, _, plans = services

    with pytest.raises(ValueError, match="id_external_user"):
        inventory_tools._analyze_inventory(
            bad,
            name="relatório",
            fileName="inventory.xlsx",
            fileType="XLSX",
        )
    with pytest.raises(ValueError, match="id_external_user"):
        inventory_tools._get_inventory_analysis(bad, 1)

    assert tickets.create_calls == []
    assert plans.calls == []


def test_get_inventory_analysis_accepts_numeric_identifiers(services):
    """Normalize numeric strings before reading ticket and plan services."""

    tickets, _, plans = services
    tickets.created = {12345: [1]}
    plans.plan = ImprovementPlan(id_external_inventory=1)

    inventory_tools._get_inventory_analysis("12345", "1")

    assert plans.calls == [1]


def test_inventory_tools_raise_when_dependencies_are_unconfigured():
    """Raise clear errors when required dependencies have not been bound."""

    inventory_tools.configure()

    with pytest.raises(RuntimeError, match="ticket"):
        inventory_tools._analyze_inventory(
            1,
            name="report",
            fileName="inventory.xlsx",
            fileType="XLSX",
        )
    inventory_tools.configure(tickets=StubTickets(stored=uploaded_ticket()))
    with pytest.raises(RuntimeError, match="create"):
        inventory_tools._analyze_inventory(12345, ticket="t1")
    tickets = StubTickets()
    tickets.created = {12345: [1]}
    inventory_tools.configure(tickets=tickets)
    with pytest.raises(RuntimeError, match="plan"):
        inventory_tools._get_inventory_analysis(12345, 1)


def test_get_inventory_ingest_tools_exposes_typed_tools_and_descriptions(services):
    """Expose both typed tools using configured environment descriptions."""

    tools = {tool.name: tool for tool in inventory_tools.get_inventory_ingest_tools()}

    assert set(tools) == {"analyze_inventory", "get_inventory_analysis"}
    assert all(isinstance(tool, StructuredTool) for tool in tools.values())
    assert tools["analyze_inventory"].description == (
        tool_constants.ANALYZE_INVENTORY_DESCRIPTION
    )
    assert tools["get_inventory_analysis"].description == (
        tool_constants.GET_INVENTORY_ANALYSIS_DESCRIPTION
    )
    assert set(tools["analyze_inventory"].args) == {
        "id_external_user",
        "name",
        "fileName",
        "fileType",
        "ticket",
    }
    assert set(tools["get_inventory_analysis"].args) == {
        "id_external_user",
        "id",
    }
