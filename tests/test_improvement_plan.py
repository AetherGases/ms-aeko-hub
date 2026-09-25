"""Verify improvement plan behavior and error handling."""

import importlib.util
import inspect
from datetime import datetime

import pytest

from improvement_plan.database import query as q
from improvement_plan.database.repository import Repository, improvement_plan_from_data
from improvement_plan.entity import ExtractedInventory, ImprovementPlan, InventoryEmission
from improvement_plan.improvement_plan import (
    IRepository,
    IService,
)
from improvement_plan.service import Service
from internal.shared.event_tracking import (
    bind_id_request,
    set_aeko_metrics_sink,
    unbind_id_request,
)
from tests.mongo_doubles import StubCollection, StubDatabase
from user.entity import User, UserMemory

UPDATED_AT = datetime(2026, 7, 26, 14, 30, 0)

ID_USER = "u1"
ID_EXTERNAL_USER = 12345
ID_INVENTORY = 502

INVENTORY_MARKDOWN = "## Escopo 1\n\n| Fonte | tCO2e |\n| --- | --- |\n| Caldeira | 12400 |"

GASES = [{"id": 1, "name": "CO2"}]
SCOPES = [{"id": 1, "name": "Escopo 1"}]
CATEGORIES = [{"id": 1, "name": "Combustão estacionária", "classification": None}]

PLAN_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c020",
    "id_external_inventory": 1,
    "id_external_unit": 77,
    "defined_problem": "high scope 1 emissions",
    "method": "PDCA",
    "reasoning": "boiler replacement cuts direct emissions",
    "updated_at": UPDATED_AT,
}

USER = User(id=ID_USER, id_external_user=ID_EXTERNAL_USER, role="analyst", usecase="report_generation")


def previous_plan(id_external_inventory, defined_problem, method, reasoning, updated_at=UPDATED_AT):
    """Build a previous improvement plan for context assertions."""
    return ImprovementPlan(
        id=f"plan-{id_external_inventory}",
        id_external_inventory=id_external_inventory,
        defined_problem=defined_problem,
        method=method,
        reasoning=reasoning,
        updated_at=updated_at,
    )


class StubPlanRepository:
    def __init__(self, result=None, existing=None):
        self.result = result
        self.existing = existing
        self.calls = []

    def get_by_id_external_inventory(self, id_external_inventory):
        """Retrieve the improvement plan associated with an external inventory identifier."""
        self.calls.append(("get", id_external_inventory))
        if self.existing is None:
            raise ValueError(
                f"Improvement plan with id_external_inventory {id_external_inventory} not found."
            )
        return self.existing

    def create(self, improvement_plan):
        """Persist an improvement plan and return the stored entity."""
        self.calls.append(("create", improvement_plan))
        if self.result is not None:
            return self.result
        improvement_plan.id = "created-plan"
        self.existing = improvement_plan
        return improvement_plan

    def replace(self, improvement_plan):
        """Replace the plan stored for the same external inventory identifier."""
        self.calls.append(("replace", improvement_plan))
        if self.result is not None:
            return self.result
        improvement_plan.id = improvement_plan.id or "replaced-plan"
        self.existing = improvement_plan
        return improvement_plan


class StubPlan:
    """Stands in for the `AekoImprovementPlan` the SDK returns."""

    def __init__(self, id_external_inventory=ID_INVENTORY):
        self.id = None
        self.id_external_inventory = id_external_inventory
        self.defined_problem = "high scope 1 emissions"
        self.method = "replace the boiler fleet"
        self.reasoning = "direct combustion dominates the inventory"


class StubEmission:
    def __init__(self):
        self.quantity_co2e = 12400.0
        self.methodology_description = "stationary combustion"
        self.supplier_data_percentage = None
        self.gas = 1
        self.scope = 1
        self.category = None
        self.is_upstream = None
        self.is_reduction = False


class StubInventory:
    """Stands in for the `AekoExtractedInventory` the SDK returns."""

    def __init__(self):
        self.description = "Boiler-dominated inventory"
        self.start_period = "2025-01-01"
        self.end_period = "2025-12-31"
        self.emissions = [StubEmission()]


class StubMetrics:
    """Stands in for the `AekoMetrics` the SDK reports an analysis with."""

    def __init__(self, id_request="", error_description=None):
        self.id_request = id_request
        self.latency = 12
        self.error_description = error_description
        self.flow = "analytical"
        self.used_agents = []


class StubAnalysis:
    """Stands in for the `AekoAnalysisResponse` 3.5 hands back."""

    def __init__(self, plan, aeko_metrics, inventory=None):
        self.plan = plan
        self.inventory = inventory or StubInventory()
        self.aeko_metrics = aeko_metrics


