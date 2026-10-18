"""Define service and repository contracts for users and memories."""

from abc import ABC, abstractmethod
from user.entity import User, UserMemory

class IRepository(ABC):
    @abstractmethod
    def get_user(self, id_external_user) -> User:
        """Retrieve a user by external identifier."""
        pass

    @abstractmethod
    def create_user(
        self,
        id_external_user: int,
        role: str,
        usecase: str,
        *,
        id_external_company: int | None = None,
    ) -> User:
        """Persist a new user with the supplied profile fields."""
        pass

    @abstractmethod
    def update_user_profile(
        self,
        id_external_user: int,
        *,
        role: str | None = None,
        usecase: str | None = None,
    ) -> User:
        """Persist only the supplied profile fields on the user document."""
        pass

    @abstractmethod
    def sync_sign_in_profile(
        self,
        id_external_user: int,
        *,
        id_external_company: int,
    ) -> None:
        """Persist the company id after OAuth Sign in."""
        pass

    @abstractmethod
    def get_user_by_id(self, id_user: str) -> User:
        """Retrieve a user by internal identifier, returning None when absent."""
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        pass

    @abstractmethod
    def set_id_external_company(self, id_user: str, id_external_company: int) -> None:
        """Persist the company identifier on the user document."""
        pass

class IService(ABC):
    @abstractmethod
    def get_mongo_user(self, id_external_user) -> User:
        """Retrieve the stored user matching an external identifier."""
        pass

    @abstractmethod
    def get_mongo_user_or_create(
        self,
        id_external_user: int,
        role: str,
        usecase: str,
        *,
        id_external_company: int | None = None,
    ) -> User:
        """Return the stored user or create one with the supplied profile fields."""
        pass

    @abstractmethod
    def update_user_profile(
        self,
        id_external_user: int,
        *,
        role: str | None = None,
        usecase: str | None = None,
    ) -> User:
        """Persist only the supplied profile fields on the user document."""
        pass

    @abstractmethod
    def apply_sign_in_profile(
        self,
        id_external_user: int,
        *,
        ms_auth_profile: dict,
    ) -> User:
        """Create or refresh the user from ms-auth after each OAuth Sign in."""
        pass

    @abstractmethod
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        pass

    @abstractmethod
    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        pass

    @abstractmethod
    def set_id_external_company(self, id_user: str, id_external_company: int) -> None:
        """Persist the company identifier on the user."""
        pass
