"""File selection tests."""

from pathlib import Path

from slite_io.selection import FileSelector


class TestFileSelection:
    def test_selects_markdown_and_mdx_recursively(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "intro.md").write_text("# Intro", encoding="utf-8")
        (tmp_path / "docs" / "api").mkdir()
        (tmp_path / "docs" / "api" / "auth.mdx").write_text("# Auth", encoding="utf-8")
        (tmp_path / "docs" / "notes.txt").write_text("ignored", encoding="utf-8")

        selected = FileSelector().select(
            includes=["docs/**/*.md", "docs/**/*.mdx"],
        )

        assert [path.name for path in selected] == ["auth.mdx", "intro.md"]

    def test_excludes_are_subtracted_from_includes(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "keep.md").write_text("# Keep", encoding="utf-8")
        (tmp_path / "docs" / "_draft.md").write_text("# Draft", encoding="utf-8")

        selected = FileSelector().select(
            includes=["docs/**/*.md"],
            excludes=["docs/**/_*.md"],
        )

        assert [path.name for path in selected] == ["keep.md"]

    def test_absolute_include_pattern_works_outside_cwd(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "repo"
        root.mkdir()
        source = tmp_path / "outside.md"
        source.write_text("# Outside", encoding="utf-8")
        monkeypatch.chdir(root)

        selected = FileSelector().select(includes=[source.as_posix()])

        assert selected == [source.resolve()]