class StubAnalyzer:
    def __init__(self, plan=None, error=None, inventory=None):
        self.plan = plan or StubPlan()
        self.error = error
        self.inventory = inventory or StubInventory()

        self.context = None
        self.analyzed = []

    def set_context(self, context):
        """Record the analysis context supplied by the service."""
        self.context = context

    def analyze(self, inventory, *, id_external_inventory, id_request, gases, scopes, categories):
        """Record the inventory analysis call and return or raise its scripted result."""
        self.analyzed.append((inventory, id_external_inventory, id_request, gases, scopes, categories))
        if self.error is not None:
            raise self.error
        return StubAnalysis(self.plan, StubMetrics(id_request=id_request), self.inventory)


class StubAnalyzerFactory:
    def __init__(self, plan=None, error=None, inventory=None):
        self.plan = plan
        self.error = error
        self.inventory = inventory
        self.built = []

    def __call__(self):
        analyzer = StubAnalyzer(self.plan, self.error, self.inventory)
        self.built.append(analyzer)
        return analyzer

    @property
    def last(self):
        """Return the most recently created test instance."""
        return self.built[-1]


class StubUserService:
    def __init__(self, user=USER):
        self.user = user
        self.memories = []

    def get_mongo_user(self, id_external_user):
        """Retrieve the stored user matching an external identifier."""
        if self.user is None:
            raise ValueError(f"User with id_external_user {id_external_user} not found.")
        return self.user

    def get_user_memories(self, id_user):
        """Retrieve the memories stored for a user."""
        return self.memories

    def create_user_memory(self, user_memory):
        """Persist a memory associated with a user."""
        self.memories.append(user_memory)


def build_repository(collection=None):
    """Build a repository backed by configurable MongoDB doubles."""
    collection = collection or StubCollection()
    return Repository(StubDatabase(improvement_plan=collection)), collection


def build_service(repository=None):
    """Build a domain service with a configurable repository double."""
    return Service(repository or StubPlanRepository())


def run(repository=None, analyzers=None, users=None, id_external_inventory=ID_INVENTORY,
        inventory=INVENTORY_MARKDOWN, gases=None, scopes=None, categories=None):
    """Execute the scenario under test."""
    service = build_service(repository)
    return service.input_inventory(
        id_external_inventory,
        inventory,
        ID_EXTERNAL_USER,
        gases if gases is not None else GASES,
        scopes if scopes is not None else SCOPES,
        categories if categories is not None else CATEGORIES,
        users or StubUserService(),
        analyzers or StubAnalyzerFactory(),
    )


def test_entity_defaults_to_an_empty_plan():
    """Verify that entity defaults to an empty plan."""
    plan = ImprovementPlan()

    assert (plan.id, plan.id_external_inventory, plan.updated_at) == (None, None, None)
    assert plan.id_external_unit is None
    assert (plan.defined_problem, plan.method, plan.reasoning) == ("", "", "")


def test_entity_renders_every_field_as_text():
    """Verify that entity renders every field as text."""
    plan = ImprovementPlan(
        id="p1",
        id_external_inventory=1,
        id_external_unit=77,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
    )

    rendered = str(plan)

    assert rendered.startswith("ImprovementPlan(")
    assert "id_external_inventory=1" in rendered
    assert "id_external_unit=77" in rendered
    assert "'problem'" in rendered


def test_extracted_inventory_defaults_to_empty_emissions():
    """Verify that extracted inventory defaults to empty emissions."""
    inventory = ExtractedInventory()

    assert (inventory.description, inventory.start_period, inventory.end_period) == (None, None, None)
    assert inventory.emissions == []


def test_repository_and_service_implement_their_interfaces():
    """Verify that repository and service implement their interfaces."""
    assert issubclass(Repository, IRepository)
    assert issubclass(Service, IService)
    assert Repository.__abstractmethods__ == frozenset()
    assert Service.__abstractmethods__ == frozenset()


def test_input_inventory_signature_matches_the_interface():
    """Verify that input inventory signature matches the interface."""
    interface = inspect.signature(IService.input_inventory).parameters
    implementation = inspect.signature(Service.input_inventory).parameters

    assert list(interface) == list(implementation)
    assert "aeko_inventory_analyzer_factory" in interface
    assert "id_external_inventory" in interface
    assert "inventory" in interface
    assert "id_external_user" in interface
    assert "gases" in interface
    assert "scopes" in interface
    assert "categories" in interface
    assert "id_external_unit" not in interface
    assert "s3" not in interface


