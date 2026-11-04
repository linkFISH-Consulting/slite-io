from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich.text import Text

from slite_io.api import DEFAULT_API_URL, SliteApiClient
from slite_io.documents import SourceDocumentLoader
from slite_io.errors import DocumentError, SliteIOError
from slite_io.logger import console_width, setup_logging_handler
from slite_io.models import UploadAction, UploadFormat, UploadResult
from slite_io.selection import FileSelector
from slite_io.upload import UploadExecutor, UploadPlanner
from slite_io.utils import get_version

from .utils import ApiKeyResolver, catch_exception

load_dotenv()

log = logging.getLogger("slite_io")

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    add_completion=False,
)


class SliteContext(typer.Context):
    """Typed Typer context carrying the lazily created Slite client."""

    obj: SliteApiClient | None


def _version_callback(value: bool) -> None:
    """Print the version for the eager --version option."""
    if value:
        typer.echo(f"slite-io version {get_version()}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    api_key: Annotated[
        str | None,
        typer.Option(
            help="Slite API key. Prefer SLITE_API_KEY or SLITE_API_KEY_FILE.",
            hide_input=True,
            envvar="SLITE_API_KEY",
        ),
    ] = None,
    base_url: Annotated[
        str,
        typer.Option(help="Slite API base URL.", envvar="SLITE_API_URL"),
    ] = DEFAULT_API_URL,
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase verbosity (-v, -vv, -vvv).",
        ),
    ] = 0,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Mirror Markdown/MDX documentation into Slite notes."""
    setup_logging_handler(verbose)
    if version:
        return
    if ctx.invoked_subcommand is None or ctx.invoked_subcommand == "validate":
        return
    if "--help" in sys.argv[1:]:
        return

    key = ApiKeyResolver().resolve(api_key)
    ctx.obj = SliteApiClient.from_api_key(key, base_url)


def _client(ctx: typer.Context) -> SliteApiClient:
    """Return the initialized Slite client or fail clearly."""
    client = ctx.obj
    if not isinstance(client, SliteApiClient):
        raise SliteIOError("Slite client is not initialized.")
    return client


def _highlight_last(path: str) -> Text:
    """Render a path in gray with its final element highlighted."""
    text = Text(style="grey62")
    if not path or path == "-":
        text.append("-")
        return text
    parent, _, final = path.rstrip("/").rpartition("/")
    if parent:
        text.append(f"{parent}/")
    text.append(final, style="bold white")
    return text


def _print_result(result: UploadResult) -> None:
    """Print an aligned summary table for all actions."""
    title = "Validation summary" if result.command == "validate" else "Upload summary"
    table = Table(title=title, show_lines=True)
    table.add_column("Action", no_wrap=True)
    table.add_column("Note", overflow="fold")

    styles = {
        "create": "green",
        "update": "cyan",
        "skip": "yellow",
        "fail": "red",
        "valid": "green",
    }

    for action in result.actions:
        details = [action.reason] if action.reason else []
        details.extend(f"warning: {warning}" for warning in action.warnings)
        if result.command == "upload-batch":
            slite_path = f"{result.target.rstrip('/')}/{action.title}"
        elif result.command == "upload-single":
            slite_path = result.target
        else:
            slite_path = "-"

        note = Table.grid(padding=(0, 2))
        note.add_column(no_wrap=True)
        note.add_column(overflow="fold")
        note.add_row(Text("Source", style="grey62"), _highlight_last(action.source))
        note.add_row(Text("Slite", style="grey62"), _highlight_last(slite_path))
        note.add_row(
            Text("URL", style="grey62"),
            Text(action.url or action.note_id or "-", style="grey62"),
        )
        note.add_row(
            Text("Details", style="grey62"),
            Text("\n".join(details) or "-", style="grey62"),
        )

        table.add_row(
            Text(action.action, style=styles.get(action.action, "white")),
            note,
        )

    console = Console(width=console_width())
    console.print(table)

    summary = result.summary()
    log.info(
        "Counts: %s",
        ", ".join(f"{key}={value}" for key, value in summary.items() if value),
    )
    if result.command.startswith("upload-") and not result.apply:
        log.info("Preview only; rerun with --apply to write.")


@app.command("upload-single")
@catch_exception(exception=SliteIOError, exit_code=1)
def upload_single(
    ctx: typer.Context,
    source_file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Markdown/MDX file to upload.",
        ),
    ],
    target_note: Annotated[
        str,
        typer.Option(
            help=(
                "Absolute root-channel path, e.g. "
                '"My private channel/Level 1/Level 2/Auth".'
            )
        ),
    ],
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write to Slite. Without this, preview only."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Update an existing note. Default: skip it.",
        ),
    ] = False,
    upload_format: Annotated[
        UploadFormat,
        typer.Option(
            "--upload-format",
            help="Slite API content field: markdown or sliteml.",
        ),
    ] = UploadFormat.markdown,
    header: Annotated[
        bool,
        typer.Option(
            "--header/--no-header",
            help="Prepend the generated read-only header.",
        ),
    ] = True,
    header_edit_url: Annotated[
        str | None,
        typer.Option(
            "--header-edit-url",
            help="Edit URL with {filename} and {file_basename} placeholders.",
        ),
    ] = None,
) -> None:
    """Upload one Markdown/MDX file to an explicit Slite note."""
    log.debug(
        "Command upload-single: source=%s target=%r apply=%s overwrite=%s format=%s",
        source_file,
        target_note,
        apply,
        overwrite,
        upload_format.value,
    )
    client = _client(ctx)
    planned = UploadPlanner(client).plan_single(
        source_file,
        target_note=target_note,
        overwrite=overwrite,
        include_header=header,
        header_edit_url=header_edit_url,
    )
    actions = UploadExecutor(client).execute(
        planned,
        apply=apply,
        upload_format=upload_format,
    )
    result = UploadResult(
        command="upload-single",
        apply=apply,
        target=target_note,
        actions=actions,
    )
    _print_result(result)
    raise typer.Exit(code=result.exit_code())


@app.command("upload-batch")
@catch_exception(exception=SliteIOError, exit_code=1)
def upload_batch(
    ctx: typer.Context,
    target_folder: Annotated[
        str,
        typer.Option(
            help=(
                "Existing absolute root-channel folder, e.g. "
                '"My private channel/Level 1/Level 2".'
            )
        ),
    ],
    include_files: Annotated[
        list[str] | None,
        typer.Option(
            "--include-files",
            help="Include glob; repeatable. Defaults to **/*.md and **/*.mdx.",
        ),
    ] = None,
    exclude_files: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-files",
            help="Exclude glob applied after includes; repeatable.",
        ),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Write to Slite. Without this, preview only."),
    ] = False,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite/--no-overwrite",
            help="Update existing notes. Default: skip them.",
        ),
    ] = False,
    upload_format: Annotated[
        UploadFormat,
        typer.Option(
            "--upload-format",
            help="Slite API content field: markdown or sliteml.",
        ),
    ] = UploadFormat.markdown,
    header: Annotated[
        bool,
        typer.Option(
            "--header/--no-header",
            help="Prepend the generated read-only header.",
        ),
    ] = True,
    header_edit_url: Annotated[
        str | None,
        typer.Option(
            "--header-edit-url",
            help="Edit URL with {filename} and {file_basename} placeholders.",
        ),
    ] = None,
) -> None:
    """Upload many files flat under one existing Slite folder."""
    log.debug(
        "Command upload-batch: target=%r includes=%s excludes=%s apply=%s "
        "overwrite=%s format=%s",
        target_folder,
        include_files,
        exclude_files,
        apply,
        overwrite,
        upload_format.value,
    )
    client = _client(ctx)
    planned = UploadPlanner(client).plan_batch(
        target_folder=target_folder,
        includes=include_files,
        excludes=exclude_files,
        overwrite=overwrite,
        include_header=header,
        header_edit_url=header_edit_url,
    )
    actions = UploadExecutor(client).execute(
        planned,
        apply=apply,
        upload_format=upload_format,
    )
    result = UploadResult(
        command="upload-batch",
        apply=apply,
        target=target_folder,
        actions=actions,
    )
    _print_result(result)
    raise typer.Exit(code=result.exit_code())


@app.command("validate")
@catch_exception(exception=SliteIOError, exit_code=1)
def validate(
    include_files: Annotated[
        list[str] | None,
        typer.Option(
            "--include-files",
            help="Include glob; repeatable. Defaults to **/*.md and **/*.mdx.",
        ),
    ] = None,
    exclude_files: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-files",
            help="Exclude glob applied after includes; repeatable.",
        ),
    ] = None,
) -> None:
    """Parse files and report problems without contacting Slite."""
    log.debug(
        "Command validate: includes=%s excludes=%s",
        include_files,
        exclude_files,
    )
    selector = FileSelector()
    loader = SourceDocumentLoader()
    files = selector.select(
        includes=include_files,
        excludes=exclude_files,
    )
    actions: list[UploadAction] = []
    for path in files:
        try:
            document = loader.load(path)
        except DocumentError as exc:
            actions.append(
                UploadAction(
                    source=path.as_posix(),
                    title=path.stem,
                    action="fail",
                    reason=str(exc),
                )
            )
            continue
        actions.append(
            UploadAction(
                source=document.path.as_posix(),
                title=document.title,
                action="skip" if document.draft else "valid",
                reason="draft: true" if document.draft else None,
                warnings=tuple(document.warnings),
            )
        )

    result = UploadResult(
        command="validate",
        apply=False,
        target="",
        actions=actions,
    )
    _print_result(result)
    raise typer.Exit(code=result.exit_code())


@app.command("doctor")
@catch_exception(exception=SliteIOError, exit_code=1)
def doctor(
    ctx: typer.Context,
    target_folder: Annotated[
        str | None,
        typer.Option(help="Optional target folder path to resolve."),
    ] = None,
) -> None:
    """Check API access and optionally resolve a target folder."""
    log.debug("Command doctor: target_folder=%r", target_folder)
    client = _client(ctx)
    me = client.test_connection()
    payload: dict[str, object] = {
        "display_name": me.get("displayName"),
        "email": me.get("email"),
        "organization": me.get("organizationName"),
        "domain": me.get("organizationDomain"),
    }
    if target_folder:
        note = client.notes.resolve_folder(target_folder)
        payload["target"] = {"id": note.id, "title": note.title}

    log.info("Connected as %s <%s>", payload["display_name"], payload["email"])
    log.info(
        "Organization: %s (%s)",
        payload["organization"],
        payload["domain"],
    )
    if "target" in payload:
        target = payload["target"]
        assert isinstance(target, dict)
        log.info("Target: %s (%s)", target["title"], target["id"])
