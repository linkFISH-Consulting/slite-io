from importlib import metadata


def get_version() -> str:
    """Return the installed distribution version."""
    try:
        return metadata.version("slite-io")
    except metadata.PackageNotFoundError:
        return "[not found] Use `uv sync` when developing!"
