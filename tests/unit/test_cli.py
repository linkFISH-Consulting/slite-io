"""CLI smoke tests and API key resolution tests."""

import logging
from pathlib import Path

from typer.testing import CliRunner

from slite_io.cli import app
from slite_io.cli.utils import ApiKeyResolver

runner = CliRunner()


class TestCli:
    def test_version_option(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SLITE_API_KEY", raising=False)
        monkeypatch.delenv("SLITE_API_KEY_FILE", raising=False)

        result = runner.invoke(app, ["--version"])

        assert result.exit_code == 0
        assert "slite-io version" in result.output

    def test_verbose_option_enables_debug_logging(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "auth.md").write_text("# Auth\n", encoding="utf-8")
        logger = logging.getLogger("slite_io")
        previous_level = logger.level
        try:
            result = runner.invoke(
                app,
                ["-v", "validate", "--include-files", "auth.md"],
            )
            assert result.exit_code == 0
            assert logger.level == logging.DEBUG
        finally:
            logger.setLevel(previous_level)

    def test_upload_format_choices_are_exposed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SLITE_API_KEY", raising=False)
        monkeypatch.delenv("SLITE_API_KEY_FILE", raising=False)

        result = runner.invoke(app, ["upload-single", "--help"])

        assert result.exit_code == 0
        assert "markdown" in result.output
        assert "sliteml" in result.output

    def test_validate_offline(self, tmp_path: Path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "auth.md").write_text("# Auth\n\nBody\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "validate",
                "--include-files",
                "docs/**/*.md",
            ],
        )

        assert result.exit_code == 0
        assert "Validation summary" in result.output
        assert "valid" in result.output
        assert "Counts: valid=1" in result.output


class TestApiKeyResolver:
    def test_cli_wins(self, monkeypatch):
        monkeypatch.setenv("SLITE_API_KEY", "env-key")

        assert ApiKeyResolver().resolve("cli-key") == "cli-key"

    def test_environment_wins_over_file(self, monkeypatch, tmp_path: Path):
        key_file = tmp_path / "key"
        key_file.write_text("file-key", encoding="utf-8")
        monkeypatch.setenv("SLITE_API_KEY", "env-key")
        monkeypatch.setenv("SLITE_API_KEY_FILE", str(key_file))

        assert ApiKeyResolver().resolve(None) == "env-key"

    def test_file_is_used_as_fallback(self, monkeypatch, tmp_path: Path):
        key_file = tmp_path / "key"
        key_file.write_text("file-key", encoding="utf-8")
        monkeypatch.delenv("SLITE_API_KEY", raising=False)
        monkeypatch.setenv("SLITE_API_KEY_FILE", str(key_file))

        assert ApiKeyResolver().resolve(None) == "file-key"
