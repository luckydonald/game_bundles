"""Steam implementation of the launcher-neutral ownership contract."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from game_collections.completion import MissingHandling, evaluate_completion
from game_collections.launchers.base import (
    CollectionEligibility,
    LauncherAdapter,
    PlannedCollectionChange,
    SyncPlan,
)
from game_collections.launchers.steam.api import SteamApiClient
from game_collections.launchers.steam.io import (
    STEAM_USER_COLLECTION_ID_PATTERN,
    SteamFileGateway,
    steam_collection_id,
)
from game_collections.launchers.steam.local_ownership import get_installed_app_ids
from game_collections.lists import LoadedGameList


# Resolves the set of owned (or approximately-owned) Steam app IDs. Kept as a
# plain callable seam so the Web API and the local-installed-games fallback
# are interchangeable without SteamAdapter knowing which one it got.
OwnedAppIdsSource = Callable[[], set[int]]
STEAM_COLLECTION_PREFIX = "🗃️ "
SteamTierMode = Literal["all", "highest"]


@dataclass(frozen=True, slots=True)
class SteamOptions:
    """Resolved Steam account inputs."""

    steam_id: str
    steam_root: Path | None = None
    api_key: str | None = None
    min_owned: int | None = None
    max_owned: int | None = None
    min_missing: int | None = None
    max_missing: int | None = 0
    min_owned_pct: float | None = None
    max_owned_pct: float | None = None
    min_missing_pct: float | None = None
    max_missing_pct: float | None = None
    unresolved_handling: MissingHandling = "ignore"
    unsupported_store_handling: MissingHandling = "ignore"
    tier_mode: SteamTierMode = "all"
    reconcile_managed: bool = False
    protected_collection_name: str | None = None
    unverified_ownership: bool = False

    def __post_init__(self) -> None:
        for bound_name in ("min_owned", "max_owned", "min_missing", "max_missing"):
            bound = getattr(self, bound_name)
            if bound is not None and bound < 0:
                raise ValueError(f"invalid Steam {bound_name!r} bound: {bound!r}")
            # end if
        # end for
        for pct_bound_name in ("min_owned_pct", "max_owned_pct", "min_missing_pct", "max_missing_pct"):
            pct_bound = getattr(self, pct_bound_name)
            if pct_bound is not None and not (0 <= pct_bound <= 100):
                raise ValueError(f"invalid Steam {pct_bound_name!r} bound: {pct_bound!r}")
            # end if
        # end for
        for handling_name in ("unresolved_handling", "unsupported_store_handling"):
            handling = getattr(self, handling_name)
            if handling not in ("hide", "ignore", "enforce"):
                raise ValueError(f"invalid Steam {handling_name!r}: {handling!r}")
            # end if
        # end for
        if self.tier_mode not in ("all", "highest"):
            raise ValueError(f"invalid Steam tier mode: {self.tier_mode!r}")
        # end if
    # end def __post_init__

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


def owned_app_ids_from_collection(gateway: SteamFileGateway, collection_name: str) -> OwnedAppIdsSource:
    """Wrap a manually curated local Steam collection as an :data:`OwnedAppIdsSource`."""
    def source() -> set[int]:
        return set(gateway.read_collection(collection_name).added)
    # end def source
    return source
# end def owned_app_ids_from_collection


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
            if self.options.unverified_ownership:
                # `--source none` deliberately writes every known Steam ID from the selected
                # list. This is not an ownership result, so it bypasses every ownership-based
                # bound and non-Steam handling setting.
                completion = evaluate_completion(game_list.data.games, set())
                results.append(
                    CollectionEligibility(
                        list_id=game_list.id,
                        name=game_list.data.name,
                        tier=game_list.data.tier,
                        eligible=True,
                        owned_ids=completion.missing_ids,
                        missing_ids=[],
                        unsupported_ids=[],
                    )
                )
                continue
            # end if
            completion = evaluate_completion(
                game_list.data.games,
                owned_app_ids,
                unresolved_handling=self.options.unresolved_handling,
                unsupported_store_handling=self.options.unsupported_store_handling,
            )
            pick_quota = game_list.data.pick_quota
            if completion.hidden_count:
                eligible = False
            elif pick_quota is not None:
                eligible = completion.owned_count >= pick_quota
            else:
                # `None` when `completion.total == 0` (nothing to divide) - percentage bounds
                # are then vacuously satisfied below, same as an absolute bound would be with
                # a count of 0.
                owned_pct = (completion.owned_count / completion.total * 100) if completion.total else None
                missing_pct = (completion.missing_count / completion.total * 100) if completion.total else None
                eligible = (
                    (self.options.min_owned is None or completion.owned_count >= self.options.min_owned)
                    and (self.options.max_owned is None or completion.owned_count <= self.options.max_owned)
                    and (self.options.min_missing is None or completion.missing_count >= self.options.min_missing)
                    and (self.options.max_missing is None or completion.missing_count <= self.options.max_missing)
                    and (self.options.min_owned_pct is None or owned_pct is None or owned_pct >= self.options.min_owned_pct)
                    and (self.options.max_owned_pct is None or owned_pct is None or owned_pct <= self.options.max_owned_pct)
                    and (self.options.min_missing_pct is None or missing_pct is None or missing_pct >= self.options.min_missing_pct)
                    and (self.options.max_missing_pct is None or missing_pct is None or missing_pct <= self.options.max_missing_pct)
                )
            # end if
            results.append(
                CollectionEligibility(
                    list_id=game_list.id,
                    name=game_list.data.name,
                    tier=game_list.data.tier,
                    eligible=eligible,
                    owned_ids=completion.owned_ids,
                    missing_ids=completion.missing_ids,
                    unsupported_ids=completion.unsupported_ids,
                )
            )
        # end for
        return results
    # end def evaluate

    def plan(self, game_lists: list[LoadedGameList]) -> SyncPlan:
        eligibility = self.evaluate(game_lists)
        selected_ids = self._selected_list_ids(eligibility)
        changes = [
            PlannedCollectionChange(
                list_id=result.list_id,
                target_id=steam_collection_id(result.list_id),
                name=f"{STEAM_COLLECTION_PREFIX}{result.name}",
                action="create-or-update",
                added_ids=result.owned_ids,
            )
            for result in eligibility
            if result.list_id in selected_ids
        ]
        if self.options.reconcile_managed:
            changes.extend(self._managed_deletions(game_lists, changes))
        # end if
        return SyncPlan(
            launcher=self.name,
            account=self.options.steam_id,
            eligibility=eligibility,
            changes=changes,
        )
    # end def plan

    def _selected_list_ids(self, eligibility: list[CollectionEligibility]) -> set[str]:
        eligible_ids = {result.list_id for result in eligibility if result.eligible}
        if self.options.tier_mode == "all":
            return eligible_ids
        # end if

        tiers: dict[tuple[str, int], str] = {}
        selected: set[str] = set()
        highest: dict[str, tuple[int, str]] = {}
        for result in eligibility:
            if result.tier is None:
                if result.eligible:
                    selected.add(result.list_id)
                # end if
                continue
            # end if
            parent = result.list_id.rpartition("/")[0]
            rank = result.tier
            key = (parent, rank)
            previous = tiers.get(key)
            if previous is not None:
                raise ValueError(f"ambiguous tier rank {rank} in {parent!r}: {previous!r} and {result.list_id!r}")
            # end if
            tiers[key] = result.list_id
            if not result.eligible:
                continue
            # end if
            current = highest.get(parent)
            if current is None or rank > current[0]:
                highest[parent] = (rank, result.list_id)
            # end if
        # end for
        selected.update(list_id for _rank, list_id in highest.values())
        return selected
    # end def _selected_list_ids

    def _managed_deletions(
        self,
        game_lists: list[LoadedGameList],
        selected_changes: list[PlannedCollectionChange],
    ) -> list[PlannedCollectionChange]:
        if self.gateway is None:
            raise ValueError("managed Steam collection reconciliation requires a file gateway")
        # end if
        selected_ids = {change.target_id for change in selected_changes}
        current_by_target: dict[str, LoadedGameList] = {}
        for game_list in game_lists:
            target_id = steam_collection_id(game_list.id)
            previous = current_by_target.get(target_id)
            if previous is not None:
                raise ValueError(f"Steam collection ID collision: {previous.id!r} and {game_list.id!r}")
            # end if
            current_by_target[target_id] = game_list
        # end for

        deletions: list[PlannedCollectionChange] = []
        protected_name = self.options.protected_collection_name
        for payload in self.gateway.read_collections():
            if protected_name is not None and payload.name.casefold() == protected_name.casefold():
                continue
            # end if
            game_list = current_by_target.get(payload.id)
            source_name = game_list.data.name if game_list is not None else None
            expected_name = f"{STEAM_COLLECTION_PREFIX}{source_name}" if source_name is not None else None
            legacy_managed = source_name is not None and payload.name == source_name
            prefixed_managed = payload.name.startswith(STEAM_COLLECTION_PREFIX)

            if payload.id in selected_ids:
                if payload.name not in (source_name, expected_name):
                    raise ValueError(
                        f"managed Steam collection ID collision for {payload.id!r}: {payload.name!r}"
                    )
                # end if
                if payload.filterSpec is not None:
                    raise ValueError(f"managed Steam collection became dynamic: {payload.name!r}")
                # end if
                continue
            # end if
            if not legacy_managed and not prefixed_managed:
                continue
            # end if
            if not STEAM_USER_COLLECTION_ID_PATTERN.fullmatch(payload.id):
                raise ValueError(f"managed Steam collection has an unsafe ID: {payload.id!r}")
            # end if
            if payload.filterSpec is not None:
                raise ValueError(f"managed Steam collection became dynamic: {payload.name!r}")
            # end if
            deletions.append(
                PlannedCollectionChange(
                    list_id=game_list.id if game_list is not None else None,
                    target_id=payload.id,
                    name=payload.name,
                    action="delete",
                )
            )
        # end for
        return sorted(deletions, key=lambda change: (change.name.casefold(), change.target_id))
    # end def _managed_deletions

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
