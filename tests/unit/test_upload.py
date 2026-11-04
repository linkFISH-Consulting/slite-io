"""Upload planning and execution tests."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from slite_io.models import Note, UploadFormat
from slite_io.upload import UploadExecutor, UploadPlanner


@pytest.fixture(autouse=True)
def _chdir_to_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def _doc(tmp_path: Path, name: str, title: str) -> Path:
    path = tmp_path / "docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {title}\n---\n\n# {title}\n\nBody\n",
        encoding="utf-8",
    )
    return path


class TestUploadPlanner:
    def test_single_creates_when_missing(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_parent_and_title.return_value = (
            Note(id="folder-1", title="Folder", parent_note_id="root"),
            "Authentication",
        )
        client.notes.find_child_optional.return_value = None
        source = _doc(tmp_path, "auth.md", "Source title")

        planned = UploadPlanner(client).plan_single(
            source,
            target_note="Root/Folder/Authentication",
            overwrite=False,
            include_header=True,
            header_edit_url="https://git.example.com/org/docs/edit/main/{filename}",
        )

        assert planned[0].action == "create"
        assert planned[0].title == "Authentication"
        assert "Read-only mirror" in (planned[0].body or "")
        assert planned[0].source == source.resolve().as_posix()
        assert "edit/main/auth.md" in (planned[0].body or "")

    def test_single_skips_existing_without_overwrite(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_parent_and_title.return_value = (
            Note(id="folder-1", title="Folder", parent_note_id="root"),
            "Authentication",
        )
        client.notes.find_child_optional.return_value = Note(
            id="note-1", title="Authentication", parent_note_id="folder-1"
        )
        source = _doc(tmp_path, "auth.md", "Authentication")

        planned = UploadPlanner(client).plan_single(
            source,
            target_note="Root/Folder/Authentication",
            overwrite=False,
            include_header=True,
            header_edit_url=None,
        )

        assert planned[0].action == "skip"
        assert planned[0].note_id == "note-1"

    def test_single_updates_existing_with_overwrite(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_parent_and_title.return_value = (
            Note(id="folder-1", title="Folder", parent_note_id="root"),
            "Authentication",
        )
        client.notes.find_child_optional.return_value = Note(
            id="note-1", title="Authentication", parent_note_id="folder-1"
        )
        source = _doc(tmp_path, "auth.md", "Authentication")

        planned = UploadPlanner(client).plan_single(
            source,
            target_note="Root/Folder/Authentication",
            overwrite=True,
            include_header=True,
            header_edit_url=None,
        )

        assert planned[0].action == "update"
        assert planned[0].note_id == "note-1"
        assert planned[0].reason == "overwriting existing note"

    def test_batch_marks_duplicate_titles_as_failed(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_folder.return_value = Note(
            id="folder-1", title="Folder", parent_note_id="root"
        )
        client.notes.list_children.return_value = []
        _doc(tmp_path, "one.md", "Same")
        _doc(tmp_path, "two.md", "Same")

        planned = UploadPlanner(client).plan_batch(
            target_folder="Root/Folder",
            includes=None,
            excludes=None,
            overwrite=False,
            include_header=True,
            header_edit_url=None,
        )

        assert [item.action for item in planned] == ["fail", "fail"]
        assert all("duplicate title" in (item.reason or "") for item in planned)

    def test_batch_skips_drafts(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_folder.return_value = Note(
            id="folder-1", title="Folder", parent_note_id="root"
        )
        client.notes.list_children.return_value = []
        path = tmp_path / "docs" / "draft.md"
        path.parent.mkdir(parents=True)
        path.write_text(
            "---\ntitle: Draft\ndraft: true\n---\n\nBody\n",
            encoding="utf-8",
        )

        planned = UploadPlanner(client).plan_batch(
            target_folder="Root/Folder",
            includes=None,
            excludes=None,
            overwrite=False,
            include_header=True,
            header_edit_url=None,
        )

        assert planned[0].action == "skip"
        assert planned[0].reason == "draft: true"


class TestUploadExecutor:
    def test_preview_does_not_write(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_parent_and_title.return_value = (
            Note(id="folder-1", title="Folder", parent_note_id="root"),
            "Authentication",
        )
        client.notes.find_child_optional.return_value = None
        source = _doc(tmp_path, "auth.md", "Authentication")
        planned = UploadPlanner(client).plan_single(
            source,
            target_note="Root/Folder/Authentication",
            overwrite=False,
            include_header=True,
            header_edit_url=None,
        )

        actions = UploadExecutor(client).execute(planned, apply=False)

        assert actions[0].action == "create"
        client.notes.create_note.assert_not_called()

    def test_apply_creates_note(self, tmp_path: Path):
        client = Mock()
        client.notes.resolve_parent_and_title.return_value = (
            Note(id="folder-1", title="Folder", parent_note_id="root"),
            "Authentication",
        )
        client.notes.find_child_optional.return_value = None
        client.notes.create_note.return_value = Note(
            id="note-1",
            title="Authentication",
            parent_note_id="folder-1",
            url="https://slite.example/note-1",
        )
        source = _doc(tmp_path, "auth.md", "Authentication")
        planned = UploadPlanner(client).plan_single(
            source,
            target_note="Root/Folder/Authentication",
            overwrite=False,
            include_header=True,
            header_edit_url=None,
        )

        actions = UploadExecutor(client).execute(
            planned,
            apply=True,
            upload_format=UploadFormat.sliteml,
        )

        assert actions[0].action == "create"
        assert actions[0].note_id == "note-1"
        client.notes.create_note.assert_called_once()
        assert (
            client.notes.create_note.call_args.kwargs["body_format"]
            == UploadFormat.sliteml
        )
