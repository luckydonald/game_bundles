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
CompletionMode = Literal["blank", "missing", "unresolved", "refetch_all"]
SearchChooser = Callable[[str, StoreName, list[StoreCandidate]], str | None]
COMPLETION_MODES: tuple[CompletionMode, ...] = (
    "blank",
    "missing",
    "unresolved",
    "refetch_all",
)


def selected_providers(values: str | list[str] | None, *, default: str) -> tuple[StoreName, ...]:
    """Validate repeated/comma-separated providers and expand ``all``."""
    selections = [values] if isinstance(values, str) else (values or [default])
    requested = [part.strip() for value in selections for part in value.split(",")]
    if any(not value for value in requested):
        raise ValueError("provider names must not be empty")
    # end if
    if "all" in requested:
        return ALLOWED_STORES
    # end if
    invalid = [value for value in requested if value not in ALLOWED_STORES]
    if invalid:
        choices = ", ".join(("all", *ALLOWED_STORES))
        raise ValueError(f"unknown provider {invalid[0]!r}; choose one of: {choices}")
    # end if
    return tuple(dict.fromkeys(cast(list[StoreName], requested)))
# end def selected_providers


def completion_mode(value: str) -> CompletionMode:
    """Validate one completion mode for a concise CLI error."""
    if value not in COMPLETION_MODES:
        choices = ", ".join(COMPLETION_MODES)
        raise ValueError(f"unknown completion mode {value!r}; choose one of: {choices}")
    # end if
    return cast(CompletionMode, value)
# end def completion_mode


def _store_unresolved_prefix(provider: StoreName) -> str:
    return f"unresolved:store:{provider}:"
# end def _store_unresolved_prefix


def _is_proper_id(value: str) -> bool:
    return not value.startswith("unresolved:")
# end def _is_proper_id


def _should_search(ids: list[str], provider: StoreName, mode: CompletionMode) -> bool:
    if mode == "blank":
        return not any(_is_proper_id(value) for value in ids)
    # end if
    if mode == "refetch_all":
        return True
    # end if
    has_provider = any(value.startswith(f"{provider}:") for value in ids)
    has_failed = any(value.startswith(_store_unresolved_prefix(provider)) for value in ids)
    if mode == "missing":
        return not has_provider and not has_failed
    # end if
    return not has_provider
# end def _should_search


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
    mode: CompletionMode = "blank",
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
        existing = game.get("ids", [])
        if not isinstance(existing, list):
            raise ValueError(f"game {name!r} ids must be a list")
        # end if
        if any(not isinstance(value, str) for value in existing):
            raise ValueError(f"game {name!r} contains a non-string ID")
        # end if
        current = [QualifiedGameId.parse(value).compact() for value in existing]
        searched = False
        failed = False
        resolved_any = False
        blank_eligible = not any(_is_proper_id(value) for value in current)
        for provider in providers:
            should_search = blank_eligible if mode == "blank" else _should_search(
                current, provider, mode
            )
            if not should_search:
                continue
            # end if
            searched = True
            prefix = _store_unresolved_prefix(provider)
            current = [value for value in current if not value.startswith(prefix)]
            if mode == "refetch_all":
                current = [value for value in current if not value.startswith(f"{provider}:")]
            # end if
            found = resolve_title(name, (provider,), resolver, choose)
            if found:
                current.extend(found)
                resolved_any = True
                continue
            # end if
            marker_name = "-".join(name.casefold().split())
            current.append(f"{prefix}{marker_name}")
            failed = True
        # end for
        if resolved_any:
            current = [value for value in current if not value.startswith("unresolved:source:")]
        # end if
        game["ids"] = list(dict.fromkeys(current))
        if searched and failed:
            unresolved.append(name)
        # end if
    # end for
    GameList.model_validate(completed)
    return completed, unresolved
# end def complete_game_list