def test_the_flow_no_longer_lives_in_its_own_package():
    """Verify that inventory analysis belongs to the improvement-plan domain."""
    assert importlib.util.find_spec("inventory_analysis") is None


def test_the_inventory_is_not_resolved_through_another_service():
    """Verify that the inventory is not resolved through another service."""
    from pathlib import Path

    assert not (Path(__file__).resolve().parents[1] / "improvement_plan" / "integration").exists()


def test_get_by_id_external_inventory_returns_the_plan():
    """Verify that get by id external inventory returns the plan."""
    repository, _ = build_repository(StubCollection(find_one_result=PLAN_DOCUMENT))

    plan = repository.get_by_id_external_inventory(1)

    assert isinstance(plan, ImprovementPlan)
    assert plan.id == "65a8b3d6c0f8e1d7f4b2c020"
    assert plan.method == "PDCA"
    assert plan.id_external_unit == 77
    assert plan.updated_at == UPDATED_AT


def test_get_by_id_external_inventory_queries_by_the_external_inventory():
    """Verify that get by id external inventory queries by the external inventory."""
    repository, collection = build_repository(StubCollection(find_one_result=PLAN_DOCUMENT))

    repository.get_by_id_external_inventory(1)

    assert collection.call_args("find_one")[0][0] == {"id_external_inventory": 1}


def test_get_by_id_external_inventory_raises_value_error_when_not_found():
    """Verify that get by id external inventory raises value error when not found."""
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match="not found"):
        repository.get_by_id_external_inventory(1)


def test_get_by_id_external_inventory_wraps_database_failures():
    """Verify that get by id external inventory wraps database failures."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_by_id_external_inventory(1)


def test_create_stores_the_plan_and_returns_it_with_an_identifier():
    """Verify that create stores the plan and returns it with an identifier."""
    repository, collection = build_repository(StubCollection(inserted_id="65a8b3d6c0f8e1d7f4b2c020"))
    plan = ImprovementPlan(
        id_external_inventory=1,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
    )

    created = repository.create(plan)

    assert created is plan
    assert created.id == "65a8b3d6c0f8e1d7f4b2c020"
    assert collection.call_args("insert_one")[0][0]["method"] == "PDCA"


def test_create_wraps_database_failures():
    """Verify that create wraps database failures."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create(ImprovementPlan())


def test_replace_overwrites_the_plan_for_that_inventory():
    """Verify that replace overwrites the plan for that inventory."""
    repository, collection = build_repository()
    plan = ImprovementPlan(
        id="65a8b3d6c0f8e1d7f4b2c020",
        id_external_inventory=1,
        defined_problem="new problem",
        method="new method",
        reasoning="new reasoning",
    )

    replaced = repository.replace(plan)

    assert replaced is plan
    assert collection.call_args("replace_one")[0][0] == {"id_external_inventory": 1}
    assert collection.call_args("replace_one")[0][1]["defined_problem"] == "new problem"


