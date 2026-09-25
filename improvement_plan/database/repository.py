"""Persist and retrieve improvement plans through MongoDB."""

from improvement_plan.database import query as q
from improvement_plan.entity import ImprovementPlan
from improvement_plan.improvement_plan import IRepository
from internal.shared import Module, logged


class Repository(IRepository):
    def __init__(self, db):
        self.db = db

    @logged(Module.DATABASE, "improvement_plan.get_by_id_external_inventory")
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        try:
            query, projection = q.get_by_id_external_inventory_query(id_external_inventory)
            improvement_plan_data = self.db["improvement_plan"].find_one(query, projection)
            if not improvement_plan_data:
                raise ValueError(f"Improvement plan with id_external_inventory {id_external_inventory} not found.")
            return improvement_plan_from_data(improvement_plan_data)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching improvement plan from database: {e}")

    @logged(Module.DATABASE, "improvement_plan.create")
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        try:
            improvement_plan_data = q.create_improvement_plan_query(improvement_plan)
            result = self.db["improvement_plan"].insert_one(improvement_plan_data)
            improvement_plan.id = str(result.inserted_id)
            return improvement_plan
        except Exception as e:
            raise RuntimeError(f"Error creating improvement plan in database: {e}")

    @logged(Module.DATABASE, "improvement_plan.replace")
    def replace(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Replace the plan stored for the same external inventory identifier."""
        try:
            query, document = q.replace_improvement_plan_query(improvement_plan)
            self.db["improvement_plan"].replace_one(query, document)
            return improvement_plan
        except Exception as e:
            raise RuntimeError(f"Error replacing improvement plan in database: {e}")


def improvement_plan_from_data(data: dict) -> ImprovementPlan:
    """Map a MongoDB document to an improvement plan entity."""
    return ImprovementPlan(
        id=str(data.get("_id")) if data.get("_id") is not None else None,
        id_external_inventory=data.get("id_external_inventory"),
        id_external_unit=data.get("id_external_unit"),
        defined_problem=data.get("defined_problem", ""),
        method=data.get("method", ""),
        reasoning=data.get("reasoning", ""),
        updated_at=data.get("updated_at"),
    )
