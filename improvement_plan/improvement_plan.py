"""Define improvement-plan service and repository contracts.

Plans are stored in MongoDB. Inventory Markdown arrives on the report request
and is not resolved through another service.
"""

from abc import ABC, abstractmethod

from improvement_plan.entity import ExtractedInventory, ImprovementPlan
from user.user import IService as IUserService


class MalformedPlanError(Exception):
    """Raised when analysis produces no persistable plan or structured inventory."""

class IRepository(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        pass

    @abstractmethod
    def replace(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Replace the plan stored for the same external inventory identifier."""
        pass

class IService(ABC):
    @abstractmethod
    def get_by_id_external_inventory(self, id_external_inventory) -> ImprovementPlan:
        """Retrieve the improvement plan associated with an external inventory identifier."""
        pass

    @abstractmethod
    def create(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Persist an improvement plan and return the stored entity."""
        pass

    @abstractmethod
    def replace(self, improvement_plan: ImprovementPlan) -> ImprovementPlan:
        """Replace the plan stored for the same external inventory identifier."""
        pass

    @abstractmethod
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
        pass
