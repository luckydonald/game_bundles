"""Interactive storefront-candidate chooser shared by every source's resolver."""

from __future__ import annotations

import typer
from pydantic import Field

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.storefronts import StoreName


class ChosenNames(StrictModel):
    """The user's declaration that one candidate title is actually several separate games."""

    names: list[NonEmptyString] = Field(min_length=1)

# end class ChosenNames


ChosenCandidate = str | ChosenNames | None


def choose_store_candidate(
    title: str,
    provider: StoreName,
    candidates: list[StoreCandidateLike],
) -> ChosenCandidate:
    """Prompt for one storefront result, or declare several separate games via "Multiple…".

    Selecting "Multiple…" loops, collecting one name per separate game (the
    first prompt defaults to `title`, the title just searched, so accepting
    the default alone still records at least one name; a blank answer on any
    later prompt ends the list). Each collected name is later re-run through
    the normal search+resolve flow by the caller, not pasted as a raw ID.
    """
    typer.echo(f"Resolve {title!r} on {provider}:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {candidate.title} — {candidate.qualified_id}")
        typer.echo(f"     {candidate.url}")
    # end for
    multiple = len(candidates) + 1
    other = len(candidates) + 2
    typer.echo(f"  {multiple}. Multiple…")
    typer.echo(f"  {other}. Other…")
    while True:
        selection = typer.prompt("Select a result", default=str(other))
        if selection.isdecimal() and 1 <= int(selection) <= len(candidates):
            return candidates[int(selection) - 1].qualified_id
        # end if
        if selection == str(multiple):
            names: list[str] = []
            while True:
                default = title if not names else ""
                name = typer.prompt("Name of one separate game (blank to finish)", default=default)
                if not name:
                    break
                # end if
                names.append(name)
            # end while
            if not names:
                continue
            # end if
            return ChosenNames(names=names)
        # end if
        if selection == str(other):
            manual = typer.prompt(
                "Paste the store URL or direct ID; leave blank for unresolved",
                default="",
                show_default=False,
            )
            return manual or None
        # end if
        typer.echo(f"Enter a number from 1 to {other}.", err=True)
    # end while
# end def choose_store_candidate
