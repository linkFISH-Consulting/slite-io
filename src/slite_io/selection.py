from __future__ import annotations

import glob
import logging
from pathlib import Path

MARKDOWN_SUFFIXES = {".md", ".mdx"}
log = logging.getLogger("slite_io")
SKIP_DIRECTORIES = {".git", ".venv", "node_modules"}


class FileSelector:
    """Expand include/exclude globs into a set of absolute Markdown files."""

    default_includes = ("**/*.md", "**/*.mdx")

    def select(
        self,
        *,
        includes: list[str] | None = None,
        excludes: list[str] | None = None,
    ) -> list[Path]:
        """Return ``include_set - exclude_set`` in deterministic order."""
        include_patterns = includes or list(self.default_includes)
        exclude_patterns = excludes or []
        log.debug("Expanding include globs: %s", include_patterns)
        log.debug("Expanding exclude globs: %s", exclude_patterns)
        include_files = self._expand(include_patterns)
        exclude_files = self._expand(exclude_patterns)
        selected = sorted(
            include_files - exclude_files,
            key=lambda path: path.as_posix(),
        )
        log.debug(
            "Selected %d files (%d included, %d excluded)",
            len(selected),
            len(include_files),
            len(exclude_files),
        )
        return selected

    def _expand(self, patterns: list[str]) -> set[Path]:
        """Expand each glob independently into absolute file paths."""
        files: set[Path] = set()
        for pattern in patterns:
            pattern_path = Path(pattern).expanduser()
            if not pattern_path.is_absolute():
                pattern_path = Path.cwd() / pattern_path
            for match in glob.glob(str(pattern_path), recursive=True):  # noqa: PTH207
                path = Path(match)
                if not path.is_file():
                    continue
                if path.suffix.lower() not in MARKDOWN_SUFFIXES:
                    continue
                if any(part in SKIP_DIRECTORIES for part in path.parts):
                    continue
                files.add(path.resolve())
        return files
