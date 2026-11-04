"""Slite notes API tests with a mocked session."""

import json
from unittest.mock import Mock

import pytest
import requests

from slite_io.api.notes import NotesApiClient, check_body_size
from slite_io.errors import AmbiguousTitleError, SliteAPIError
from slite_io.models import UploadFormat


def _response(payload=None, *, status=200):
    response = Mock()
    response.status_code = status
    response.content = (
        json.dumps(payload).encode("utf-8") if payload is not None else b""
    )
    response.text = json.dumps(payload) if payload is not None else ""
    response.reason = "OK"
    response.headers = {}
    response.json = Mock(return_value=payload if payload is not None else {})
    if status >= 400:
        response.raise_for_status = Mock(side_effect=requests.HTTPError("http error"))
    else:
        response.raise_for_status = Mock()
    return response


class TestNotesApiClient:
    def test_resolves_root_and_folder(self):
        session = Mock()
        session.get.side_effect = [
            _response(
                {
                    "nbPages": 1,
                    "hits": [
                        {"id": "user-1", "title": "My private channel"},
                    ],
                }
            ),
            _response(
                {
                    "hasNextPage": False,
                    "nextCursor": None,
                    "notes": [
                        {
                            "id": "folder-1",
                            "title": "Level 1",
                            "parentNoteId": "user-1",
                        }
                    ],
                }
            ),
            _response(
                {
                    "hasNextPage": False,
                    "nextCursor": None,
                    "notes": [
                        {
                            "id": "folder-2",
                            "title": "Level 2",
                            "parentNoteId": "folder-1",
                        }
                    ],
                }
            ),
        ]

        note = NotesApiClient(session).resolve_folder(
            "My private channel/Level 1/Level 2"
        )

        assert note.id == "folder-2"
        assert note.title == "Level 2"
        assert session.get.call_args_list[0].args[0] == "/search-notes"
        assert session.get.call_args_list[1].args[0] == "/notes/user-1/children"
        assert session.get.call_args_list[2].args[0] == "/notes/folder-1/children"

    def test_ambiguous_root_title_fails(self):
        session = Mock()
        session.get.return_value = _response(
            {
                "nbPages": 1,
                "hits": [
                    {"id": "root-1", "title": "Docs"},
                    {"id": "root-2", "title": "Docs"},
                ],
            }
        )

        with pytest.raises(AmbiguousTitleError):
            NotesApiClient(session).find_root_channel("Docs")

    def test_create_note_sends_markdown_field(self):
        session = Mock()
        session.request.return_value = _response(
            {
                "id": "note-1",
                "title": "Authentication",
                "parentNoteId": "folder-1",
                "url": "https://slite.example/note-1",
            }
        )

        note = NotesApiClient(session).create_note(
            parent_note_id="folder-1",
            title="Authentication",
            body="# Auth",
        )

        assert note.id == "note-1"
        assert session.request.call_args.kwargs["json"] == {
            "parentNoteId": "folder-1",
            "title": "Authentication",
            "markdown": "# Auth",
        }

    def test_create_note_sends_sliteml_field(self):
        session = Mock()
        session.request.return_value = _response(
            {
                "id": "note-1",
                "title": "Authentication",
                "parentNoteId": "folder-1",
            }
        )

        NotesApiClient(session).create_note(
            parent_note_id="folder-1",
            title="Authentication",
            body="<callout>Auth</callout>",
            body_format=UploadFormat.sliteml,
        )

        assert session.request.call_args.kwargs["json"] == {
            "parentNoteId": "folder-1",
            "title": "Authentication",
            "sliteml": "<callout>Auth</callout>",
        }

    def test_api_error_is_typed(self):
        session = Mock()
        session.get.return_value = _response(
            {"message": "Not found", "id": "not-found"}, status=404
        )

        with pytest.raises(SliteAPIError) as exc_info:
            NotesApiClient(session).get_me()

        assert exc_info.value.status_code == 404
        assert exc_info.value.code == "not-found"

    def test_body_size_limit(self):
        with pytest.raises(SliteAPIError):
            check_body_size("x" * 1_000_001)
