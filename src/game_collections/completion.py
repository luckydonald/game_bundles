"""Ownership-completion counting shared by the Steam adapter and the `apply` picker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from game_collections.models import Game


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


def evaluate_completion(
    games: list[Game],
    owned_app_ids: set[int],
    *,
    unresolved_handling: MissingHandling = "ignore",
    unsupported_store_handling: MissingHandling = "ignore",
) -> GameListCompletion:
    """Count owned/missing games, applying `unresolved_handling`/`unsupported_store_handling`."""
    required: list[int] = []
    unsupported_ids: list[str] = []
    enforced_ids: list[str] = []
    hidden_count = 0
    steam_game_count = 0
    owned_game_count = 0
    for game in games:
        steam_ids = [identifier for identifier in game.qualified_ids if identifier.provider == "steam"]
        if steam_ids:
            steam_game_count += 1
            game_app_ids: list[int] = []
            for identifier in steam_ids:
                try:
                    app_id = int(identifier.value)
                except ValueError as error:
                    raise ValueError(f"invalid Steam app ID {identifier.value!r} in {game.name!r}") from error
                # end try
                if app_id <= 0:
                    raise ValueError(f"invalid Steam app ID {app_id} in {game.name!r}")
                # end if
                game_app_ids.append(app_id)
            # end for
            required.extend(game_app_ids)
            if any(app_id in owned_app_ids for app_id in game_app_ids):
                owned_game_count += 1
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

    missing = sorted(set(required) - owned_app_ids)
    owned = sorted(set(required) & owned_app_ids)
    missing_ids = [f"steam:{app_id}" for app_id in missing] + enforced_ids
    owned_ids = [f"steam:{app_id}" for app_id in owned]
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
