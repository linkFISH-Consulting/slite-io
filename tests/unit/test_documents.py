"""Document parsing and header rendering tests."""

from pathlib import Path

from slite_io.documents import (
    FrontmatterParser,
    ReadOnlyHeader,
    SourceDocumentLoader,
    TitleResolver,
    utc_now_string,
)


class TestFrontmatterParser:
    def test_parses_yaml_and_strips_frontmatter(self):
        metadata, body = FrontmatterParser().parse(
            "---\ntitle: Auth\nsidebar_label: Login\n---\n\n# Auth\n\nBody\n"
        )

        assert metadata == {"title": "Auth", "sidebar_label": "Login"}
        assert body.startswith("# Auth")

    def test_returns_plain_body_without_frontmatter(self):
        metadata, body = FrontmatterParser().parse("# Plain\n")

        assert metadata == {}
        assert body == "# Plain\n"


class TestTitleResolver:
    def test_precedence_is_title_then_sidebar_then_h1_then_filename(self):
        resolver = TitleResolver()
        path = Path("fallback-name.md")

        assert (
            resolver.resolve({"title": "A", "sidebar_label": "B"}, "# C", path) == "A"
        )
        assert resolver.resolve({"sidebar_label": "B"}, "# C", path) == "B"
        assert resolver.resolve({}, "# C", path) == "C"
        assert resolver.resolve({}, "", path) == "fallback name"

    def test_title_override_wins(self):
        resolver = TitleResolver()

        assert (
            resolver.resolve({"title": "A"}, "# B", Path("x.md"), "Target") == "Target"
        )

    def test_strips_leading_h1_when_it_matches_title(self):
        body, stripped, heading = TitleResolver().strip_leading_duplicate_h1(
            "# Auth\n\nBody\n", "Auth"
        )

        assert stripped is True
        assert heading == "Auth"
        assert body == "Body\n"

    def test_keeps_h1_when_it_differs(self):
        body, stripped, heading = TitleResolver().strip_leading_duplicate_h1(
            "# Other\n\nBody\n", "Auth"
        )

        assert stripped is False
        assert heading == "Other"
        assert body.startswith("# Other")


class TestSourceDocumentLoader:
    def test_loads_document_using_absolute_path(self, tmp_path: Path):
        source = tmp_path / "docs" / "auth.md"
        source.parent.mkdir(parents=True)
        source.write_text(
            "---\ntitle: Authentication\n---\n\n# Authentication\n\nBody\n",
            encoding="utf-8",
        )

        document = SourceDocumentLoader().load(source)

        assert document.path == source
        assert document.title == "Authentication"
        assert document.body == "Body\n"
        assert document.warnings == []


class TestReadOnlyHeader:
    def test_builds_edit_url_from_placeholders(self):
        header = ReadOnlyHeader()

        url = header.build_edit_url(
            template="https://git.example.com/org/docs/edit/main/{filename}",
            filename="auth.md",
            file_basename="auth",
        )

        assert url == "https://git.example.com/org/docs/edit/main/auth.md"

    def test_rejects_unknown_placeholder(self):
        header = ReadOnlyHeader()

        try:
            header.build_edit_url(
                template="https://example.com/{unknown}",
                filename="auth.md",
                file_basename="auth",
            )
        except Exception as exc:
            assert "Unknown placeholder" in str(exc)
        else:
            raise AssertionError("expected DocumentError")

    def test_renders_warning_and_sync_time(self):
        header = ReadOnlyHeader()

        rendered = header.render(
            source_path="docs/auth.md",
            synced_at="2026-11-03 14:05 UTC",
            edit_url="https://git.example.com/org/docs/edit/main/auth.md",
        )

        assert "> [!WARNING]" in rendered
        assert "Read-only mirror" in rendered
        assert "Last synced: 2026-11-03 14:05 UTC" in rendered
        assert "https://git.example.com/org/docs/edit/main/auth.md" in rendered

    def test_utc_timestamp_format(self):
        assert utc_now_string().endswith(" UTC")
