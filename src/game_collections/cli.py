"""Command-line interface for game list validation and synchronization."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from game_collections.lists import ListLoadError, discover_game_lists
from game_collections.schema import write_schema


app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


def _lists_root(path: Path | None) -> Path:
    return path or Path.cwd() / "lists"
# end def _lists_root


@app.command("validate")
def validate_command(
    path: Annotated[Path | None, typer.Argument(help="Lists root; defaults to ./lists.")] = None,
) -> None:
    """Validate every YAML game list."""
    try:
        loaded = discover_game_lists(_lists_root(path))
    except (OSError, ValueError, ListLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
    typer.echo(f"Validated {len(loaded)} game list(s).")
# end def validate_command


@app.command("list")
def list_command(
    path: Annotated[Path | None, typer.Option("--lists-root")] = None,
) -> None:
    """Print all path-derived IDs and display names."""
    try:
        loaded = discover_game_lists(_lists_root(path))
    except (OSError, ValueError, ListLoadError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
    for game_list in loaded:
        typer.echo(f"{game_list.id}\t{game_list.data.name}")
    # end for
# end def list_command


@app.command("schema")
def schema_command(
    output: Annotated[
        Path,
        typer.Option("--output", help="Generated JSON Schema path."),
    ] = Path("schemas/game-list.schema.json"),
) -> None:
    """Generate JSON Schema from the runtime Pydantic models."""
    write_schema(output)
    typer.echo(output)
# end def schema_command


if __name__ == "__main__":
    app()
# end if

