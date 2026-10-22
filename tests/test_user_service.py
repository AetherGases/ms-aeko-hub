"""Verify user service behavior and error handling."""

import pytest

from user.entity import User, UserMemory
from user.service import Service
from user.user import IService

USER = User(
    id="u1", id_external_user=12345, role="analyst", usecase="report_generation"
)


class StubUserRepository:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def _run(self, name, *args):
        self.calls.append((name, *args))
        if self.error is not None:
            raise self.error
        return self.result

    def get_user(self, id_external_user):
        """Retrieve a user by external identifier."""
        return self._run("get_user", id_external_user)

    def get_user_by_id(self, id_user):
        """Retrieve a user by internal identifier, returning None when absent."""
        return self._run("get_user_by_id", id_user)

    def get_user_memories(self, id_user):
        """Retrieve the memories stored for a user."""
        return self._run("get_user_memories", id_user)

    def create_user_memory(self, user_memory):
        """Persist a memory associated with a user."""
        return self._run("create_user_memory", user_memory)

    def set_id_external_company(self, id_user, id_external_company):
        """Persist the company identifier on the user document."""
        return self._run("set_id_external_company", id_user, id_external_company)

    def create_user(self, id_external_user, role, usecase, **kwargs):
        """Persist a new user with the supplied profile fields."""
        return self._run("create_user", id_external_user, role, usecase, kwargs)

    def sync_sign_in_profile(self, id_external_user, **kwargs):
        """Persist ms-auth company id after OAuth Sign in."""
        return self._run("sync_sign_in_profile", id_external_user, kwargs)

    def update_user_profile(self, id_external_user, *, role=None, usecase=None):
        """Persist only the supplied profile fields on the user document."""
        return self._run("update_user_profile", id_external_user, role, usecase)


def test_service_implements_the_service_interface():
    """Verify that service implements the service interface."""
    assert issubclass(Service, IService)
    assert Service.__abstractmethods__ == frozenset()


def test_get_mongo_user_delegates_to_the_repository():
    """Verify that get mongo user delegates to the repository."""
    repository = StubUserRepository(result=USER)
    service = Service(repository)

    assert service.get_mongo_user(12345) is USER
    assert repository.calls == [("get_user", 12345)]


def test_get_mongo_user_propagates_value_error():
    """Verify that get mongo user propagates value error."""
    service = Service(StubUserRepository(error=ValueError("User not found.")))

    with pytest.raises(ValueError, match="User not found."):
        service.get_mongo_user(404)


def test_get_mongo_user_wraps_unexpected_errors():
    """Verify that get mongo user wraps unexpected errors."""
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_mongo_user(12345)


def test_get_user_memories_delegates_to_the_repository():
    """Verify that get user memories delegates to the repository."""
    memory = UserMemory(
        id="m1", id_user="u1", field="improvement_plan", description="text"
    )
    repository = StubUserRepository(result=[memory])
    service = Service(repository)

    assert service.get_user_memories("u1") == [memory]
    assert repository.calls == [("get_user_memories", "u1")]


def test_get_user_memories_wraps_unexpected_errors():
    """Verify that get user memories wraps unexpected errors."""
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_user_memories("u1")


def test_set_id_external_company_delegates_to_the_repository():
    """Verify that set id external company delegates to the repository."""
    repository = StubUserRepository()
    Service(repository).set_id_external_company("u1", 90)
    assert repository.calls == [("set_id_external_company", "u1", 90)]


def test_create_user_memory_delegates_to_the_repository():
    """Verify that create user memory delegates to the repository."""
    repository = StubUserRepository()
    service = Service(repository)
    memory = UserMemory(
        id=None, id_user="u1", field="improvement_plan", description="text"
    )

    assert service.create_user_memory(memory) is None
    assert repository.calls == [("create_user_memory", memory)]


def test_create_user_memory_wraps_unexpected_errors():
    """Verify that create user memory wraps unexpected errors."""
    service = Service(StubUserRepository(error=OSError("mongo down")))

    with pytest.raises(RuntimeError, match="mongo down"):
        service.create_user_memory(
            UserMemory(id=None, id_user="u1", field="f", description="d")
        )


def test_get_mongo_user_or_create_returns_an_existing_user():
    """Verify that get mongo user or create returns an existing user without creating one."""
    repository = StubUserRepository(result=USER)
    service = Service(repository)

    assert (
        service.get_mongo_user_or_create(12345, "analyst", "report_generation") is USER
    )
    assert repository.calls == [("get_user", 12345)]


def test_get_mongo_user_or_create_creates_when_missing():
    """Verify that get mongo user or create inserts a user when absent."""
    created = User(id="u2", id_external_user=99, role="analyst", usecase="inventory")

    class Repository(StubUserRepository):
        def get_user(self, id_external_user):
            """Raise not found once, then behave like the default stub."""
            self.calls.append(("get_user", id_external_user))
            if id_external_user == 99 and len(self.calls) == 1:
                raise ValueError("User with id_external_user 99 not found.")
            return created

        def create_user(self, id_external_user, role, usecase, **kwargs):
            """Record provisioning and return the created user."""
            self.calls.append(("create_user", id_external_user, role, usecase, kwargs))
            return created

    repository = Repository()
    service = Service(repository)

    assert service.get_mongo_user_or_create(99, "analyst", "inventory") is created
    assert repository.calls == [
        ("get_user", 99),
        ("create_user", 99, "analyst", "inventory", {}),
    ]


