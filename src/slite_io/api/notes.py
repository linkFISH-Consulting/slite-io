from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from slite_io.errors import (
    AmbiguousTitleError,
    NoteNotFoundError,
    SliteAPIError,
    SliteError,
)
from slite_io.models import Note, UploadFormat

from .session import SliteApiSession

log = logging.getLogger("slite_io")
MAX_API_BODY_BYTES = 1_000_000


def normalize_title(title: str) -> str:
    """Normalize a title for case-insensitive, whitespace-insensitive matching."""
    return " ".join(title.split()).casefold()


class NotesApiClient:
    """Class-based wrapper around Slite's note endpoints."""

    def __init__(self, session: SliteApiSession):
        """Store the session and initialize the root-channel cache."""
        self.session = session
        self._root_channels: list[dict[str, Any]] | None = None

    def get_me(self) -> dict[str, Any]:
        """Return the authenticated user and organization."""
        payload = self._get_json("/me")
        log.debug(
            "Authenticated as %s in %s",
            payload.get("displayName"),
            payload.get("organizationName"),
        )
        return payload

    def find_root_channel(self, title: str) -> Note:
        """Resolve an exact root-channel title and log its category."""
        target = normalize_title(title)
        matches: list[Note] = []
        for payload in self._load_root_channels():
            if normalize_title(str(payload.get("title", ""))) == target:
                matches.append(Note.from_payload(payload))

        if not matches:
            raise NoteNotFoundError(f"Slite root channel not found: {title!r}")
        if len(matches) > 1:
            ids = ", ".join(note.id for note in matches)
            raise AmbiguousTitleError(
                f"Multiple root channels are titled {title!r}: {ids}"
            )

        note = matches[0]
        category = "personal" if note.id.startswith("user-") else "company"
        log.debug(
            "Root channel %r (id=%s) classified as %s",
            note.title,
            note.id,
            category,
        )
        return note

    def resolve_folder(self, path: str) -> Note:
        """Resolve an absolute root-channel path to a folder note."""
        segments = _split_path(path)
        log.debug("Resolving folder path %r (%d segments)", path, len(segments))
        note = self.find_root_channel(segments[0])
        for segment in segments[1:]:
            note = self._find_child(note.id, segment, parent_path=path)
        log.debug("Resolved folder %r -> %s (%s)", path, note.title, note.id)
        return note

    def resolve_parent_and_title(self, target_note_path: str) -> tuple[Note, str]:
        """Split a target note path into its parent folder and note title."""
        segments = _split_path(target_note_path)
        if len(segments) < 2:
            raise NoteNotFoundError(
                "Target note path must include a root channel and a note title: "
                f"{target_note_path!r}"
            )
        parent = self.resolve_folder("/".join(segments[:-1]))
        return parent, segments[-1]

    def list_children(self, parent_note_id: str) -> list[Note]:
        """Return all direct children, following cursor pagination."""
        log.debug("Listing children of %s", parent_note_id)
        notes: list[Note] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {
                "orderBy": "title",
                "orderDirection": "asc",
            }
            if cursor:
                params["cursor"] = cursor
            payload = self._get_json(
                f"/notes/{quote(parent_note_id, safe='')}/children",
                params=params,
            )
            notes.extend(Note.from_payload(item) for item in payload.get("notes", []))
            cursor = payload.get("nextCursor")
            if not payload.get("hasNextPage") or not cursor:
                log.debug("Found %d children of %s", len(notes), parent_note_id)
                return notes

    def find_child_optional(self, parent_note_id: str, title: str) -> Note | None:
        """Return a unique child by title, or None if it does not exist."""
        target = normalize_title(title)
        matches = [
            note
            for note in self.list_children(parent_note_id)
            if normalize_title(note.title) == target
        ]
        if len(matches) > 1:
            ids = ", ".join(note.id for note in matches)
            raise AmbiguousTitleError(
                f"Multiple Slite notes are titled {title!r}: {ids}"
            )
        if matches:
            log.debug("Found existing child %r -> %s", title, matches[0].id)
            return matches[0]
        log.debug("No existing child titled %r under %s", title, parent_note_id)
        return None

    def create_note(
        self,
        *,
        parent_note_id: str,
        title: str,
        body: str,
        body_format: UploadFormat = UploadFormat.markdown,
    ) -> Note:
        """Create a note under the given parent."""
        check_body_size(body)
        log.debug(
            "Creating note %r under %s (%d bytes, %s)",
            title,
            parent_note_id,
            len(body.encode("utf-8")),
            body_format.value,
        )
        payload = self._request_json(
            "POST",
            "/notes",
            json={
                "parentNoteId": parent_note_id,
                "title": title,
                body_format.value: body,
            },
        )
        return Note.from_payload(payload)

    def update_note(
        self,
        *,
        note_id: str,
        title: str,
        body: str,
        body_format: UploadFormat = UploadFormat.markdown,
    ) -> Note:
        """Update an existing note's title and formatted content."""
        check_body_size(body)
        log.debug(
            "Updating note %s as %r (%d bytes, %s)",
            note_id,
            title,
            len(body.encode("utf-8")),
            body_format.value,
        )
        payload = self._request_json(
            "PUT",
            f"/notes/{quote(note_id, safe='')}",
            json={"title": title, body_format.value: body},
        )
        return Note.from_payload(payload)

    def _find_child(
        self, parent_note_id: str, title: str, *, parent_path: str
    ) -> Note:
        """Resolve a required child by title inside a known parent path."""
        target = normalize_title(title)
        matches = [
            note
            for note in self.list_children(parent_note_id)
            if normalize_title(note.title) == target
        ]
        if not matches:
            raise NoteNotFoundError(
                f"Slite note not found: {title!r} under {parent_path!r}"
            )
        if len(matches) > 1:
            ids = ", ".join(note.id for note in matches)
            raise AmbiguousTitleError(
                f"Multiple Slite notes are titled {title!r} under "
                f"{parent_path!r}: {ids}"
            )
        return matches[0]

    def _load_root_channels(self) -> list[dict[str, Any]]:
        """Fetch and cache all depth-0 root channels."""
        if self._root_channels is not None:
            return self._root_channels

        channels: list[dict[str, Any]] = []
        page = 0
        pages = 1
        while page < pages:
            payload = self._get_json(
                "/search-notes",
                params={"query": "", "depth": 0, "page": page, "hitsPerPage": 100},
            )
            pages = max(1, int(payload.get("nbPages", 1)))
            channels.extend(payload.get("hits", []))
            page += 1

        log.debug("Loaded %d depth-0 root channels", len(channels))
        self._root_channels = channels
        return channels

    def _get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send a GET request and decode the JSON response."""
        try:
            response = self.session.get(path, params=params)
        except requests.RequestException as exc:
            raise SliteError(f"Could not reach Slite: {exc}") from exc
        return self._response_json(response)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a JSON write request and decode the JSON response."""
        try:
            response = self.session.request(method, path, json=json)
        except requests.RequestException as exc:
            raise SliteError(f"Could not reach Slite: {exc}") from exc
        return self._response_json(response)

    @staticmethod
    def _response_json(response: requests.Response) -> dict[str, Any]:
        """Raise a typed Slite error or decode a successful response."""
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise SliteAPIError(
                response.status_code,
                _error_message(response),
                _error_code(response),
            ) from exc
        if not response.content:
            return {}
        payload = response.json()
        if not isinstance(payload, dict):
            raise SliteAPIError(response.status_code, "Unexpected response shape")
        return payload


def check_body_size(markdown: str) -> None:
    """Reject Markdown that exceeds Slite's request-body limit."""
    size = len(markdown.encode("utf-8"))
    if size > MAX_API_BODY_BYTES:
        raise SliteAPIError(
            413,
            f"Markdown is {size:,} bytes, over the Slite 1,000,000-byte limit.",
            "note-size-limit-exceeded",
        )


def _split_path(path: str) -> list[str]:
    """Split a Slite title path into non-empty segments."""
    segments = [segment.strip() for segment in path.split("/") if segment.strip()]
    if not segments:
        raise NoteNotFoundError("Slite target path is empty.")
    return segments


def _error_message(response: requests.Response) -> str:
    """Extract the human-readable error message from a Slite response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip() or response.reason
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])
    return response.text.strip() or response.reason


def _error_code(response: requests.Response) -> str | None:
    """Extract Slite's machine-readable error id, if present."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get("id"):
        return str(payload["id"])
    return None
