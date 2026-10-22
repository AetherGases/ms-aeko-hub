"""Define the domain entities for HTTP request metrics."""

from datetime import datetime


class Metric:
    """One request, as a dashboard needs it."""

    id: str | None
    latency: str
    response_status: int
    endpoint: str

    def __init__(
        self,
        latency: str,
        response_status: int,
        endpoint: str,
        id: str | None = None,
        origin: str = "internal",
        created_at: datetime | None = None,
    ):
        """Store the fields of one HTTP request metric."""
        self.id = id
        self.latency = latency
        self.response_status = response_status
        self.endpoint = endpoint
        self.origin = origin
        self.created_at = created_at
