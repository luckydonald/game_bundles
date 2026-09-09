"""Interactive storefront-candidate chooser shared by every source's resolver."""

from __future__ import annotations

import typer
from pydantic import Field

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.storefronts import StoreName


class ChosenNames(StrictModel):
    """The user's declaration that one candidate title is actually several separate games.

    Returned when `choose_store_candidate` is called with `interleaved=False` (the default,
    used by every caller except `humblebundle.resolver`): all names are collected upfront, then
    re-resolved by the caller afterward.
    """

    names: list[NonEmptyString] = Field(min_length=1)

# end class ChosenNames


class EnterMultiple(StrictModel):
    """The user's declaration that this title is actually several separate games.

    Returned instead of `ChosenNames` when `choose_store_candidate` is called with
    `interleaved=True`: the caller collects and resolves one name at a time (via
    `collect_one_name`), immediately searching each before asking for the next, since only the
    caller - not this module - has search capability. See
    `humblebundle.resolver.StorefrontResolver._resolve_title`.
    """

# end class EnterMultiple


ChosenCandidate = str | ChosenNames | EnterMultiple | None


def announce_exact_match(qualified_id: str, url: str) -> None:
    """Print a short confirmation that a name collected under "Multiple…" resolved uniquely."""
    typer.echo(f"Exact match found — {qualified_id}")
    typer.echo(f"  {url}")
# end def announce_exact_match


def collect_one_name(count: int, known_names: set[str] | None = None) -> str | None:
    """Prompt for one more separate-game name; a blank answer ends the collection.

    `known_names`, when given, is a live set of casefolded names already destined for the
    current bundle/list. A name that collides with one of them is rejected with an error and
    re-prompted immediately, instead of only failing much later when the whole list is validated
    (see `game_collections.models.GameList.validate_games`). An accepted name is added to
    `known_names` before it's returned.
    """
    while True:
        name = typer.prompt(
            f"Name of one separate game ({count} so far) (blank to finish)", default="", show_default=False
        )
        if not name:
            return None
        # end if
        if known_names is not None and name.casefold() in known_names:
            typer.echo(f"{name!r} is already used by another game in this list — enter a different name.", err=True)
            continue
        # end if
        if known_names is not None:
            known_names.add(name.casefold())
        # end if
        return name
    # end while
# end def collect_one_name


def choose_store_candidate(
    title: str,
    provider: StoreName,
    candidates: list[StoreCandidateLike],
    *,
    allow_multiple: bool = True,
    interleaved: bool = False,
    known_names: set[str] | None = None,
) -> ChosenCandidate:
    """Prompt for one storefront result, or declare several separate games via "Multiple…".

    `allow_multiple=False` omits the "Multiple…" row entirely - used for a name already
    collected inside another "Multiple…" declaration, where offering to split it again makes no
    sense. `interleaved=True` (used only by `humblebundle.resolver`, whose caller can search
    immediately) returns `EnterMultiple` as soon as "Multiple…" is chosen instead of collecting
    names itself; `interleaved=False` (every other caller) keeps the original behavior: looping
    to collect one name per separate game (the first prompt defaults to `title`, the title just
    searched, so accepting the default alone still records at least one name; a blank answer on
    any later prompt ends the list) and returning them all at once as `ChosenNames`.

    `known_names`, when given, is a live set of casefolded names already destined for the current
    bundle/list (the caller is expected to have removed `title` itself from it beforehand, since
    accepting the default just keeps this entry under its own name). A typed name that collides
    with `known_names`, or with another name already collected in this same "Multiple…" session,
    is rejected with an error and re-prompted rather than silently producing a duplicate that
    would only be caught much later by `game_collections.models.GameList.validate_games`. Every
    accepted name is added to `known_names` immediately.
    """
    typer.echo(f"Resolve {title!r} on {provider}:")
    for index, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {index}. {candidate.title} — {candidate.qualified_id}")
        typer.echo(f"     {candidate.url}")
    # end for
    multiple = len(candidates) + 1 if allow_multiple else None
    other = len(candidates) + (2 if allow_multiple else 1)
    if multiple is not None:
        typer.echo(f"  {multiple}. Multiple…")
    # end if
    typer.echo(f"  {other}. Other…")
    while True:
        selection = typer.prompt("Select a result", default=str(other))
        if selection.isdecimal() and 1 <= int(selection) <= len(candidates):
            return candidates[int(selection) - 1].qualified_id
        # end if
        if multiple is not None and selection == str(multiple):
            if interleaved:
                return EnterMultiple()
            # end if
            names: list[str] = []
            while True:
                default = title if not names else ""
                name = typer.prompt("Name of one separate game (blank to finish)", default=default)
                if not name:
                    break
                # end if
                if known_names is not None and name.casefold() in known_names:
                    typer.echo(
                        f"{name!r} is already used by another game in this list — enter a different name.",
                        err=True,
                    )
                    continue
                # end if
                names.append(name)
                if known_names is not None:
                    known_names.add(name.casefold())
                # end if
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
