"""Coordinate domain operations for improvement plans."""

from improvement_plan.entity import ExtractedInventory, ImprovementPlan, InventoryEmission
from improvement_plan.improvement_plan import (
    IRepository,
    IService,
    MalformedPlanError,
)
from internal.shared import current_id_request, record_aeko_metrics
from user.user import IService as IUserService, UserMemory


class Service(IService):
    def __init__(self, repository: IRepository):
        self.repository = repository

    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        return self.repository.get_by_id_external_inventory(id_external_inventory)

    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        return self.repository.create(improvement_plan)

    def replace(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Replace the plan stored for the same external inventory identifier."""
        return self.repository.replace(improvement_plan)

    def input_inventory(
        self,
        id_external_inventory: int | None,
        inventory: str,
        id_external_user: int,
        gases,
        scopes,
        categories,
        user_service: IUserService,
        aeko_inventory_analyzer_factory,
    ) -> ExtractedInventory:
        """Analyze inventory Markdown with the current plan as context, then store the new plan."""
        if id_external_inventory is None:
            raise ValueError("id_external_inventory is required to analyze an inventory.")
        if not inventory or not str(inventory).strip():
            raise ValueError("inventory is required to analyze an inventory.")

        user = user_service.get_mongo_user(id_external_user)

        existing = _current_plan(self.repository, id_external_inventory)

        aeko_inventory_analyzer = aeko_inventory_analyzer_factory()
        aeko_inventory_analyzer.set_context(_context_from(existing))

        analysis = _analyze(
            aeko_inventory_analyzer,
            inventory,
            id_external_inventory,
            current_id_request(),
            gases,
            scopes,
            categories,
        )

        record_aeko_metrics(analysis.aeko_metrics)

        extracted_inventory = extracted_inventory_from_aeko(analysis.inventory)

        improvement_plan = improvement_plan_from_aeko_plan(analysis.plan)
        if existing is None:
            improvement_plan = self.create(improvement_plan)
        else:
            improvement_plan.id = existing.id
            improvement_plan = self.replace(improvement_plan)

        user_service.create_user_memory(
            UserMemory(
                id=None,
                id_user=user.id,
                field="improvement_plan",
                description=str(improvement_plan)
            )
        )

        return extracted_inventory


def _current_plan(repository: IRepository, id_external_inventory: int) -> ImprovementPlan | None:
    """Return the stored plan for an inventory, or None when that inventory has none yet."""
    try:
        return repository.get_by_id_external_inventory(id_external_inventory)
    except ValueError:
        return None


def _analyze(analyzer, inventory_markdown: str, id_external_inventory: int, id_request: str, gases, scopes, categories):
    """Analyze an inventory and record metrics attached to any raised exception."""

    try:
        return analyzer.analyze(
            inventory_markdown,
            id_external_inventory=id_external_inventory,
            id_request=id_request,
            gases=gases,
            scopes=scopes,
            categories=categories,
        )
    except Exception as exc:
        record_aeko_metrics(getattr(exc, "aeko_metrics", None))
        raise


def improvement_plan_from_aeko_plan(plan) -> ImprovementPlan:
    """Map an SDK plan to a domain plan for persistence."""
    return ImprovementPlan(
        id=None,
        id_external_inventory=plan.id_external_inventory,
        defined_problem=plan.defined_problem,
        method=plan.method,
        reasoning=plan.reasoning,
        updated_at=None
    )


def extracted_inventory_from_aeko(inventory) -> ExtractedInventory:
    """Map an SDK structured inventory to the domain object returned by a report."""
    try:
        return ExtractedInventory(
            description=inventory.description,
            start_period=inventory.start_period,
            end_period=inventory.end_period,
            emissions=[
                InventoryEmission(
                    quantity_co2e=item.quantity_co2e,
                    methodology_description=item.methodology_description,
                    supplier_data_percentage=item.supplier_data_percentage,
                    gas=item.gas,
                    scope=item.scope,
                    category=item.category,
                    is_upstream=item.is_upstream,
                    is_reduction=item.is_reduction,
                )
                for item in inventory.emissions
            ],
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise MalformedPlanError(
            "The analysis produced no inventory in the shape a report is returned in."
        ) from exc


def _context_from(previous_plan: ImprovementPlan | None) -> str:
    """Render the current plan as analysis context, or empty text when absent."""
    if previous_plan is None:
        return ""
    return "\n".join(
        [
            f"Relatório anterior (inventário {previous_plan.id_external_inventory}, atualizado em {previous_plan.updated_at}):",
            f"Problema identificado: {previous_plan.defined_problem}",
            f"Método: {previous_plan.method}",
            f"Justificativa: {previous_plan.reasoning}",
        ]
    )
