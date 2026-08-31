"""Ownership-completion counting shared by the Steam adapter and the `apply` picker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from game_collections.models import Game, QualifiedGameId


MissingHandling = Literal["hide", "ignore", "enforce"]


@dataclass(frozen=True, slots=True)
class GameListCompletion:
    """Owned/missing counts for one game list, with non-steam handling already applied."""

    total: int
    owned_count: int
    missing_count: int
    owned_ids: list[str]
    missing_ids: list[str]
    unsupported_ids: list[str]
    hidden_count: int

# end class GameListCompletion


def _steam_app_ids(identifiers: tuple[QualifiedGameId, ...], label: str) -> list[int]:
    """Parse a game's Steam-qualified identities into positive AppIDs, skipping bundle IDs."""
    app_ids: list[int] = []
    for identifier in identifiers:
        if identifier.provider != "steam":
            continue
        # end if
        if identifier.value.startswith("bundle/"):
            # A Steam bundle (e.g. a "Deluxe Edition" only sold as a bundle
            # of the base app + DLC, see `parse_store_identity`) has no
            # single AppID the Web API's owned-games list can match
            # against, so it can't drive ownership on its own.
            continue
        # end if
        try:
            app_id = int(identifier.value)
        except ValueError as error:
            raise ValueError(f"invalid Steam app ID {identifier.value!r} in {label!r}") from error
        # end try
        if app_id <= 0:
            raise ValueError(f"invalid Steam app ID {app_id} in {label!r}")
        # end if
        app_ids.append(app_id)
    # end for
    return app_ids
# end def _steam_app_ids


def evaluate_completion(
    games: list[Game],
    owned_app_ids: set[int],
    *,
    unresolved_handling: MissingHandling = "ignore",
    unsupported_store_handling: MissingHandling = "ignore",
) -> GameListCompletion:
    """Count owned/missing games, applying `unresolved_handling`/`unsupported_store_handling`.

    Every ownership source that goes through Steam's `GetOwnedGames` Web API
    (or a human-curated `collection`) never returns a DLC's own AppID - see
    the Stage 0 investigation in the "bundle-in-bundle DLC packs" plan - so a
    `Game` with a non-empty `requires` also counts as owned when its base
    game's AppID is owned, not only its own AppID. Applied uniformly here
    (rather than per-source) since it's harmless for sources - like
    `installed` - that can see DLC AppIDs directly too.
    """
    unsupported_ids: list[str] = []
    enforced_ids: list[str] = []
    owned_app_id_set: set[int] = set()
    missing_app_id_set: set[int] = set()
    hidden_count = 0
    steam_game_count = 0
    owned_game_count = 0
    for game in games:
        game_app_ids = _steam_app_ids(game.qualified_ids, game.name)
        if game_app_ids:
            steam_game_count += 1
            require_app_ids = _steam_app_ids(game.qualified_ids_required, game.name) if game.requires else []
            game_owned_ids = {app_id for app_id in game_app_ids if app_id in owned_app_ids}
            is_owned = bool(game_owned_ids) or any(app_id in owned_app_ids for app_id in require_app_ids)
            if is_owned:
                owned_game_count += 1
                # A DLC owned only via `requires` (its own AppID never returned
                # by `GetOwnedGames`) still displays as owned by its own ID.
                owned_app_id_set.update(game_owned_ids or set(game_app_ids))
            else:
                missing_app_id_set.update(game_app_ids)
            # end if
            continue
        # end if

        is_unresolved = all(identifier.provider == "unresolved" for identifier in game.qualified_ids)
        handling = unresolved_handling if is_unresolved else unsupported_store_handling
        if handling == "hide":
            hidden_count += 1
            continue
        elif handling == "ignore":
            unsupported_ids.append(game.name)
        else:
            enforced_ids.append(game.qualified_ids[0].compact())
        # end if
    # end for

    missing_ids = [f"steam:{app_id}" for app_id in sorted(missing_app_id_set)] + enforced_ids
    owned_ids = [f"steam:{app_id}" for app_id in sorted(owned_app_id_set)]
    return GameListCompletion(
        total=steam_game_count + len(enforced_ids),
        owned_count=owned_game_count,
        missing_count=(steam_game_count - owned_game_count) + len(enforced_ids),
        owned_ids=owned_ids,
        missing_ids=missing_ids,
        unsupported_ids=unsupported_ids,
        hidden_count=hidden_count,
    )
# end def evaluate_completion
