"""Coordinate domain operations for users and memories."""

from cmd.api.integrations.profile_api import sign_in_profile_sync
from user.entity import User, UserMemory
from user.user import IService


def _nonempty_string(value: str, field: str) -> str:
    """Return a trimmed string or reject blank supplied values."""
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must be a nonempty string.")
    return stripped


class Service(IService):
    def __init__(self, repository):
        """Bind the user repository."""
        self.repository = repository

    def get_mongo_user(self, id_external_user) -> User:
        """Retrieve the stored user matching an external identifier."""
        try:
            return self.repository.get_user(id_external_user)
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(f"Error retrieving user: {e}")

    def get_mongo_user_or_create(
        self,
        id_external_user: int,
        role: str,
        usecase: str,
        *,
        id_external_company: int | None = None,
    ) -> User:
        """Return the stored user or create one, syncing company when supplied."""
        try:
            user = self.get_mongo_user(id_external_user)
        except ValueError:
            try:
                create_kwargs: dict = {}
                if id_external_company is not None:
                    create_kwargs["id_external_company"] = id_external_company
                return self.repository.create_user(
                    id_external_user,
                    role,
                    usecase,
                    **create_kwargs,
                )
            except Exception as e:
                raise RuntimeError(f"Error creating user: {e}")
        if id_external_company is None:
            return user
        self.repository.sync_sign_in_profile(
            id_external_user,
            id_external_company=id_external_company,
        )
        return self.get_mongo_user(id_external_user)

    def update_user_profile(
        self,
        id_external_user: int,
        *,
        role: str | None = None,
        usecase: str | None = None,
    ) -> User:
        """Persist only the supplied profile fields on the user document."""
        if role is None and usecase is None:
            raise ValueError("At least one of role or usecase must be supplied.")
        update_role = _nonempty_string(role, "role") if role is not None else None
        update_usecase = (
            _nonempty_string(usecase, "usecase") if usecase is not None else None
        )
        try:
            self.repository.update_user_profile(
                id_external_user,
                role=update_role,
                usecase=update_usecase,
            )
            return self.get_mongo_user(id_external_user)
        except ValueError as ve:
            raise ve
        except Exception as e:
            raise RuntimeError(f"Error updating user profile: {e}")

    def apply_sign_in_profile(
        self,
        id_external_user: int,
        *,
        ms_auth_profile: dict,
    ) -> User:
        """Create or refresh the user from ms-auth after each OAuth Sign in."""
        sync_fields = sign_in_profile_sync(ms_auth_profile)
        try:
            self.repository.sync_sign_in_profile(
                id_external_user,
                id_external_company=sync_fields["id_external_company"],
            )
            return self.get_mongo_user(id_external_user)
        except ValueError:
            return self.repository.create_user(
                id_external_user,
                "",
                "",
                id_external_company=sync_fields["id_external_company"],
            )

    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        try:
            return self.repository.get_user_memories(id_user)
        except Exception as e:
            raise RuntimeError(f"Error retrieving user memories: {e}")

    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        try:
            self.repository.create_user_memory(user_memory)
        except Exception as e:
            raise RuntimeError(f"Error creating user memory: {e}")

    def set_id_external_company(self, id_user: str, id_external_company: int) -> None:
        """Persist the company identifier on the user."""
        try:
            self.repository.set_id_external_company(id_user, id_external_company)
        except Exception as e:
            raise RuntimeError(f"Error updating user company: {e}")
