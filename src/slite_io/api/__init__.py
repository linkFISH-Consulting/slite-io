from __future__ import annotations

from typing import Any

from .notes import NotesApiClient
from .session import DEFAULT_API_URL, SliteApiSession


class SliteApiClient:
    """Aggregate root for Slite API access."""

    def __init__(self, session: SliteApiSession):
        """Build the notes client around one authenticated session."""
        self.session = session
        self.notes = NotesApiClient(session)

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        base_url: str = DEFAULT_API_URL,
    ) -> SliteApiClient:
        """Create a client from an API key and base URL."""
        return cls(SliteApiSession(base_url=base_url, api_key=api_key))

    def test_connection(self) -> dict[str, Any]:
        """Return the authenticated user/organization payload."""
        return self.notes.get_me()

    def close(self) -> None:
        """Close the underlying requests session."""
        self.session.close()

    def __enter__(self) -> SliteApiClient:
        """Enter a context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Close the session when leaving a context manager."""
        self.close()


__all__ = [
    "DEFAULT_API_URL",
    "NotesApiClient",
    "SliteApiClient",
    "SliteApiSession",
]
