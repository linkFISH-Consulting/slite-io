from __future__ import annotations

import logging
import os
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

import typer

from slite_io.errors import SliteIOError

E = TypeVar("E", bound=Exception, covariant=True)
P = ParamSpec("P")
R = TypeVar("R")

log = logging.getLogger("slite_io")


class ApiKeyResolver:
    """Resolve the Slite API key from CLI, environment, or a key file."""

    def resolve(self, cli_value: str | None) -> str:
        """Resolve the key from CLI, environment, or the key file."""
        if cli_value and cli_value.strip():
            return cli_value.strip()

        env_value = os.environ.get("SLITE_API_KEY")
        if env_value and env_value.strip():
            return env_value.strip()

        key_file = os.environ.get("SLITE_API_KEY_FILE")
        if key_file:
            path = Path(key_file).expanduser()
            try:
                value = path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise SliteIOError(f"Could not read SLITE_API_KEY_FILE: {exc}") from exc
            if value:
                return value
            raise SliteIOError(f"SLITE_API_KEY_FILE is empty: {path}")

        raise SliteIOError(
            "No Slite API key. Pass --api-key, set SLITE_API_KEY, or set "
            "SLITE_API_KEY_FILE."
        )


def default_convert(exc: Exception) -> str:
    """Format an exception for concise CLI output."""
    return f"{exc.__class__.__name__}: {exc}"


def catch_exception(
    exception: type[E],
    exit_code: int = 1,
    converter: Callable[[E], str] = default_convert,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log selected exceptions without a traceback and exit with a code."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        """Wrap one CLI command."""

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            """Run the command and convert selected exceptions."""
            try:
                return func(*args, **kwargs)
            except exception as exc:
                log.error("%s", converter(exc))
                raise typer.Exit(code=exit_code) from exc

        return wrapper

    return decorator
