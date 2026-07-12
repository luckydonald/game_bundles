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
from game_collections.lists import LoadedGameList


@dataclass(frozen=True, slots=True)
class SteamOptions:
    """Resolved Steam account inputs."""

    steam_id: str
    api_key: str
    steam_root: Path | None = None

# end class SteamOptions


class SteamAdapter(LauncherAdapter):
    """Steam ownership and collection synchronization adapter."""

    name = "steam"

    def __init__(
        self,
        options: SteamOptions,
        api_client: SteamApiClient | None = None,
        gateway: SteamFileGateway | None = None,
    ) -> None:
        self.options = options
        self.api_client = api_client or SteamApiClient(options.api_key)
        self.gateway = gateway
    # end def __init__

    def evaluate(self, game_lists: list[LoadedGameList]) -> list[CollectionEligibility]:
        owned_response = self.api_client.get_owned_games(self.options.steam_id)
        owned_app_ids = {game.appid for game in owned_response.response.games}
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
