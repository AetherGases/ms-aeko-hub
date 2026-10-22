"""Persist and retrieve users and memories through MongoDB."""

from internal.shared import Module, logged
from user.database import query as q
from user.entity import User, UserMemory
from user.user import IRepository


class Repository(IRepository):
    def __init__(self, db):
        """Bind the MongoDB database handle."""
        self.db = db

    @logged(Module.DATABASE, "user.create_user")
    def create_user(
        self,
        id_external_user: int,
        role: str,
        usecase: str,
        *,
        id_external_company: int | None = None,
    ) -> User:
        """Persist a new user and return the stored entity."""
        try:
            document = q.create_user_query(
                id_external_user,
                role,
                usecase,
                id_external_company=id_external_company,
            )
            result = self.db.user.insert_one(document)
            return user_from_data({**document, "_id": result.inserted_id})
        except Exception as e:
            raise RuntimeError(f"Error creating user in database: {e}")

    @logged(Module.DATABASE, "user.update_user_profile")
    def update_user_profile(
        self,
        id_external_user: int,
        *,
        role: str | None = None,
        usecase: str | None = None,
    ) -> User:
        """Persist only the supplied profile fields on the user document."""
        try:
            query, update = q.update_user_profile_query(
                id_external_user,
                role=role,
                usecase=usecase,
            )
            result = self.db.user.update_one(query, update)
            if result.matched_count == 0:
                raise ValueError(
                    f"User with id_external_user {id_external_user} not found."
                )
            return self.get_user(id_external_user)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error updating user profile in database: {e}")

    @logged(Module.DATABASE, "user.sync_sign_in_profile")
    def sync_sign_in_profile(
        self,
        id_external_user: int,
        *,
        id_external_company: int,
    ) -> None:
        """Persist the company id after OAuth Sign in."""
        try:
            query, update = q.sync_sign_in_profile_query(
                id_external_user,
                id_external_company=id_external_company,
            )
            result = self.db.user.update_one(query, update)
            if result.matched_count == 0:
                raise ValueError(
                    f"User with id_external_user {id_external_user} not found."
                )
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error syncing sign-in profile in database: {e}")

    @logged(Module.DATABASE, "user.get_user")
    def get_user(self, id_external_user) -> User:
        """Retrieve a user by external identifier."""
        try:
            user_data = self.db.user.find_one(q.get_user_query_filter(id_external_user))
            if not user_data:
                raise ValueError(
                    f"User with id_external_user {id_external_user} not found."
                )
            return user_from_data(user_data)
        except ValueError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Error fetching user from database: {e}")

    @logged(Module.DATABASE, "user.get_user_by_id")
    def get_user_by_id(self, id_user: str) -> User:
        """Retrieve a user by internal identifier, returning None when absent."""
        try:
            query, projection = q.get_user_query(id_user)
            user_data = self.db.user.find_one(query, projection)
            if not user_data:
                return None
            return user_from_data(user_data)
        except Exception as e:
            raise RuntimeError(f"Error fetching user by id from database: {e}")

    @logged(Module.DATABASE, "user.get_user_memories")
    def get_user_memories(self, id_user: str) -> list[UserMemory]:
        """Retrieve the memories stored for a user."""
        try:
            memories_data = self.db.user_memory.find(q.get_user_memories_query(id_user))
            return [
                UserMemory(
                    id=str(memory["_id"]),
                    id_user=str(memory["id_user"]),
                    field=memory["field"],
                    description=memory["description"],
                    created_at=memory.get("created_at"),
                    expires_at=memory.get("expires_at"),
                )
                for memory in memories_data
            ]
        except Exception as e:
            raise RuntimeError(f"Error fetching user memories from database: {e}")

    @logged(Module.DATABASE, "user.create_user_memory")
    def create_user_memory(self, user_memory: UserMemory):
        """Persist a memory associated with a user."""
        try:
            memory_data = q.create_user_memory_query(user_memory)
            self.db.user_memory.insert_one(memory_data)
            return
        except Exception as e:
            raise RuntimeError(f"Error creating user memory in database: {e}")

    @logged(Module.DATABASE, "user.set_id_external_company")
    def set_id_external_company(self, id_user: str, id_external_company: int) -> None:
        """Persist the company identifier on the user document."""
        try:
            query, update = q.set_id_external_company_query(
                id_user, id_external_company
            )
            self.db.user.update_one(query, update)
        except Exception as e:
            raise RuntimeError(f"Error updating user company: {e}")


def user_from_data(data: dict) -> User:
    """Map a MongoDB document to a user entity."""
    return User(
        id=str(data["_id"]),
        id_external_user=data["id_external_user"],
        role=data["role"],
        usecase=data["usecase"],
        id_external_company=data.get("id_external_company"),
    )
