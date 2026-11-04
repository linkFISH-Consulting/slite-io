from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from slite_io.api import SliteApiClient
from slite_io.api.notes import check_body_size, normalize_title
from slite_io.documents import (
    DocumentRenderer,
    ReadOnlyHeader,
    SourceDocumentLoader,
    utc_now_string,
)
from slite_io.errors import DocumentError, SelectionError, SliteError
from slite_io.models import (
    ActionName,
    Note,
    SourceDocument,
    UploadAction,
    UploadFormat,
)
from slite_io.selection import FileSelector

log = logging.getLogger("slite_io")


@dataclass
class PlannedUpload:
    """One upload decision plus the formatted body that would be written."""

    source: str
    title: str
    action: ActionName
    parent_note_id: str | None = None
    note_id: str | None = None
    note_url: str | None = None
    body: str | None = None
    reason: str | None = None
    warnings: tuple[str, ...] = ()


class UploadPlanner:
    """Resolve targets and turn source files into create/update/skip decisions."""

    def __init__(
        self,
        client: SliteApiClient,
        *,
        loader: SourceDocumentLoader | None = None,
        selector: FileSelector | None = None,
        renderer: DocumentRenderer | None = None,
        header: ReadOnlyHeader | None = None,
    ):
        """Store dependencies and allow lightweight test doubles."""
        self.client = client
        self.loader = loader or SourceDocumentLoader()
        self.selector = selector or FileSelector()
        self.header = header or ReadOnlyHeader()
        self.renderer = renderer or DocumentRenderer(self.header)

    def plan_single(
        self,
        source_file: Path,
        *,
        target_note: str,
        overwrite: bool,
        include_header: bool,
        header_edit_url: str | None,
        synced_at: str | None = None,
    ) -> list[PlannedUpload]:
        """Plan one explicit source file and target note path."""
        log.debug(
            "Planning single upload: source=%s target=%r overwrite=%s header=%s",
            source_file,
            target_note,
            overwrite,
            include_header,
        )
        parent, title = self.client.notes.resolve_parent_and_title(target_note)
        document = self.loader.load(source_file, title_override=title)
        existing = self.client.notes.find_child_optional(parent.id, title)
        action: ActionName
        if existing is None:
            action = "create"
        elif overwrite:
            action = "update"
        else:
            action = "skip"

        return [
            self._planned(
                document,
                action=action,
                parent_note_id=parent.id,
                existing=existing,
                include_header=include_header,
                header_edit_url=header_edit_url,
                synced_at=synced_at or utc_now_string(),
            )
        ]

    def plan_batch(
        self,
        *,
        target_folder: str,
        includes: list[str] | None,
        excludes: list[str] | None,
        overwrite: bool,
        include_header: bool,
        header_edit_url: str | None,
        synced_at: str | None = None,
    ) -> list[PlannedUpload]:
        """Plan a flat batch from the current working directory."""
        log.debug(
            "Planning batch upload: target=%r includes=%s excludes=%s overwrite=%s",
            target_folder,
            includes,
            excludes,
            overwrite,
        )
        files = self.selector.select(
            includes=includes,
            excludes=excludes,
        )
        if not files:
            raise SelectionError("No Markdown/MDX files matched the selection.")

        target = self.client.notes.resolve_folder(target_folder)
        children = self.client.notes.list_children(target.id)
        existing_by_title: dict[str, list[Note]] = {}
        for child in children:
            existing_by_title.setdefault(normalize_title(child.title), []).append(child)

        documents: list[tuple[SourceDocument, PlannedUpload | None]] = []
        for path in files:
            try:
                document = self.loader.load(path)
            except DocumentError as exc:
                documents.append(
                    (
                        _failed_document(path),
                        PlannedUpload(
                            source=path.as_posix(),
                            title=path.stem,
                            action="fail",
                            reason=str(exc),
                        ),
                    )
                )
                continue
            if document.draft:
                documents.append(
                    (
                        document,
                        PlannedUpload(
                            source=document.path.as_posix(),
                            title=document.title,
                            action="skip",
                            reason="draft: true",
                            warnings=tuple(document.warnings),
                        ),
                    )
                )
                continue
            documents.append((document, None))

        title_counts: dict[str, int] = {}
        for document, explicit in documents:
            if explicit is not None:
                continue
            title_counts[normalize_title(document.title)] = (
                title_counts.get(normalize_title(document.title), 0) + 1
            )

        synced_at = synced_at or utc_now_string()
        planned: list[PlannedUpload] = []
        for document, explicit in documents:
            if explicit is not None:
                planned.append(explicit)
                continue

            key = normalize_title(document.title)
            if title_counts[key] > 1:
                planned.append(
                    PlannedUpload(
                        source=document.path.as_posix(),
                        title=document.title,
                        action="fail",
                        reason="duplicate title in this batch",
                        warnings=tuple(document.warnings),
                    )
                )
                continue

            matches = existing_by_title.get(key, [])
            if len(matches) > 1:
                planned.append(
                    PlannedUpload(
                        source=document.path.as_posix(),
                        title=document.title,
                        action="fail",
                        reason="multiple existing Slite notes share this title",
                        warnings=tuple(document.warnings),
                    )
                )
                continue

            existing = matches[0] if matches else None
            if existing is None:
                action: ActionName = "create"
            elif overwrite:
                action = "update"
            else:
                action = "skip"

            planned.append(
                self._planned(
                    document,
                    action=action,
                    parent_note_id=target.id,
                    existing=existing,
                    include_header=include_header,
                    header_edit_url=header_edit_url,
                    synced_at=synced_at,
                )
            )

        return planned

    def _planned(
        self,
        document: SourceDocument,
        *,
        action: ActionName,
        parent_note_id: str,
        existing: Note | None,
        include_header: bool,
        header_edit_url: str | None,
        synced_at: str,
    ) -> PlannedUpload:
        """Build one plan item, including the rendered body payload."""
        log.debug(
            "Planned action %s for %r (%s)",
            action,
            document.title,
            document.path,
        )
        if action == "skip":
            return PlannedUpload(
                source=document.path.as_posix(),
                title=document.title,
                action=action,
                note_id=existing.id if existing else None,
                note_url=existing.url if existing else None,
                reason="already exists",
                warnings=tuple(document.warnings),
            )

        header = ReadOnlyHeader()
        edit_url = header.build_edit_url(
            template=header_edit_url,
            filename=document.path.name,
            file_basename=document.path.stem,
        )
        body = DocumentRenderer(header).render(
            document,
            synced_at=synced_at,
            edit_url=edit_url,
            include_header=include_header,
        )
        try:
            check_body_size(body)
        except SliteError as exc:
            return PlannedUpload(
                source=document.path.as_posix(),
                title=document.title,
                action="fail",
                reason=str(exc),
                warnings=tuple(document.warnings),
            )

        reason = "overwriting existing note" if action == "update" else None
        return PlannedUpload(
            source=document.path.as_posix(),
            title=document.title,
            action=action,
            parent_note_id=parent_note_id,
            note_id=existing.id if existing else None,
            note_url=existing.url if existing else None,
            body=body,
            reason=reason,
            warnings=tuple(document.warnings),
        )


