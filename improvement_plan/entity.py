"""Define the domain entities for improvement plans and extracted inventories."""

from datetime import datetime

class ImprovementPlan:
    id: str | None
    id_external_inventory: int | None
    id_external_unit: int | None
    defined_problem: str
    method: str
    reasoning: str
    updated_at: datetime | None

    def __init__(self, id: str | None = None, id_external_inventory: int | None = None, id_external_unit: int | None = None, defined_problem: str = "", method: str = "", reasoning: str = "", updated_at: datetime | None = None):
        self.id = id
        self.id_external_inventory = id_external_inventory
        self.id_external_unit = id_external_unit
        self.defined_problem = defined_problem
        self.method = method
        self.reasoning = reasoning
        self.updated_at = updated_at

    def __str__(self) -> str:
        return (
            "ImprovementPlan("
            f"id={self.id}, "
            f"id_external_inventory={self.id_external_inventory}, "
            f"id_external_unit={self.id_external_unit}, "
            f"defined_problem={self.defined_problem!r}, "
            f"method={self.method!r}, "
            f"reasoning={self.reasoning!r}, "
            f"updated_at={self.updated_at!r}"
            ")"
        )


class InventoryEmission:
    quantity_co2e: float
    methodology_description: str | None
    supplier_data_percentage: float | None
    gas: int | None
    scope: int | None
    category: int | None
    is_upstream: bool | None
    is_reduction: bool

    def __init__(
        self,
        quantity_co2e: float,
        methodology_description: str | None = None,
        supplier_data_percentage: float | None = None,
        gas: int | None = None,
        scope: int | None = None,
        category: int | None = None,
        is_upstream: bool | None = None,
        is_reduction: bool = False,
    ):
        self.quantity_co2e = quantity_co2e
        self.methodology_description = methodology_description
        self.supplier_data_percentage = supplier_data_percentage
        self.gas = gas
        self.scope = scope
        self.category = category
        self.is_upstream = is_upstream
        self.is_reduction = is_reduction


class ExtractedInventory:
    description: str | None
    start_period: str | None
    end_period: str | None
    emissions: list[InventoryEmission]

    def __init__(
        self,
        description: str | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        emissions: list[InventoryEmission] | None = None,
    ):
        self.description = description
        self.start_period = start_period
        self.end_period = end_period
        self.emissions = list(emissions or [])
