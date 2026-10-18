"""Verify user repository behavior and error handling."""

from datetime import datetime, timedelta

import pytest
from bson import ObjectId

from tests.mongo_doubles import StubCollection, StubDatabase
from user.database import query as q
from user.database.repository import Repository
from user.entity import User, UserMemory
from user.user import IRepository

ID_USER = "65a8b3d6c0f8e1d7f4b2c010"

USER_DOCUMENT = {
    "_id": ID_USER,
    "id_external_user": 12345,
    "role": "analyst",
    "usecase": "report_generation",
}

MEMORY_DOCUMENT = {
    "_id": "65a8b3d6c0f8e1d7f4b2c099",
    "id_user": "65a8b3d6c0f8e1d7f4b2c010",
    "field": "improvement_plan",
    "description": "replace the boiler",
    "created_at": datetime(2026, 7, 26, 14, 30, 0),
    "expires_at": datetime(2026, 8, 7, 14, 30, 0),
}


def build_repository(user=None, user_memory=None):
    """Build a repository backed by configurable MongoDB doubles."""
    database = StubDatabase(user=user or StubCollection(), user_memory=user_memory or StubCollection())
    return Repository(database), database


def test_repository_implements_the_repository_interface():
    """Verify that repository implements the repository interface."""
    assert issubclass(Repository, IRepository)


def test_repository_has_no_unimplemented_abstract_method():
    """Verify that repository has no unimplemented abstract method."""
    assert Repository.__abstractmethods__ == frozenset()


def test_repository_can_be_instantiated():
    """Verify that repository can be instantiated."""
    repository = Repository("db")

    assert isinstance(repository, IRepository)
    assert repository.db == "db"


@pytest.mark.parametrize("method", sorted(IRepository.__abstractmethods__))
def test_repository_exposes_every_method_of_the_interface(method):
    """Verify that repository exposes every method of the interface."""
    assert callable(getattr(Repository, method, None))


def test_get_user_returns_the_user_entity():
    """Verify that get user returns the user entity."""
    repository, _ = build_repository(user=StubCollection(find_one_result=USER_DOCUMENT))

    user = repository.get_user(12345)

    assert isinstance(user, User)
    assert (user.id, user.id_external_user, user.role, user.usecase) == (
        "65a8b3d6c0f8e1d7f4b2c010",
        12345,
        "analyst",
        "report_generation",
    )


def test_get_user_maps_id_external_company():
    """Verify that get user maps id external company."""
    repository, _ = build_repository(
        user=StubCollection(find_one_result={**USER_DOCUMENT, "id_external_company": 90})
    )

    assert repository.get_user(12345).id_external_company == 90


def test_set_id_external_company_updates_the_user_document():
    """Verify that set id external company updates the user document."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.set_id_external_company(ID_USER, 90)

    query, update = collection.call_args("update_one")[0]
    assert query == q.get_user_query(ID_USER)[0]
    assert update == {"$set": {"id_external_company": 90}}


def test_create_user_inserts_the_document_and_returns_the_entity():
    """Verify that create user inserts the document and returns the user entity."""
    collection = StubCollection(inserted_id=ObjectId())
    repository, _ = build_repository(user=collection)

    user = repository.create_user(99, "analyst", "report_generation")

    document = collection.call_args("insert_one")[0][0]
    assert document["id_external_user"] == 99
    assert document["role"] == "analyst"
    assert document["usecase"] == "report_generation"
    assert user.id_external_user == 99
    assert user.role == "analyst"
    assert user.usecase == "report_generation"
    assert user.id == str(collection.inserted_id)


def test_update_user_profile_overwrites_only_supplied_role():
    """Verify that update user profile overwrites only the supplied role."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.update_user_profile(12345, role="gestor")

    query, update = collection.call_args("update_one")[0]
    assert query == q.get_user_query_filter(12345)
    assert update == {"$set": {"role": "gestor"}}


def test_update_user_profile_overwrites_both_fields():
    """Verify that update user profile overwrites both profile fields."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.update_user_profile(12345, role="gestor", usecase="auditoria")

    query, update = collection.call_args("update_one")[0]
    assert query == q.get_user_query_filter(12345)
    assert update == {"$set": {"role": "gestor", "usecase": "auditoria"}}


def test_sync_sign_in_profile_updates_the_user_document():
    """Verify that sync sign in profile updates the user document."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)
    repository.sync_sign_in_profile(12345, id_external_company=90)

    query, update = collection.call_args("update_one")[0]
    assert query == q.get_user_query_filter(12345)
    assert update == {"$set": {"id_external_company": 90}}


