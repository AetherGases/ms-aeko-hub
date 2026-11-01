"""Verify session repository behavior and error handling."""

from datetime import datetime

import pytest
from bson import ObjectId

from session.database import query as q
from session.database.repository import Repository, message_from_data, session_from_data
from session.entity import Message, Session
from session.session import IRepository
from tests.mongo_doubles import StubCollection, StubDatabase

ID_SESSION = "65a8b3d6c0f8e1d7f4b2c001"
ID_USER = "65a8b3d6c0f8e1d7f4b2c010"
SUBMITTED_AT = datetime(2026, 7, 26, 14, 30, 0)

SERVICE_METHODS = [
    "get_user_sessions",
    "get_session",
    "get_session_messages",
    "get_session_messages_count",
    "create_session",
    "save_message",
    "update_name",
    "delete_session",
    "get_sessions_updated_since",
]

SESSION_DOCUMENT = {
    "_id": ID_SESSION,
    "id_user": ID_USER,
    "name": "Weekly emissions review",
    "created_at": SUBMITTED_AT,
    "updated_at": SUBMITTED_AT,
}

MESSAGE_DOCUMENT = {
    "input": "Summarize this session.",
    "output": "Here is the summary.",
    "submitted_at": SUBMITTED_AT,
}


class StubUserRepository:
    def __init__(self, user=None):
        self.user = user
        self.calls = []

    def get_user_by_id(self, id_user):
        """Retrieve a user by internal identifier, returning None when absent."""
        self.calls.append(id_user)
        return self.user


def build_repository(session=None):
    """Build a repository backed by configurable MongoDB doubles."""
    database = StubDatabase(session=session or StubCollection())
    return Repository(database), database


def test_repository_implements_the_repository_interface():
    """Verify that repository implements the repository interface."""
    assert issubclass(Repository, IRepository)


def test_repository_has_no_unimplemented_abstract_method():
    """Verify that repository has no unimplemented abstract method."""
    assert Repository.__abstractmethods__ == frozenset()


def test_repository_can_be_instantiated():
    """Verify that repository can be instantiated."""
    assert isinstance(Repository("db"), IRepository)


@pytest.mark.parametrize("method", SERVICE_METHODS)
def test_repository_exposes_every_method_called_by_the_service(method):
    """Verify that repository exposes every method called by the service."""
    assert callable(getattr(Repository, method, None))


@pytest.mark.parametrize("method", SERVICE_METHODS)
def test_interface_declares_every_method_called_by_the_service(method):
    """Verify that interface declares every method called by the service."""
    assert callable(getattr(IRepository, method, None))


def test_get_user_sessions_maps_every_document():
    """Verify that get user sessions maps every document."""
    repository, _ = build_repository(StubCollection(find_result=[SESSION_DOCUMENT]))

    sessions = repository.get_user_sessions(ID_USER)

    assert len(sessions) == 1
    assert isinstance(sessions[0], Session)
    assert sessions[0].id == ID_SESSION
    assert sessions[0].name == "Weekly emissions review"


def test_get_user_sessions_queries_by_the_user_identifier():
    """Verify that get user sessions queries by the user identifier."""
    collection = StubCollection(find_result=[SESSION_DOCUMENT])
    repository, _ = build_repository(collection)

    repository.get_user_sessions(ID_USER)

    query, _ = collection.call_args("find")[0]
    assert {"id_user": ID_USER} in query["$or"]


def test_get_user_sessions_raises_value_error_when_there_is_none():
    """Verify that get user sessions raises value error when there is none."""
    repository, _ = build_repository(StubCollection(find_result=[]))

    with pytest.raises(ValueError, match=ID_USER):
        repository.get_user_sessions(ID_USER)


def test_get_user_sessions_wraps_database_failures_in_runtime_error():
    """Verify that get user sessions wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_user_sessions(ID_USER)


def test_get_session_returns_the_session_entity():
    """Verify that get session returns the session entity."""
    repository, _ = build_repository(StubCollection(find_one_result=SESSION_DOCUMENT))

    session = repository.get_session(ID_SESSION)

    assert isinstance(session, Session)
    assert session.id == ID_SESSION
    assert session.id_user == ID_USER


def test_get_session_raises_value_error_when_not_found():
    """Verify that get session raises value error when not found."""
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session(ID_SESSION)


def test_get_session_wraps_database_failures_in_runtime_error():
    """Verify that get session wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session(ID_SESSION)


