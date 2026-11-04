from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

ActionName = Literal["create", "update", "skip", "fail", "valid"]


class UploadFormat(StrEnum):
    """Select which Slite API content field receives the document body."""

    markdown = "markdown"
    sliteml = "sliteml"


@dataclass(frozen=True)
class Note:
    """A Slite note as returned by the public API."""

    id: str
    title: str
    parent_note_id: str | None
    url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_edited_at: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Note:
        """Build a note from a Slite JSON payload."""
        return cls(
            id=str(payload["id"]),
            title=str(payload.get("title", "")),
            parent_note_id=payload.get("parentNoteId"),
            url=payload.get("url"),
            created_at=payload.get("createdAt"),
            updated_at=payload.get("updatedAt"),
            last_edited_at=payload.get("lastEditedAt"),
        )


@dataclass
class SourceDocument:
    """A parsed Markdown/MDX source file."""

    path: Path
    title: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    draft: bool = False


@dataclass(frozen=True)
class UploadAction:
    """The outcome of one planned or executed upload."""

    source: str
    title: str
    action: ActionName
    note_id: str | None = None
    url: str | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass
class UploadResult:
    """A batch of upload actions plus command metadata."""

    command: str
    apply: bool
    target: str
    actions: list[UploadAction]

    def summary(self) -> dict[str, int]:
        """Count actions by type."""
        counts = {"create": 0, "update": 0, "skip": 0, "fail": 0, "valid": 0}
        for action in self.actions:
            counts[action.action] += 1
        return counts

    @property
    def failed(self) -> bool:
        """Whether any action failed."""
        return any(action.action == "fail" for action in self.actions)

    def exit_code(self) -> int:
        """Return the CLI exit code for this result."""
        if not self.failed:
            return 0
        return 3 if self.command == "upload-batch" else 1
