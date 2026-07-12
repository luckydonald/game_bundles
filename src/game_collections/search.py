"""Launcher-neutral storefront search and draft-list completion."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any, Literal, cast

from game_collections.models import GameList, QualifiedGameId
from game_collections.sources.humblebundle.resolver import (
    ALLOWED_STORES,
    StoreCandidate,
    StoreName,
    StorefrontResolver,
    normalized_title,
    parse_store_identity,
)


ProviderSelection = StoreName | Literal["all"]
SearchChooser = Callable[[str, StoreName, list[StoreCandidate]], str | None]


def selected_providers(provider: str) -> tuple[StoreName, ...]:
    """Validate a provider selection and expand ``all`` deterministically."""
    if provider == "all":
        return ALLOWED_STORES
    # end if
    if provider not in ALLOWED_STORES:
        choices = ", ".join(("all", *ALLOWED_STORES))
        raise ValueError(f"unknown provider {provider!r}; choose one of: {choices}")
    # end if
    return (cast(StoreName, provider),)
# end def selected_providers


def resolve_title(
    title: str,
    providers: tuple[StoreName, ...],
    resolver: StorefrontResolver,
    choose: SearchChooser,
) -> list[str]:
    """Resolve a title once per provider, accepting unique exact matches."""
    ids: list[str] = []
    for provider in providers:
        candidates = resolver.search(provider, title)
        exact = [
            candidate
            for candidate in candidates
            if normalized_title(candidate.title) == normalized_title(title)
        ]
        if len(exact) == 1:
            ids.append(exact[0].qualified_id)
            continue
        # end if
        selected = choose(title, provider, candidates)
        if selected is None:
            continue
        # end if
        ids.append(parse_store_identity(provider, selected))
    # end for
    return list(dict.fromkeys(ids))
# end def resolve_title


def complete_game_list(
    raw: object,
    providers: tuple[StoreName, ...],
    resolver: StorefrontResolver,
    choose: SearchChooser,
) -> tuple[dict[str, Any], list[str]]:
    """Fill missing game IDs in a draft list and return unresolved names."""
    if not isinstance(raw, Mapping):
        raise ValueError("YAML list must contain an object")
    # end if
    completed = deepcopy(dict(raw))
    games = completed.get("games")
    if not isinstance(games, list) or not games:
        raise ValueError("draft list must contain a non-empty games list")
    # end if
    unresolved: list[str] = []
    for index, game in enumerate(games, start=1):
        if not isinstance(game, dict):
            raise ValueError(f"game {index} must contain an object")
        # end if
        name = game.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"game {index} requires a non-empty name")
        # end if
        existing = game.get("ids")
        if existing:
            if not isinstance(existing, list):
                raise ValueError(f"game {name!r} ids must be a list")
            # end if
            for value in existing:
                if not isinstance(value, str):
                    raise ValueError(f"game {name!r} contains a non-string ID")
                # end if
                QualifiedGameId.parse(value)
            # end for
            continue
        # end if
        ids = resolve_title(name, providers, resolver, choose)
        if not ids:
            game.pop("ids", None)
            unresolved.append(name)
            continue
        # end if
        game["ids"] = ids
    # end for
    if not unresolved:
        GameList.model_validate(completed)
    # end if
    return completed, unresolved
# end def complete_game_list