def test_apply_sign_in_profile_updates_an_existing_user():
    """Verify that apply sign in profile refreshes company without overwriting role."""
    from tests.test_profile_api import PROFILE_PAYLOAD

    updated = User(
        id="u1",
        id_external_user=12345,
        role="Analista ESG",
        usecase="novo uso",
        id_external_company=90,
    )

    class Repository(StubUserRepository):
        def sync_sign_in_profile(self, id_external_user, **kwargs):
            """Record the ms-auth sync."""
            self.calls.append(("sync_sign_in_profile", id_external_user, kwargs))
            return None

        def get_user(self, id_external_user):
            """Return the user after the sign-in profile refresh."""
            self.calls.append(("get_user", id_external_user))
            return updated

    repository = Repository()
    service = Service(repository)

    assert (
        service.apply_sign_in_profile(12345, ms_auth_profile=PROFILE_PAYLOAD) is updated
    )
    assert repository.calls[0][0] == "sync_sign_in_profile"
    assert repository.calls[0][2]["id_external_company"] == 90
    assert updated.role == "Analista ESG"


def test_apply_sign_in_profile_creates_when_missing():
    """Verify that apply sign in profile creates the user when absent."""
    from tests.test_profile_api import PROFILE_PAYLOAD

    created = User(
        id="u2",
        id_external_user=99,
        role="",
        usecase="",
        id_external_company=90,
    )

    class Repository(StubUserRepository):
        def sync_sign_in_profile(self, id_external_user, **kwargs):
            """Raise not found so the service creates the user."""
            self.calls.append(("sync_sign_in_profile", id_external_user, kwargs))
            raise ValueError(
                f"User with id_external_user {id_external_user} not found."
            )

        def create_user(self, id_external_user, role, usecase, **kwargs):
            """Record provisioning and return the created user."""
            self.calls.append(("create_user", id_external_user, role, usecase, kwargs))
            return created

    repository = Repository()
    service = Service(repository)

    assert service.apply_sign_in_profile(99, ms_auth_profile=PROFILE_PAYLOAD) is created
    assert repository.calls[0][0] == "sync_sign_in_profile"
    assert repository.calls[1][0] == "create_user"
    assert repository.calls[1][2] == ""
    assert repository.calls[1][3] == ""
    assert repository.calls[1][4]["id_external_company"] == 90


def test_update_user_profile_rejects_when_neither_field_is_supplied():
    """Verify that update user profile rejects when neither field is supplied."""
    service = Service(StubUserRepository())

    with pytest.raises(ValueError, match="role or usecase"):
        service.update_user_profile(12345)


def test_update_user_profile_rejects_blank_role():
    """Verify that update user profile rejects blank role."""
    service = Service(StubUserRepository())

    with pytest.raises(ValueError, match="must be a nonempty string"):
        service.update_user_profile(12345, role="   ")


def test_get_mongo_user_or_create_persists_empty_role_usecase_and_company():
    """Verify that get mongo user or create persists empty role, usecase, and company."""
    created = User(
        id="u2", id_external_user=99, role="", usecase="", id_external_company=90
    )

    class Repository(StubUserRepository):
        def get_user(self, id_external_user):
            """Raise not found once, then behave like the default stub."""
            self.calls.append(("get_user", id_external_user))
            if id_external_user == 99 and len(self.calls) == 1:
                raise ValueError("User with id_external_user 99 not found.")
            return created

        def create_user(self, id_external_user, role, usecase, **kwargs):
            """Record provisioning and return the created user."""
            self.calls.append(("create_user", id_external_user, role, usecase, kwargs))
            return created

    repository = Repository()
    service = Service(repository)

    assert (
        service.get_mongo_user_or_create(99, "", "", id_external_company=90) is created
    )
    assert repository.calls == [
        ("get_user", 99),
        ("create_user", 99, "", "", {"id_external_company": 90}),
    ]


def test_get_mongo_user_or_create_wraps_unexpected_create_errors():
    """Verify that get mongo user or create wraps unexpected repository errors on insert."""

    class Repository(StubUserRepository):
        def get_user(self, id_external_user):
            """Raise not found so the service attempts to create the user."""
            raise ValueError(
                f"User with id_external_user {id_external_user} not found."
            )

        def create_user(self, id_external_user, role, usecase, **kwargs):
            """Raise a transport error while inserting."""
            raise OSError("mongo down")

    service = Service(Repository())

    with pytest.raises(RuntimeError, match="mongo down"):
        service.get_mongo_user_or_create(99, "analyst", "report_generation")


def test_get_mongo_user_or_create_syncs_company_for_an_existing_user():
    """Verify that get mongo user or create persists company on an existing user."""
    updated = User(
        id="u1",
        id_external_user=12345,
        role="analyst",
        usecase="report_generation",
        id_external_company=91,
    )

    class Repository(StubUserRepository):
        def get_user(self, id_external_user):
            """Return the original user until company has been synced."""
            self.calls.append(("get_user", id_external_user))
            if any(call[0] == "sync_sign_in_profile" for call in self.calls):
                return updated
            return USER

        def sync_sign_in_profile(self, id_external_user, **kwargs):
            """Record the same company sync used after OAuth Sign in."""
            self.calls.append(("sync_sign_in_profile", id_external_user, kwargs))
            return None

        def create_user(self, id_external_user, role, usecase, **kwargs):
            """Fail if an existing user is inserted again."""
            raise AssertionError("existing user must not be created")

    repository = Repository()
    service = Service(repository)

    assert (
        service.get_mongo_user_or_create(
            12345, "analyst", "report_generation", id_external_company=91
        )
        is updated
    )
    assert repository.calls == [
        ("get_user", 12345),
        ("sync_sign_in_profile", 12345, {"id_external_company": 91}),
        ("get_user", 12345),
    ]