def test_get_session_messages_maps_every_embedded_message():
    """Verify that get session messages maps every embedded message."""
    document = {"messages": [MESSAGE_DOCUMENT]}
    repository, _ = build_repository(StubCollection(find_one_result=document))

    messages = repository.get_session_messages(ID_SESSION)

    assert len(messages) == 1
    assert isinstance(messages[0], Message)
    assert messages[0].input == "Summarize this session."
    assert messages[0].output == "Here is the summary."
    assert messages[0].submitted_at == SUBMITTED_AT


def test_get_session_messages_returns_an_empty_list_when_there_is_none():
    """Verify that get session messages returns an empty list when there is none."""
    repository, _ = build_repository(StubCollection(find_one_result={"messages": []}))

    assert repository.get_session_messages(ID_SESSION) == []


def test_get_session_messages_raises_value_error_when_the_session_is_unknown():
    """Verify that get session messages raises value error when the session is unknown."""
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session_messages(ID_SESSION)


def test_get_session_messages_wraps_database_failures_in_runtime_error():
    """Verify that get session messages wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session_messages(ID_SESSION)


def test_get_session_messages_count_returns_the_size():
    """Verify that get session messages count returns the size."""
    repository, _ = build_repository(
        StubCollection(find_one_result={"messages_count": 3})
    )

    assert repository.get_session_messages_count(ID_SESSION) == 3


def test_get_session_messages_count_raises_value_error_when_not_found():
    """Verify that get session messages count raises value error when not found."""
    repository, _ = build_repository(StubCollection(find_one_result=None))

    with pytest.raises(ValueError, match=ID_SESSION):
        repository.get_session_messages_count(ID_SESSION)


def test_get_session_messages_count_wraps_database_failures_in_runtime_error():
    """Verify that get session messages count wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.get_session_messages_count(ID_SESSION)


def test_create_session_returns_the_new_identifier():
    """Verify that create session returns the new identifier."""
    collection = StubCollection(inserted_id=ObjectId(ID_SESSION))
    repository, _ = build_repository(collection)

    assert (
        repository.create_session(ID_USER, StubUserRepository(user=object()))
        == ID_SESSION
    )


def test_create_session_stores_the_owner_and_an_empty_history():
    """Verify that create session stores the owner and an empty history."""
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.create_session(ID_USER, StubUserRepository(user=object()))

    document = collection.call_args("insert_one")[0][0]
    assert document["id_user"] == ObjectId(ID_USER)
    assert document["messages"] == []


def test_create_session_raises_value_error_for_an_unknown_user():
    """Verify that create session raises value error for an unknown user."""
    repository, _ = build_repository(StubCollection())

    with pytest.raises(ValueError, match=ID_USER):
        repository.create_session(ID_USER, StubUserRepository(user=None))


def test_create_session_wraps_database_failures_in_runtime_error():
    """Verify that create session wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.create_session(ID_USER, StubUserRepository(user=object()))


def test_save_message_pushes_the_message_into_the_session():
    """Verify that save message pushes the message into the session."""
    collection = StubCollection()
    repository, _ = build_repository(collection)
    message = Message(
        input="What is scope 3?",
        output="Indirect emissions.",
        submitted_at=SUBMITTED_AT,
    )

    repository.save_message(ID_SESSION, message)

    query, update = collection.call_args("update_one")[0]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]
    assert update["$push"]["messages"]["input"] == "What is scope 3?"
    assert update["$push"]["messages"]["output"] == "Indirect emissions."
    assert update["$push"]["messages"]["submitted_at"] == SUBMITTED_AT
    assert "ouput" not in update["$push"]["messages"]


def test_a_pushed_turn_is_only_the_exchange_and_its_time():
    """Verify that a pushed turn is only the exchange and its time."""
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.save_message(
        ID_SESSION, Message(input="a", output="b", submitted_at=SUBMITTED_AT)
    )

    _, update = collection.call_args("update_one")[0]
    assert set(update["$push"]["messages"]) == {"input", "output", "submitted_at"}


def test_save_message_wraps_database_failures_in_runtime_error():
    """Verify that save message wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))
    message = Message(input="a", output="b", submitted_at=SUBMITTED_AT)

    with pytest.raises(RuntimeError, match="boom"):
        repository.save_message(ID_SESSION, message)


