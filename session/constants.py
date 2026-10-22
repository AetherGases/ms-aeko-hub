"""Session name limits, Redis key prefix, and MongoDB projections."""

SESSION_NAME_MAX_LENGTH = 60
SESSION_KEY_PREFIX = "aeko:session"
SESSION_PROJECTION = {
    "_id": 1,
    "id_user": 1,
    "name": 1,
    "created_at": 1,
    "updated_at": 1,
}
