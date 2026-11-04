class SliteIOError(Exception):
    """Base error for user-facing slite-io failures."""


class SliteError(SliteIOError):
    """Base error for Slite API and client operations."""


class SliteAPIError(SliteError):
    """HTTP error returned by the Slite API."""

    def __init__(self, status_code: int, message: str, code: str | None = None):
        """Store the HTTP status, message, and optional Slite error code."""
        self.status_code = status_code
        self.code = code
        self.message = message
        suffix = f" ({code})" if code else ""
        super().__init__(f"Slite API {status_code}: {message}{suffix}")


class NoteNotFoundError(SliteError):
    """A target note or root channel could not be found."""


class AmbiguousTitleError(SliteError):
    """Multiple notes or channels share the requested title."""


class DocumentError(SliteIOError):
    """A source document could not be read, parsed, or mapped to a repo path."""


class SelectionError(SliteIOError):
    """The input paths or include/exclude globs produced no usable selection."""
