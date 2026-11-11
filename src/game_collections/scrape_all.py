"""Run several `scrape` sources one after another, collecting failures instead of aborting.

Kept independent of `cli.py` (which builds the registry of concrete scrapers) so the
orchestration can be tested without importing every crawler.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import typer

from game_collections import scrape_git


class ScrapeKind(StrEnum):
    """Whether a source crawls a store's own site or a third-party listing of bundles."""

    # The store's own site; the cleanest results, so these run first.
    DIRECT = "direct"
    # Third-party listings that skip bundles a direct scraper already covers.
    AGGREGATE = "aggregate"

# end class ScrapeKind


@dataclass(frozen=True)
class ScraperSpec:
    """One registered scrape source and how to invoke its CLI command."""

    name: str
    kind: ScrapeKind
    # Receives the context (with `ctx.obj` set to the per-source git session), `refresh`
    # and `non_interactive`; forwards only the options the concrete command supports.
    run: Callable[[typer.Context, bool, bool], None]

# end class ScraperSpec


@dataclass(frozen=True)
class ScraperFailure:
    """A source which raised or exited non-zero during an `all` run."""

    name: str
    reason: str

# end class ScraperFailure


def select_scrapers(
    registry: Sequence[ScraperSpec], kinds: Sequence[ScrapeKind], skip: Sequence[str]
) -> list[ScraperSpec]:
    """Pick the specs of the given kinds, ordered by `kinds` and then registry order.

    Raises `typer.BadParameter` for a `skip` name that is not a registered source,
    so a typo does not silently scrape the source the user meant to leave out.
    """
    known = {spec.name for spec in registry}
    unknown = sorted(set(skip) - known)
    if unknown:
        raise typer.BadParameter(f"unknown source(s) {', '.join(unknown)}; choose from {', '.join(sorted(known))}")
    # end if
    return [spec for kind in kinds for spec in registry if spec.kind == kind and spec.name not in skip]
# end def select_scrapers


def run_scrapers(
    ctx: typer.Context,
    specs: Sequence[ScraperSpec],
    refresh: bool,
    non_interactive: bool,
) -> list[ScraperFailure]:
    """Run every spec in order and return the failures; never stops at the first one."""
    session: scrape_git.ScrapeGitSession = ctx.obj
    failures: list[ScraperFailure] = []
    try:
        for index, spec in enumerate(specs, start=1):
            typer.echo(f"=== Source {index}/{len(specs)}: {spec.name} ({spec.kind.value}) ===")
            # Each source still commits its own output, but only the very end of the whole
            # run may restore the autostash or integrate the worktree - doing either after the
            # first source would hand the checkout back while later sources are still writing.
            ctx.obj = dataclasses.replace(session, stashed=False, defer_close=True)
            try:
                spec.run(ctx, refresh, non_interactive)
            except typer.Exit as error:
                if error.exit_code == 0:
                    continue
                # end if
                failures.append(ScraperFailure(spec.name, f"exited with code {error.exit_code}"))
            except (OSError, ValueError, RuntimeError) as error:
                failures.append(ScraperFailure(spec.name, f"{type(error).__name__}: {error}"))
            # end try
            if failures and failures[-1].name == spec.name:
                typer.echo(f"error: {spec.name}: {failures[-1].reason}", err=True)
            # end if
        # end for
    finally:
        ctx.obj = session
        scrape_git.close_scrape_git_session(session)
    # end try
    return failures
# end def run_scrapers


def report_failures(specs: Sequence[ScraperSpec], failures: Sequence[ScraperFailure]) -> None:
    """Print the closing summary and exit 1 when any source failed."""
    typer.echo(f"{len(specs) - len(failures)}/{len(specs)} source(s) succeeded.")
    if not failures:
        return
    # end if
    typer.echo("Failed sources:", err=True)
    for failure in failures:
        typer.echo(f"  {failure.name}: {failure.reason}", err=True)
    # end for
    raise typer.Exit(1)
# end def report_failures
