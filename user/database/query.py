"""Build MongoDB filters and documents for users and memories."""

from datetime import datetime, timedelta

from internal.database.object_id import id_filter, normalize_id
from user.entity import UserMemory

USER_MEMORY_TTL_DAYS = 2


def get_user_query_filter(id_external_user: int) -> dict:
    """Build the user filter for an external identifier."""
    return {
        "id_external_user": id_external_user
    }

def create_user_query(
    id_external_user: int,
    role: str,
    usecase: str,
    *,
    id_external_company: int | None = None,
) -> dict:
    """Build a new user document for MongoDB insertion."""
    document = {
        "id_external_user": id_external_user,
        "role": role,
        "usecase": usecase,
    }
    if id_external_company is not None:
        document["id_external_company"] = id_external_company
    return document

def get_user_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection for an internal user identifier."""
    return id_filter("_id", id_user), {}

def set_id_external_company_query(id_user: str, id_external_company: int) -> tuple[dict, dict]:
    """Build the filter and $set document for a user's company identifier."""
    return id_filter("_id", id_user), {"$set": {"id_external_company": id_external_company}}

def sync_sign_in_profile_query(
    id_external_user: int,
    role: str,
    usecase: str,
    *,
    id_external_company: int,
) -> tuple[dict, dict]:
    """Build the filter and $set document for an OAuth Sign in profile refresh."""
    return get_user_query_filter(id_external_user), {
        "$set": {
            "role": role,
            "usecase": usecase,
            "id_external_company": id_external_company,
        }
    }

def get_user_memories_query(id_user: str) -> dict:
    """Build the filter for memories belonging to a user."""
    return id_filter("id_user", id_user)

def get_user_profile_query(id_external_user: int) -> tuple[dict, dict]:
    """Build the filter and projection for a user's public profile."""
    return get_user_query_filter(id_external_user), {
        "_id": 0,
        "id_external_user": 1,
        "role": 1,
        "usecase": 1,
        "id_external_company": 1,
    }

def get_user_memory_fields_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection for a user's memory field names."""
    return get_user_memories_query(id_user), {
        "_id": 0,
        "field": 1
    }

def get_user_memory_by_field_query(id_user: str, field: str) -> tuple[dict, dict]:
    """Build the filter and projection for one memory field of a user."""
    return {
        "$and": [get_user_memories_query(id_user), {"field": field}]
    }, {
        "_id": 0,
        "field": 1,
        "description": 1
    }

def get_user_memories_content_query(id_user: str) -> tuple[dict, dict]:
    """Build the filter and projection for a user's memory contents."""
    return get_user_memories_query(id_user), {
        "_id": 0,
        "field": 1,
        "description": 1
    }

def create_user_memory_query(user_memory: UserMemory) -> dict:
    """Build a user memory document with normalized identifiers."""
    created_at = user_memory.created_at or datetime.utcnow()
    expires_at = user_memory.expires_at or (created_at + timedelta(days=USER_MEMORY_TTL_DAYS))

    return {
        "id_user": normalize_id(user_memory.id_user),
        "field": user_memory.field,
        "description": user_memory.description,
        "created_at": created_at,
        "expires_at": expires_at
    }