def test_replace_wraps_database_failures():
    """Verify that replace wraps database failures."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.replace(ImprovementPlan(id_external_inventory=1))


def test_improvement_plan_from_data_handles_a_document_without_an_identifier():
    """Verify that improvement plan from data handles a document without an identifier."""
    plan = improvement_plan_from_data({"id_external_inventory": 2})

    assert plan.id is None
    assert plan.id_external_unit is None
    assert plan.defined_problem == ""


def test_get_by_id_external_inventory_query():
    """Verify that get by id external inventory query."""
    assert q.get_by_id_external_inventory_query(7) == ({"id_external_inventory": 7}, {})


def test_create_improvement_plan_query_maps_every_field_the_flow_persists():
    """Verify that create improvement plan query maps every field the flow persists."""
    plan = ImprovementPlan(
        id="p1",
        id_external_inventory=1,
        id_external_unit=77,
        defined_problem="problem",
        method="PDCA",
        reasoning="why",
        updated_at=UPDATED_AT,
    )

    document = q.create_improvement_plan_query(plan)

    assert document == {
        "id_external_inventory": 1,
        "defined_problem": "problem",
        "method": "PDCA",
        "reasoning": "why",
        "updated_at": UPDATED_AT,
    }
    assert "id_external_unit" not in document


def test_create_improvement_plan_query_stamps_a_missing_update_timestamp():
    """Verify that create improvement plan query stamps a missing update timestamp."""
    document = q.create_improvement_plan_query(ImprovementPlan(id_external_inventory=1))

    assert isinstance(document["updated_at"], datetime)


def test_create_improvement_plan_query_leaves_out_what_the_plan_does_not_carry():
    """Verify that create improvement plan query leaves out what the plan does not carry."""
    document = q.create_improvement_plan_query(ImprovementPlan(id_external_inventory=1))

    assert None not in document.values()


def test_create_improvement_plan_query_keeps_the_external_identifier_a_number():
    """Verify that create improvement plan query keeps the external identifier a number."""
    document = q.create_improvement_plan_query(ImprovementPlan(id_external_inventory=7))

    assert isinstance(document["id_external_inventory"], int)


def test_service_get_delegates_to_the_repository():
    """Verify that service get delegates to the repository."""
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(existing=plan)

    assert build_service(repository).get_by_id_external_inventory(1) is plan
    assert repository.calls == [("get", 1)]


def test_service_create_delegates_to_the_repository():
    """Verify that service create delegates to the repository."""
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert build_service(repository).create(plan) is plan
    assert repository.calls == [("create", plan)]


def test_service_replace_delegates_to_the_repository():
    """Verify that service replace delegates to the repository."""
    plan = ImprovementPlan(id="p1")
    repository = StubPlanRepository(result=plan)

    assert build_service(repository).replace(plan) is plan
    assert repository.calls == [("replace", plan)]


def test_analyze_receives_the_inventory_as_markdown():
    """Verify that analyze receives the inventory as markdown."""
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    inventory, _, _, _, _, _ = analyzers.last.analyzed[0]
    assert inventory == INVENTORY_MARKDOWN


def test_analyze_receives_the_inventory_identifier():
    """Verify that analyze receives the inventory identifier."""
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    _, id_external_inventory, _, _, _, _ = analyzers.last.analyzed[0]
    assert id_external_inventory == ID_INVENTORY


def test_analyze_receives_the_catalogs_from_the_request():
    """Verify that analyze receives the catalogs from the request."""
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)

    _, _, _, gases, scopes, categories = analyzers.last.analyzed[0]
    assert gases == GASES
    assert scopes == SCOPES
    assert categories == CATEGORIES


def test_every_report_gets_a_fresh_analyzer():
    """Verify that every report gets a fresh analyzer."""
    analyzers = StubAnalyzerFactory()

    run(analyzers=analyzers)
    run(analyzers=analyzers)

    assert len(analyzers.built) == 2


def test_the_current_plan_of_the_inventory_becomes_context():
    """Verify that the current plan of the inventory becomes context."""
    analyzers = StubAnalyzerFactory()
    repository = StubPlanRepository(
        existing=previous_plan(ID_INVENTORY, "boiler still burning", "swap for heat pumps", "scope 1 dominates")
    )

    run(repository=repository, analyzers=analyzers)

    context = analyzers.last.context
    assert "boiler still burning" in context
    assert "swap for heat pumps" in context
    assert "scope 1 dominates" in context
    assert all(call[0] != "get_last" for call in repository.calls)


def test_the_context_is_empty_when_the_inventory_has_no_plan():
    """Verify that the context is empty when the inventory has no plan."""
    analyzers = StubAnalyzerFactory()

    run(repository=StubPlanRepository(), analyzers=analyzers)

    assert analyzers.last.context == ""


def test_an_inventory_without_an_identifier_is_rejected():
    """Verify that an inventory without an identifier is rejected."""
    with pytest.raises(ValueError, match="id_external_inventory"):
        run(id_external_inventory=None)


def test_an_empty_inventory_is_rejected_before_the_analyzer():
    """Verify that an empty inventory is rejected before the analyzer."""
    analyzers = StubAnalyzerFactory()

    with pytest.raises(ValueError, match="inventory"):
        run(inventory="  ", analyzers=analyzers)

    assert analyzers.built == []


def test_a_missing_user_is_rejected_before_the_analyzer():
    """Verify that a missing user is rejected before the analyzer."""
    analyzers = StubAnalyzerFactory()

    with pytest.raises(ValueError, match="not found"):
        run(users=StubUserService(user=None), analyzers=analyzers)

    assert analyzers.built == []


def test_the_plan_is_persisted_field_by_field():
    """Verify that the plan is persisted field by field."""
    repository = StubPlanRepository()

    run(repository=repository)

    (plan,) = [call[1] for call in repository.calls if call[0] == "create"]
    assert isinstance(plan, ImprovementPlan)
    assert plan.id_external_inventory == ID_INVENTORY
    assert plan.id_external_unit is None
    assert plan.defined_problem == "high scope 1 emissions"
    assert plan.method == "replace the boiler fleet"
    assert plan.reasoning == "direct combustion dominates the inventory"


def test_a_successful_reanalysis_replaces_the_plan():
    """Verify that a successful reanalysis replaces the plan."""
    existing = previous_plan(ID_INVENTORY, "old problem", "old method", "old reasoning")
    repository = StubPlanRepository(existing=existing)

    run(repository=repository)

    assert [call[0] for call in repository.calls if call[0] in {"create", "replace"}] == ["replace"]
    (plan,) = [call[1] for call in repository.calls if call[0] == "replace"]
    assert plan.defined_problem == "high scope 1 emissions"
    assert plan.id == existing.id


def test_a_failing_analysis_does_not_replace_the_plan():
    """Verify that a failing analysis does not replace the plan."""
    existing = previous_plan(ID_INVENTORY, "old problem", "old method", "old reasoning")
    repository = StubPlanRepository(existing=existing)

    with pytest.raises(RuntimeError, match="coordinator never produced the plan"):
        run(
            repository=repository,
            analyzers=StubAnalyzerFactory(error=RuntimeError("coordinator never produced the plan")),
        )

    assert [call[0] for call in repository.calls if call[0] in {"create", "replace"}] == []
    assert repository.existing is existing


def test_the_plan_is_remembered_for_the_user():
    """Verify that the plan is remembered for the user."""
    users = StubUserService()

    run(users=users)

    memory = users.memories[0]
    assert isinstance(memory, UserMemory)
    assert memory.id_user == ID_USER
    assert memory.field == "improvement_plan"
    assert "high scope 1 emissions" in memory.description


def test_the_structured_inventory_is_returned():
    """Verify that the structured inventory is returned."""
    inventory = run()

    assert isinstance(inventory, ExtractedInventory)
    assert inventory.description == "Boiler-dominated inventory"
    assert inventory.start_period == "2025-01-01"
    assert inventory.end_period == "2025-12-31"
    assert isinstance(inventory.emissions[0], InventoryEmission)
    assert inventory.emissions[0].quantity_co2e == 12400.0
    assert inventory.emissions[0].is_reduction is False


def test_a_failing_analyzer_is_surfaced():
    """Verify that a failing analyzer is surfaced."""
    with pytest.raises(RuntimeError, match="coordinator never produced the plan"):
        run(analyzers=StubAnalyzerFactory(error=RuntimeError("coordinator never produced the plan")))


@pytest.fixture
def recorded_metrics():
    """Capture SDK run metrics for the duration of the test."""
    metrics = []
    set_aeko_metrics_sink(metrics.append)
    yield metrics
    set_aeko_metrics_sink(None)


def test_the_analyzer_is_handed_the_identifier_the_request_is_tracked_under():
    """Verify that the analyzer is handed the identifier the request is tracked under."""
    analyzers = StubAnalyzerFactory()
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        run(analyzers=analyzers)
    finally:
        unbind_id_request(token)

    assert analyzers.last.analyzed[0][2] == "65a8b3d6c0f8e1d7f4b2c0aa"


def test_an_analysis_records_what_it_cost(recorded_metrics):
    """Verify that an analysis records what it cost."""
    token = bind_id_request("65a8b3d6c0f8e1d7f4b2c0aa")

    try:
        run()
    finally:
        unbind_id_request(token)

    assert [metrics.id_request for metrics in recorded_metrics] == ["65a8b3d6c0f8e1d7f4b2c0aa"]
    assert recorded_metrics[0].flow == "analytical"


def test_an_analysis_that_raised_records_the_tracking_it_carried_out(recorded_metrics):
    """Verify that an analysis that raised records the tracking it carried out."""
    error = RuntimeError("coordinator never produced the plan")
    error.aeko_metrics = StubMetrics(error_description="MalformedAgentOutputError: no sections")

    with pytest.raises(RuntimeError):
        run(analyzers=StubAnalyzerFactory(error=error))

    assert [metrics.error_description for metrics in recorded_metrics] == [
        "MalformedAgentOutputError: no sections"
    ]


def test_a_failure_carrying_no_tracking_records_nothing(recorded_metrics):
    """Verify that a failure carrying no tracking records nothing."""
    with pytest.raises(RuntimeError):
        run(analyzers=StubAnalyzerFactory(error=RuntimeError("gemini down")))

    assert recorded_metrics == []


def test_a_recording_that_fails_never_takes_the_analysis_down():
    """Verify that a recording that fails never takes the analysis down."""
    def explode(metrics):
        """Raise the configured failure to exercise error handling."""
        raise RuntimeError("mongo is down")

    set_aeko_metrics_sink(explode)

    try:
        assert run().description == "Boiler-dominated inventory"
    finally:
        set_aeko_metrics_sink(None)
