from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from slite_io.errors import DocumentError
from slite_io.models import SourceDocument

H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*#*[ \t]*$")
log = logging.getLogger("slite_io")


class FrontmatterParser:
    """Split and parse a leading YAML frontmatter block with ruamel."""

    def parse(self, text: str) -> tuple[dict[str, Any], str]:
        """Return frontmatter metadata and the remaining Markdown body."""
        if text.startswith("\ufeff"):
            text = text[1:]

        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            return {}, text

        closing_index: int | None = None
        for index in range(1, len(lines)):
            if lines[index].strip() in {"---", "..."}:
                closing_index = index
                break

        if closing_index is None:
            raise DocumentError(
                "Frontmatter starts with '---' but has no closing '---'."
            )

        yaml_text = "".join(lines[1:closing_index])
        try:
            metadata = YAML(typ="safe").load(yaml_text) or {}
        except YAMLError as exc:
            raise DocumentError(f"Could not parse YAML frontmatter: {exc}") from exc

        if not isinstance(metadata, dict):
            raise DocumentError("Frontmatter must be a YAML mapping.")

        body = "".join(lines[closing_index + 1 :]).lstrip("\r\n")
        return dict(metadata), body


class TitleResolver:
    """Resolve note titles and remove a duplicate leading H1."""

    def resolve(
        self,
        metadata: dict[str, Any],
        body: str,
        path: Path,
        override: str | None = None,
    ) -> str:
        """Resolve the title from override, frontmatter, H1, or filename."""
        if override:
            return override.strip()

        for key in ("title", "sidebar_label"):
            value = metadata.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()

        heading = self.first_h1(body)
        if heading is not None:
            return heading[0]

        return path.stem.replace("-", " ").replace("_", " ").strip()

    def strip_leading_duplicate_h1(
        self, body: str, title: str
    ) -> tuple[str, bool, str | None]:
        """Remove a leading H1 when it duplicates the note title."""
        lines = body.splitlines()
        in_fence = False
        fence_marker = ""
        leading_index: int | None = None

        for index, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped:
                continue
            if self._is_fence(stripped):
                marker = stripped[:3]
                if not in_fence:
                    in_fence = True
                    fence_marker = marker
                elif marker == fence_marker:
                    in_fence = False
                continue
            if in_fence:
                continue
            leading_index = index
            break

        if leading_index is None:
            return body, False, None

        match = H1_RE.match(lines[leading_index])
        if not match:
            return body, False, None

        heading = match.group(1).strip()
        if normalize_title(heading) != normalize_title(title):
            return body, False, heading

        del lines[leading_index]
        while leading_index < len(lines) and not lines[leading_index].strip():
            del lines[leading_index]

        result = "\n".join(lines).lstrip("\r\n")
        if body.endswith("\n") and result and not result.endswith("\n"):
            result += "\n"
        return result, True, heading

    def first_h1(self, body: str) -> tuple[str, int] | None:
        """Return the first H1 outside fenced code, with its line index."""
        in_fence = False
        fence_marker = ""
        for index, line in enumerate(body.splitlines()):
            stripped = line.lstrip()
            if self._is_fence(stripped):
                marker = stripped[:3]
                if not in_fence:
                    in_fence = True
                    fence_marker = marker
                elif marker == fence_marker:
                    in_fence = False
                continue
            if in_fence:
                continue
            match = H1_RE.match(line)
            if match:
                return match.group(1).strip(), index
        return None

    @staticmethod
    def _is_fence(stripped_line: str) -> bool:
        """Return whether the line opens or closes a fenced code block."""
        return stripped_line.startswith("```") or stripped_line.startswith("~~~")


class SourceDocumentLoader:
    """Read, parse, and normalize one source file."""

    def __init__(
        self,
        *,
        frontmatter_parser: FrontmatterParser | None = None,
        title_resolver: TitleResolver | None = None,
    ):
        """Allow injection of the parser and title resolver for testing."""
        self.frontmatter_parser = frontmatter_parser or FrontmatterParser()
        self.title_resolver = title_resolver or TitleResolver()

    def load(
        self,
        path: Path,
        *,
        title_override: str | None = None,
    ) -> SourceDocument:
        """Load a file and return its normalized source document."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise DocumentError(f"Could not read {path}: {exc}") from exc

        metadata, body = self.frontmatter_parser.parse(text)
        title = self.title_resolver.resolve(
            metadata, body, path, override=title_override
        )
        body, stripped, leading_h1 = self.title_resolver.strip_leading_duplicate_h1(
            body, title
        )

        warnings: list[str] = []
        if leading_h1 is not None and not stripped:
            if normalize_title(leading_h1) != normalize_title(title):
                warnings.append(
                    f"document starts with H1 {leading_h1!r}, which differs from "
                    f"the note title {title!r}; keeping it"
                )

        log.debug(
            "Loaded document %s title=%r draft=%s warnings=%d",
            path,
            title,
            is_true(metadata.get("draft")),
            len(warnings),
        )
        return SourceDocument(
            path=path,
            title=title,
            body=body,
            metadata=metadata,
            warnings=warnings,
            draft=is_true(metadata.get("draft")),
        )


class ReadOnlyHeader:
    """Render the generated read-only notice and edit link."""

    def build_edit_url(
        self,
        *,
        template: str | None,
        filename: str,
        file_basename: str,
    ) -> str | None:
        """Expand ``{filename}`` and ``{file_basename}`` in the edit URL."""
        if not template:
            return None
        try:
            edit_url = template.format(
                filename=quote(filename, safe=""),
                file_basename=quote(file_basename, safe=""),
            )
            log.debug("Expanded header edit URL for %r -> %s", filename, edit_url)
            return edit_url
        except KeyError as exc:
            raise DocumentError(
                f"Unknown placeholder {exc} in --header-edit-url; only "
                "{filename} and {file_basename} are supported."
            ) from exc

    def render(
        self,
        *,
        source_path: str,
        synced_at: str,
        edit_url: str | None,
    ) -> str:
        """Return the Markdown blockquote prepended to the Slite note."""
        lines = [
            "> [!WARNING]",
            "> **🔒 Read-only mirror — do not edit this note in Slite.**",
            "> ",
            "> This note is imported via the API. Manual changes are overwritten",
            "> by the next sync.",
            ">",
        ]
        if edit_url:
            lines.append(
                f"> [Edit this file in Git]({edit_url}) · Last synced: {synced_at}"
            )
        else:
            lines.append(f"> Source: `{source_path}` · Last synced: {synced_at}")
        return "\n".join(lines) + "\n\n"


class DocumentRenderer:
    """Combine a source document with its optional read-only header."""

    def __init__(self, header: ReadOnlyHeader | None = None):
        """Allow injection of the header renderer for testing."""
        self.header = header or ReadOnlyHeader()

    def render(
        self,
        document: SourceDocument,
        *,
        synced_at: str,
        edit_url: str | None,
        include_header: bool = True,
    ) -> str:
        """Return the final Markdown payload for a Slite note."""
        if not include_header:
            return document.body
        return (
            self.header.render(
                source_path=document.path.as_posix(),
                synced_at=synced_at,
                edit_url=edit_url,
            )
            + document.body
        )


def utc_now_string() -> str:
    """Return the current UTC timestamp used in the sync header."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")


def normalize_title(title: str) -> str:
    """Normalize a title for case-insensitive comparison."""
    return " ".join(title.split()).casefold()


def is_true(value: Any) -> bool:
    """Interpret YAML boolean-ish values."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1"}
    return bool(value)