class UploadExecutor:
    """Apply planned uploads, or return them unchanged in preview mode."""

    def __init__(self, client: SliteApiClient):
        """Store the API client used for writes."""
        self.client = client

    def execute(
        self,
        planned: list[PlannedUpload],
        *,
        apply: bool,
        upload_format: UploadFormat = UploadFormat.markdown,
    ) -> list[UploadAction]:
        """Execute plans with the selected API content field."""
        log.debug(
            "Executing %d planned actions (apply=%s format=%s)",
            len(planned),
            apply,
            upload_format.value,
        )
        actions: list[UploadAction] = []
        for item in planned:
            if not apply or item.action in {"skip", "fail"}:
                log.debug("Not writing %r: action=%s", item.title, item.action)
                actions.append(self._to_action(item))
                continue
            try:
                if item.action == "create":
                    assert item.parent_note_id is not None
                    note = self.client.notes.create_note(
                        parent_note_id=item.parent_note_id,
                        title=item.title,
                        body=item.body or "",
                        body_format=upload_format,
                    )
                elif item.action == "update":
                    assert item.note_id is not None
                    note = self.client.notes.update_note(
                        note_id=item.note_id,
                        title=item.title,
                        body=item.body or "",
                        body_format=upload_format,
                    )
                else:
                    actions.append(self._to_action(item))
                    continue
            except SliteError as exc:
                log.debug("Upload failed for %r: %s", item.title, exc)
                actions.append(
                    UploadAction(
                        source=item.source,
                        title=item.title,
                        action="fail",
                        reason=str(exc),
                        warnings=item.warnings,
                    )
                )
                continue

            log.debug(
                "Completed %s for %r -> note %s",
                item.action,
                item.title,
                note.id,
            )
            actions.append(
                UploadAction(
                    source=item.source,
                    title=item.title,
                    action=item.action,
                    note_id=note.id,
                    url=note.url,
                    reason=item.reason,
                    warnings=item.warnings,
                )
            )

        return actions

    @staticmethod
    def _to_action(item: PlannedUpload) -> UploadAction:
        """Convert a plan item to a non-writing result action."""
        return UploadAction(
            source=item.source,
            title=item.title,
            action=item.action,
            note_id=item.note_id,
            url=item.note_url,
            reason=item.reason,
            warnings=item.warnings,
        )


def _failed_document(path: Path) -> SourceDocument:
    """Create a placeholder document for a file that failed to parse."""
    return SourceDocument(
        path=path,
        title=path.stem,
        body="",
    )
