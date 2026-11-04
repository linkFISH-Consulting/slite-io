from __future__ import annotations

import logging
import shutil

from rich.console import Console, ConsoleRenderable
from rich.highlighter import NullHighlighter
from rich.logging import RichHandler
from rich.text import Text
from rich.theme import Theme
from rich.traceback import install

log = logging.getLogger("slite_io")


def console_width() -> int:
    """Return the current terminal width with a readable non-TTY fallback."""
    return max(80, shutil.get_terminal_size((120, 24)).columns)


def setup_logging_handler(verbose_level: int = 0) -> None:
    """Configure logging for the CLI's verbosity level.

    Levels:
        0: INFO, minimal formatting.
        1: DEBUG, path shown.
        2: DEBUG, path/level/time and local tracebacks.
        3: DEBUG for all modules, with logger names.
    """
    verbose_level = max(0, min(verbose_level, 3))

    console = Console(
        width=console_width(),
        theme=Theme(
            {
                "message.debug": "dim",
                "message.warning": "yellow",
                "message.critical": "red",
                "message.error": "bold red",
            }
            if verbose_level < 2
            else {}
        ),
    )

    if verbose_level < 2:
        install(show_locals=False, extra_lines=0)

    level_mapping = {
        0: logging.INFO,
        1: logging.DEBUG,
        2: logging.DEBUG,
        3: logging.DEBUG,
    }
    level = level_mapping.get(verbose_level, logging.INFO)

    handler = ColoredHandler(
        console=console,
        markup=False,
        tracebacks_max_frames=1,
        tracebacks_show_locals=(verbose_level >= 2),
        show_path=(verbose_level >= 1),
        show_level=(verbose_level >= 2),
        show_time=(verbose_level >= 2),
        highlighter=NullHighlighter(),
    )

    log.handlers.clear()

    if verbose_level == 3:
        log.propagate = True
        logging.basicConfig(
            level=logging.DEBUG,
            format="[%(name)s] %(message)s",
            datefmt="[%X]",
            handlers=[handler],
            force=True,
        )
    else:
        log.propagate = False
        handler.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(handler)
        log.setLevel(level)

    log.debug("Set logging level to %s", logging.getLevelName(level))


class ColoredHandler(RichHandler):
    """RichHandler that styles messages by log level."""

    def render_message(
        self, record: logging.LogRecord, message: str
    ) -> ConsoleRenderable:
        """Render the message and apply the level-specific theme style."""
        message_text = super().render_message(record, message)
        if isinstance(message_text, Text):
            message_text.stylize(style=f"message.{record.levelname.lower()}")
        return message_text
