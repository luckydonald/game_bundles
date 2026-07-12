"""Steam implementation of the launcher-neutral ownership contract."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

from game_collections.launchers.base import (
    CollectionEligibility,
    LauncherAdapter,
    PlannedCollectionChange,
    SyncPlan,
)
from game_collections.launchers.steam.api import SteamApiClient
from game_collections.launchers.steam.io import SteamFileGateway
from game_collections.launchers.steam.local_ownership import get_installed_app_ids
from game_collections.lists import LoadedGameList


# Resolves the set of owned (or approximately-owned) Steam app IDs. Kept as a
# plain callable seam so the Web API and the local-installed-games fallback
# are interchangeable without SteamAdapter knowing which one it got.
OwnedAppIdsSource = Callable[[], set[int]]


@dataclass(frozen=True, slots=True)
class SteamOptions:
    """Resolved Steam account inputs."""

    steam_id: str
    steam_root: Path | None = None
    api_key: str | None = None

# end class SteamOptions


def owned_app_ids_from_api(api_client: SteamApiClient, steam_id: str) -> OwnedAppIdsSource:
    """Wrap the Web API client as an :data:`OwnedAppIdsSource`."""
    def source() -> set[int]:
        owned_response = api_client.get_owned_games(steam_id)
        return {game.appid for game in owned_response.response.games}
    # end def source
    return source
# end def owned_app_ids_from_api


def owned_app_ids_from_installed(steam_root: Path) -> OwnedAppIdsSource:
    """Wrap the local installed-games scan as an :data:`OwnedAppIdsSource`."""
    def source() -> set[int]:
        return get_installed_app_ids(steam_root)
    # end def source
    return source
# end def owned_app_ids_from_installed


class SteamAdapter(LauncherAdapter):
    """Steam ownership and collection synchronization adapter."""

    name = "steam"

    def __init__(
        self,
        options: SteamOptions,
        owned_app_ids_source: OwnedAppIdsSource | None = None,
        gateway: SteamFileGateway | None = None,
    ) -> None:
        self.options = options
        if owned_app_ids_source is not None:
            self.owned_app_ids_source = owned_app_ids_source
        else:
            if not options.api_key:
                raise ValueError("Steam adapter requires either an owned_app_ids_source or an api_key")
            # end if
            self.owned_app_ids_source = owned_app_ids_from_api(SteamApiClient(options.api_key), options.steam_id)
        # end if
        self.gateway = gateway
    # end def __init__

    def evaluate(self, game_lists: list[LoadedGameList]) -> list[CollectionEligibility]:
        owned_app_ids = self.owned_app_ids_source()
        results: list[CollectionEligibility] = []
        for game_list in game_lists:
            required: list[int] = []
            unsupported: list[str] = []
            for game in game_list.data.games:
                steam_ids = [identifier for identifier in game.qualified_ids if identifier.provider == "steam"]
                if not steam_ids:
                    unsupported.append(game.name)
                    continue
                # end if
                for identifier in steam_ids:
                    try:
                        app_id = int(identifier.value)
                    except ValueError as error:
                        raise ValueError(f"invalid Steam app ID {identifier.value!r} in {game_list.id}") from error
                    # end try
                    if app_id <= 0:
                        raise ValueError(f"invalid Steam app ID {app_id} in {game_list.id}")
                    # end if
                    required.append(app_id)
                # end for
            # end for
            missing = sorted(set(required) - owned_app_ids)
            owned = sorted(set(required) & owned_app_ids)
            results.append(
                CollectionEligibility(
                    list_id=game_list.id,
                    name=game_list.data.name,
                    eligible=not missing and not unsupported and bool(required),
                    owned_ids=[f"steam:{app_id}" for app_id in owned],
                    missing_ids=[f"steam:{app_id}" for app_id in missing],
                    unsupported_ids=unsupported,
                )
            )
        # end for
        return results
    # end def evaluate

    def plan(self, game_lists: list[LoadedGameList]) -> SyncPlan:
        eligibility = self.evaluate(game_lists)
        changes = [
            PlannedCollectionChange(
                list_id=result.list_id,
                name=result.name,
                action="create-or-update",
                added_ids=result.owned_ids,
            )
            for result in eligibility
            if result.eligible
        ]
        return SyncPlan(
            launcher=self.name,
            account=self.options.steam_id,
            eligibility=eligibility,
            changes=changes,
        )
    # end def plan

    def stage(self, plan: SyncPlan, output_dir: Path) -> Path:
        if self.gateway is None:
            raise ValueError("Steam staging requires a locked file gateway")
        # end if
        return self.gateway.stage(plan, output_dir)
    # end def stage

    def apply(self, staged_dir: Path, confirm: Callable[[str], str]) -> None:
        if self.gateway is None:
            raise ValueError("Steam apply requires a locked file gateway")
        # end if
        self.gateway.apply(staged_dir, confirm)
    # end def apply

# end class SteamAdapter
