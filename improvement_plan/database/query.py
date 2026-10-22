"""Build MongoDB filters and documents for improvement plans."""

from datetime import datetime

from improvement_plan.entity import ImprovementPlan


def get_by_id_external_inventory_query(id_external_inventory: int) -> tuple[dict, dict]:
    """Build the filter and projection for a plan associated with an external inventory."""
    return {
        "id_external_inventory": id_external_inventory,
    }, {}


def get_improvement_plan_problem_query(id_external_inventory: int) -> tuple[dict, dict]:
    """Build the filter and projection for an inventory plan's defined problem."""
    query, _ = get_by_id_external_inventory_query(id_external_inventory)
    return query, {
        "_id": 0,
        "id_external_inventory": 1,
        "defined_problem": 1,
    }


def get_improvement_plan_method_query(id_external_inventory: int) -> tuple[dict, dict]:
    """Build the filter and projection for an inventory plan's method."""
    query, _ = get_by_id_external_inventory_query(id_external_inventory)
    return query, {
        "_id": 0,
        "id_external_inventory": 1,
        "method": 1,
    }


def get_improvement_plan_reasoning_query(
    id_external_inventory: int,
) -> tuple[dict, dict]:
    """Build the filter and projection for an inventory plan's reasoning."""
    query, _ = get_by_id_external_inventory_query(id_external_inventory)
    return query, {
        "_id": 0,
        "id_external_inventory": 1,
        "reasoning": 1,
    }


def get_latest_improvement_plans_query(id_external_company: int) -> tuple[dict, dict]:
    """Build a company-scoped filter and list projection for the most recent plans."""
    return {
        "id_external_company": id_external_company,
    }, {
        "_id": 0,
        "id_external_inventory": 1,
        "defined_problem": 1,
        "method": 1,
        "reasoning": 1,
        "updated_at": 1,
    }


def create_improvement_plan_query(improvement_plan: ImprovementPlan) -> dict:
    """Build a plan document with the persistence timestamp."""
    document = {
        "id_external_inventory": improvement_plan.id_external_inventory,
        "id_external_company": improvement_plan.id_external_company,
        "defined_problem": improvement_plan.defined_problem,
        "method": improvement_plan.method,
        "reasoning": improvement_plan.reasoning,
        "updated_at": improvement_plan.updated_at or datetime.utcnow(),
    }

    return {field: value for field, value in document.items() if value is not None}


def replace_improvement_plan_query(
    improvement_plan: ImprovementPlan,
) -> tuple[dict, dict]:
    """Build the filter and replacement document for an inventory's current plan."""
    return {
        "id_external_inventory": improvement_plan.id_external_inventory,
    }, create_improvement_plan_query(improvement_plan)
