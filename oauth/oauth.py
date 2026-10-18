"""Define the OAuth authorization-server service contract."""

from abc import ABC, abstractmethod


class IService(ABC):
    @abstractmethod
    def authorize(
        self,
        email: str,
        password: str,
        *,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str,
        resource=None,
    ) -> str:
        """Authenticate the user and return the client redirect URL with code, state, and iss."""
        pass

    @abstractmethod
    def exchange(
        self,
        code: str,
        *,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
        resource=None,
    ) -> dict:
        """Exchange a one-time authorization code for this API's access token."""
        pass
