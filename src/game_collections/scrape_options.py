"""Option definitions shared by every `scrape` source command, so their help text lives in one place."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

UrlsOption = Annotated[
    list[str] | None,
    typer.Option("--url", help="Crawl only this bundle page URL (must be one of the source's own); repeatable."),
]
ListsRootOption = Annotated[Path, typer.Option("--lists-root", help="Directory the bundle lists are written to.")]
ArchiveRootOption = Annotated[
    Path, typer.Option("--archive-root", help="Directory the normalized and raw archives are written to.")
]
RefreshOption = Annotated[
    bool,
    typer.Option("--refresh", "--no-cache", help="Redo every bundle, ignoring already-archived output."),
]
NonInteractiveOption = Annotated[
    bool,
    typer.Option("--non-interactive", help="Record unresolved IDs instead of prompting."),
]