def test_sync_sign_in_profile_raises_when_the_user_is_missing():
    """Verify that sync sign in profile raises when the user is missing."""
    repository, _ = build_repository(
        user=StubCollection(find_one_result=None, update_matched_count=0)
    )

    with pytest.raises(ValueError, match="not found"):
        repository.sync_sign_in_profile(12345, id_external_company=90)


def test_create_user_query_builds_the_expected_document():
    """Verify that create user query builds the expected document."""
    document = q.create_user_query(99, "analyst", "report_generation")
    assert document == {
        "id_external_user": 99,
        "role": "analyst",
        "usecase": "report_generation",
    }


def test_get_user_queries_by_the_external_identifier():
    """Verify that get user queries by the external identifier."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user(12345)

    assert collection.call_args("find_one")[0][0] == {"id_external_user": 12345}


def test_get_user_reads_the_collection_only_once():
    """Verify that get user reads the collection only once."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user(12345)

    assert len(collection.call_args("find_one")) == 1


def test_get_user_raises_value_error_when_not_found():
    """Verify that get user raises value error when not found."""
    repository, _ = build_repository(user=StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match="12345"):
        repository.get_user(12345)


def test_get_user_wraps_database_failures_in_runtime_error():
    """Verify that get user wraps database failures in runtime error."""
    repository, _ = build_repository(user=StubCollection(error=OSError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        repository.get_user(12345)


def test_get_user_by_id_returns_the_user_entity():
    """Verify that get user by id returns the user entity."""
    repository, _ = build_repository(user=StubCollection(find_one_result=USER_DOCUMENT))

    user = repository.get_user_by_id("65a8b3d6c0f8e1d7f4b2c010")

    assert isinstance(user, User)
    assert user.id == "65a8b3d6c0f8e1d7f4b2c010"


def test_get_user_by_id_queries_by_the_internal_identifier():
    """Verify that get user by id queries by the internal identifier."""
    collection = StubCollection(find_one_result=USER_DOCUMENT)
    repository, _ = build_repository(user=collection)

    repository.get_user_by_id(ID_USER)

    query = collection.call_args("find_one")[0][0]
    assert {"_id": ID_USER} in query["$or"]
    assert {"_id": ObjectId(ID_USER)} in query["$or"]


def test_get_user_by_id_returns_none_when_not_found():
    """Verify that get user by id returns none when not found."""
    repository, _ = build_repository(user=StubCollection(find_one_result=None))

    assert repository.get_user_by_id("ghost") is None


def test_get_user_by_id_wraps_database_failures_in_runtime_error():
    """Verify that get user by id wraps database failures in runtime error."""
    repository, _ = build_repository(user=StubCollection(error=OSError("connection reset")))

    with pytest.raises(RuntimeError, match="connection reset"):
        repository.get_user_by_id("u1")


def test_get_user_memories_maps_every_document():
    """Verify that get user memories maps every document."""
    repository, _ = build_repository(user_memory=StubCollection(find_result=[MEMORY_DOCUMENT]))

    memories = repository.get_user_memories("65a8b3d6c0f8e1d7f4b2c010")

    assert len(memories) == 1
    assert isinstance(memories[0], UserMemory)
    assert memories[0].field == "improvement_plan"
    assert memories[0].created_at == MEMORY_DOCUMENT["created_at"]


def test_get_user_memories_renders_an_object_id_owner_as_text():
    """Verify that get user memories renders an object id owner as text."""
    document = {**MEMORY_DOCUMENT, "_id": ObjectId(MEMORY_DOCUMENT["_id"]), "id_user": ObjectId(ID_USER)}
    repository, _ = build_repository(user_memory=StubCollection(find_result=[document]))

    memories = repository.get_user_memories(ID_USER)

    assert memories[0].id_user == ID_USER


def test_get_user_memories_returns_an_empty_list():
    """Verify that get user memories returns an empty list."""
    repository, _ = build_repository(user_memory=StubCollection(find_result=[]))

    assert repository.get_user_memories("u1") == []


def test_get_user_memories_wraps_database_failures_in_runtime_error():
    """Verify that get user memories wraps database failures in runtime error."""
    repository, _ = build_repository(user_memory=StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_user_memories("u1")


def test_create_user_memory_inserts_the_document():
    """Verify that create user memory inserts the document."""
    collection = StubCollection()
    repository, _ = build_repository(user_memory=collection)
    created_at = datetime(2026, 7, 26, 14, 30, 0)

    repository.create_user_memory(
        UserMemory(id=None, id_user="u1", field="improvement_plan", description="text", created_at=created_at)
    )

    document = collection.call_args("insert_one")[0][0]
    assert document["id_user"] == "u1"
    assert document["field"] == "improvement_plan"
    assert document["created_at"] == created_at


def test_create_user_memory_wraps_database_failures_in_runtime_error():
    """Verify that create user memory wraps database failures in runtime error."""
    repository, _ = build_repository(user_memory=StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create_user_memory(UserMemory(id=None, id_user="u1", field="f", description="d"))


def test_get_user_query_filter_targets_the_external_identifier():
    """Verify that get user query filter targets the external identifier."""
    assert q.get_user_query_filter(12345) == {"id_external_user": 12345}


def test_get_user_query_filter_keeps_the_external_identifier_a_number():
    """Verify that get user query filter keeps the external identifier a number."""
    assert isinstance(q.get_user_query_filter(12345)["id_external_user"], int)


def test_set_id_external_company_query_sets_the_company():
    """Verify that set id external company query sets the company."""
    query, update = q.set_id_external_company_query(ID_USER, 90)
    assert query == q.get_user_query(ID_USER)[0]
    assert update == {"$set": {"id_external_company": 90}}


def test_get_user_query_targets_the_internal_identifier():
    """Verify that get user query targets the internal identifier."""
    query, projection = q.get_user_query(ID_USER)

    assert {"_id": ID_USER} in query["$or"]
    assert {"_id": ObjectId(ID_USER)} in query["$or"]
    assert projection == {}


def test_get_user_query_keeps_an_identifier_that_is_not_an_object_id():
    """Verify that get user query keeps an identifier that is not an object id."""
    query, _ = q.get_user_query("u1")

    assert query["$or"] == [{"_id": "u1"}, {"_id": "u1"}]


def test_get_user_memories_query_targets_the_user():
    """Verify that get user memories query targets the user."""
    query = q.get_user_memories_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert {"id_user": ObjectId(ID_USER)} in query["$or"]


def test_get_user_profile_query_projects_role_and_usecase():
    """Verify that get user profile query projects role and usecase."""
    query, projection = q.get_user_profile_query(12345)

    assert query == {"id_external_user": 12345}
    assert projection == {
        "_id": 0,
        "id_external_user": 1,
        "role": 1,
        "usecase": 1,
        "id_external_company": 1,
    }


def test_get_user_memory_fields_query_projects_only_field_names():
    """Verify that get user memory fields query projects only field names."""
    query, projection = q.get_user_memory_fields_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert projection == {"_id": 0, "field": 1}


def test_get_user_memory_by_field_query_requires_the_owner_and_field():
    """Verify that get user memory by field query requires the owner and field."""
    query, projection = q.get_user_memory_by_field_query(ID_USER, "preferred_language")

    assert {"id_user": ID_USER} in query["$and"][0]["$or"]
    assert {"field": "preferred_language"} in query["$and"]
    assert projection == {"_id": 0, "field": 1, "description": 1}


def test_get_user_memories_content_query_projects_field_and_description():
    """Verify that get user memories content query projects field and description."""
    query, projection = q.get_user_memories_content_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert projection == {"_id": 0, "field": 1, "description": 1}


def test_create_user_memory_query_stores_the_owner_as_an_object_id():
    """Verify that create user memory query stores the owner as an object id."""
    document = q.create_user_memory_query(UserMemory(id=None, id_user=ID_USER, field="f", description="d"))

    assert document["id_user"] == ObjectId(ID_USER)


def test_create_user_memory_query_keeps_an_owner_that_is_not_an_object_id():
    """Verify that create user memory query keeps an owner that is not an object id."""
    document = q.create_user_memory_query(UserMemory(id=None, id_user="u1", field="f", description="d"))

    assert document["id_user"] == "u1"


def test_create_user_memory_query_keeps_explicit_timestamps():
    """Verify that create user memory query keeps explicit timestamps."""
    created_at = datetime(2026, 7, 26, 14, 30, 0)
    expires_at = datetime(2026, 9, 1, 0, 0, 0)

    document = q.create_user_memory_query(
        UserMemory(id=None, id_user="u1", field="f", description="d", created_at=created_at, expires_at=expires_at)
    )

    assert document["created_at"] == created_at
    assert document["expires_at"] == expires_at


def test_create_user_memory_query_defaults_the_expiration_window():
    """Verify that create user memory query defaults the expiration window."""
    created_at = datetime(2026, 7, 26, 14, 30, 0)

    document = q.create_user_memory_query(
        UserMemory(id=None, id_user="u1", field="f", description="d", created_at=created_at)
    )

    assert document["expires_at"] == created_at + timedelta(days=q.USER_MEMORY_TTL_DAYS)


def test_create_user_memory_query_defaults_the_creation_timestamp():
    """Verify that create user memory query defaults the creation timestamp."""
    document = q.create_user_memory_query(UserMemory(id=None, id_user="u1", field="f", description="d"))

    assert isinstance(document["created_at"], datetime)
    assert document["expires_at"] > document["created_at"]