def test_update_name_sets_the_new_name():
    """Verify that update name sets the new name."""
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.update_name(ID_SESSION, "Scope 3 questions")

    query, update = collection.call_args("update_one")[0]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]
    assert update["$set"]["name"] == "Scope 3 questions"


def test_update_name_wraps_database_failures_in_runtime_error():
    """Verify that update name wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.update_name(ID_SESSION, "new name")


def test_delete_session_only_matches_a_session_without_history():
    """Verify that delete session never matches a session holding more than one message."""
    collection = StubCollection()
    repository, _ = build_repository(collection)

    repository.delete_session(ID_SESSION)

    (query,) = collection.call_args("delete_one")[0]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]
    assert query["messages.1"] == {"$exists": False}


def test_delete_session_wraps_database_failures_in_runtime_error():
    """Verify that delete session wraps database failures in runtime error."""
    repository, _ = build_repository(StubCollection(error=OSError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        repository.delete_session(ID_SESSION)


def test_message_from_data_reads_the_stored_field_names():
    """Verify that message from data reads the stored field names."""
    message = message_from_data(MESSAGE_DOCUMENT)

    assert (message.input, message.output) == (
        "Summarize this session.",
        "Here is the summary.",
    )
    assert message.submitted_at == SUBMITTED_AT


def test_message_from_data_ignores_what_a_turn_used_to_carry():
    """Verify that message mapping ignores additional model and token fields."""
    message = message_from_data(
        {**MESSAGE_DOCUMENT, "llm": "m", "input_tokens": 1, "output_tokens": 2}
    )

    assert set(vars(message)) == {"input", "output", "submitted_at"}


def test_message_from_data_ignores_the_response_field_names():
    """Verify that message from data ignores the response field names."""
    with pytest.raises(KeyError):
        message_from_data(
            {
                "input_message": "in",
                "output_message": "out",
                "submitted_at": SUBMITTED_AT,
            }
        )


def test_message_from_data_ignores_the_legacy_misspelled_output():
    """Verify that message from data ignores the legacy misspelled output."""
    with pytest.raises(KeyError):
        message_from_data({"input": "in", "ouput": "out", "submitted_at": SUBMITTED_AT})


def test_session_from_data_maps_the_document():
    """Verify that session from data maps the document."""
    session = session_from_data(SESSION_DOCUMENT)

    assert (session.id, session.id_user, session.name) == (
        ID_SESSION,
        ID_USER,
        "Weekly emissions review",
    )
    assert session.messages == []


def test_session_from_data_maps_embedded_messages_into_entities():
    """Verify that session from data maps embedded messages into entities."""
    session = session_from_data({**SESSION_DOCUMENT, "messages": [MESSAGE_DOCUMENT]})

    assert len(session.messages) == 1
    assert isinstance(session.messages[0], Message)
    assert session.messages[0].input == "Summarize this session."
    assert session.messages[0].output == "Here is the summary."
    assert session.messages[0].submitted_at == SUBMITTED_AT


def test_session_from_data_renders_an_object_id_owner_as_text():
    """Verify that session from data renders an object id owner as text."""
    session = session_from_data(
        {**SESSION_DOCUMENT, "_id": ObjectId(ID_SESSION), "id_user": ObjectId(ID_USER)}
    )

    assert (session.id, session.id_user) == (ID_SESSION, ID_USER)


def test_session_filter_accepts_both_string_and_object_id():
    """Verify that session filter accepts both string and object id."""
    query = q.get_session_filter(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert {"_id": ObjectId(ID_SESSION)} in query["$or"]


def test_session_filter_accepts_an_identifier_that_is_already_an_object_id():
    """Verify that session filter accepts an identifier that is already an object id."""
    object_id = ObjectId(ID_SESSION)

    assert q.get_session_filter(object_id)["$or"] == [
        {"_id": object_id},
        {"_id": object_id},
    ]


def test_session_filter_keeps_identifiers_that_are_not_object_ids():
    """Verify that session filter keeps identifiers that are not object ids."""
    query = q.get_session_filter("not-an-object-id")

    assert query["$or"] == [{"_id": "not-an-object-id"}, {"_id": "not-an-object-id"}]


def test_get_user_sessions_query_projects_the_session_fields():
    """Verify that get user sessions query projects the session fields."""
    query, projection = q.get_user_sessions_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert {"id_user": ObjectId(ID_USER)} in query["$or"]
    assert projection["name"] == 1
    assert projection["id_user"] == 1


def test_get_user_session_names_query_projects_only_the_name():
    """Verify that get user session names query projects only the name."""
    query, projection = q.get_user_session_names_query(ID_USER)

    assert {"id_user": ID_USER} in query["$or"]
    assert projection == {"_id": 0, "name": 1}


def test_get_session_by_name_query_requires_the_owner_and_name():
    """Verify that get session by name query requires the owner and name."""
    query, projection = q.get_session_by_name_query(ID_USER, "Weekly emissions review")

    assert {"id_user": ID_USER} in query["$and"][0]["$or"]
    assert {"name": "Weekly emissions review"} in query["$and"]
    assert projection["messages.input"] == 1
    assert projection["messages.output"] == 1
    assert projection["messages.submitted_at"] == 1


def test_get_session_query_projects_the_session_fields():
    """Verify that get session query projects the session fields."""
    query, projection = q.get_session_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["name"] == 1


def test_get_session_messages_query_projects_the_message_fields():
    """Verify that get session messages query projects the message fields."""
    query, projection = q.get_session_messages_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["messages.input"] == 1
    assert projection["messages.output"] == 1
    assert projection["messages.submitted_at"] == 1
    assert "messages.ouput" not in projection


def test_get_session_messages_count_query_projects_the_size():
    """Verify that get session messages count query projects the size."""
    query, projection = q.get_session_messages_count_query(ID_SESSION)

    assert {"_id": ID_SESSION} in query["$or"]
    assert projection["messages_count"] == {"$size": "$messages"}


def test_get_save_message_query_stores_the_turns_own_timestamp():
    """Verify that get save message query stores the turns own timestamp."""
    update = q.get_save_message_query("in", "out", SUBMITTED_AT)

    assert update["$push"]["messages"]["submitted_at"] == SUBMITTED_AT
    assert update["$set"]["updated_at"] == SUBMITTED_AT


def test_get_save_message_query_pushes_and_timestamps():
    """Verify that get save message query pushes and timestamps."""
    update = q.get_save_message_query("in", "out")

    assert update["$push"]["messages"]["input"] == "in"
    assert update["$push"]["messages"]["output"] == "out"
    assert "ouput" not in update["$push"]["messages"]
    assert update["$set"]["updated_at"] == update["$push"]["messages"]["submitted_at"]


def test_get_create_session_query_starts_an_empty_named_session():
    """Verify that get create session query starts an empty named session."""
    document = q.get_create_session_query(ID_USER)

    assert document["id_user"] == ObjectId(ID_USER)
    assert document["messages"] == []
    assert document["name"] == ""
    assert document["created_at"] == document["updated_at"]


def test_get_create_session_query_keeps_an_owner_that_is_not_an_object_id():
    """Verify that get create session query keeps an owner that is not an object id."""
    assert q.get_create_session_query("u1")["id_user"] == "u1"


def test_get_update_name_query_sets_the_name():
    """Verify that get update name query sets the name."""
    update = q.get_update_name_query("Scope 3 questions")

    assert update["$set"]["name"] == "Scope 3 questions"
    assert isinstance(update["$set"]["updated_at"], datetime)
