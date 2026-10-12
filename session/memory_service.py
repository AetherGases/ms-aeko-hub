"""Harvest inactive conversation windows and synchronize recent sessions into Redis."""

from datetime import datetime, timedelta

from internal.shared import new_id_request, record_aeko_metrics
from session.cache.cache import ICacheRepository
from session.entity import SessionWindow
from session.session import IRepository as ISessionRepository
from user.entity import UserMemory
from user.user import IService as IUserService


class Service:
    def __init__(
        self,
        session_repository: ISessionRepository,
        cache_repository: ICacheRepository,
        user_service: IUserService,
        summary_generator,
        inactivity_minutes: int,
        memory_field: str,
        aeko_id_request: str | None = None,
    ):
        self.session_repository = session_repository
        self.cache_repository = cache_repository
        self.user_service = user_service
        self.summary_generator = summary_generator
        self.inactivity_minutes = inactivity_minutes
        self.memory_field = memory_field
        self.aeko_id_request = aeko_id_request

    def run(self) -> None:
        """Harvest expired windows into user memories, then refresh active session caches."""
        self._harvest_expired_windows()
        self._sync_recent_sessions()

    def _harvest_expired_windows(self) -> None:
        for id_session in self.cache_repository.list_expired_windows():
            window = self.cache_repository.get_window(id_session)
            if window is None or not window.messages:
                self.cache_repository.delete_window(id_session)
                continue

            summary = self._generate_summary(window.messages)
            self.user_service.create_user_memory(
                UserMemory(
                    id=None,
                    id_user=window.id_user,
                    field=self.memory_field,
                    description=summary,
                )
            )
            self.cache_repository.delete_window(id_session)

    def _sync_recent_sessions(self) -> None:
        since = datetime.utcnow() - timedelta(minutes=self.inactivity_minutes)
        sessions = self.session_repository.get_sessions_updated_since(since)
        for session in sessions:
            messages = self.session_repository.get_session_messages(session.id)
            window_messages = SessionWindow.derive(messages, self.inactivity_minutes)
            if not window_messages:
                continue

            self.cache_repository.set_window(session.id, session.id_user, window_messages)
            self.cache_repository.set_activity(session.id, self._activity_ttl(session.updated_at))

    def _activity_ttl(self, updated_at: datetime | None) -> int:
        reference = updated_at or datetime.utcnow()
        elapsed = (datetime.utcnow() - reference).total_seconds()
        remaining = self.inactivity_minutes * 60 - elapsed
        return max(1, int(remaining))

    def _generate_summary(self, messages) -> str:
        id_request = self.aeko_id_request or new_id_request()
        try:
            response = self.summary_generator.generate_summary(messages, id_request=id_request)
        except Exception as exc:
            record_aeko_metrics(getattr(exc, "aeko_metrics", None))
            raise

        record_aeko_metrics(response.aeko_metrics)
        return response.summary
