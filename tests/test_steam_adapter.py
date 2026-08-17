from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_collections.launchers.base import PlannedCollectionChange, SyncPlan
from game_collections.launchers.steam.adapter import (
    SteamAdapter,
    SteamOptions,
    owned_app_ids_from_collection,
)
from game_collections.launchers.steam.io import NAMESPACE_NAME, SteamFileGateway, steam_collection_id
from game_collections.lists import LoadedGameList, load_game_list
from game_collections.models import GameList
from test_steam_io import ACCOUNT_ID, STEAM_ID, build_fake_steam


REPO_ROOT = Path(__file__).parents[1]


def _orange_box() -> list[LoadedGameList]:
    return [
        load_game_list(
            REPO_ROOT / "lists/valve/the-orange-box.yml",
            REPO_ROOT / "lists",
        )
    ]
# end def _orange_box


def _fake_source(owned: list[int]) -> object:
    return lambda: set(owned)
# end def _fake_source


def _list(
    list_id: str,
    steam_ids: list[int],
    *,
    unsupported: bool = False,
    tier: int | None = None,
    pick_quota: int | None = None,
) -> LoadedGameList:
    games = [
        {"name": f"Game {app_id}", "ids": [f"steam:{app_id}"]}
        for app_id in steam_ids
    ]
    if unsupported:
        games.append({"name": "Other Store Game", "ids": ["gog:other"]})
    # end if
    payload: dict[str, object] = {"schema": 1, "name": list_id, "games": games}
    if tier is not None:
        payload["tier"] = tier
    # end if
    if pick_quota is not None:
        payload["pick_quota"] = pick_quota
    # end if
    data = GameList.model_validate(payload)
    return LoadedGameList(id=list_id, path=Path(f"lists/{list_id}.yml"), data=data)
# end def _list


def test_orange_box_requires_every_game() -> None:
    game_lists = _orange_box()
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919"),
        owned_app_ids_source=_fake_source([220, 380, 420, 400]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate(game_lists)[0]

    assert result.eligible is False
    assert result.missing_ids == ["steam:440"]
# end def test_orange_box_requires_every_game


def test_orange_box_is_eligible_when_complete() -> None:
    game_lists = _orange_box()
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919"),
        owned_app_ids_source=_fake_source([220, 380, 420, 400, 440]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate(game_lists)[0]

    assert result.eligible is True
    assert result.missing_ids == []
# end def test_orange_box_is_eligible_when_complete


def test_max_missing_zero_ignores_games_without_steam_ids() -> None:
    game_list = _list("example/mixed", [10, 20], unsupported=True)
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", max_missing=0),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is True
    assert result.unsupported_ids == ["Other Store Game"]
# end def test_max_missing_zero_ignores_games_without_steam_ids


def test_unverified_ownership_adds_every_listed_steam_id_without_gating() -> None:
    game_list = _list("example/unverified", [10, 20], unsupported=True)
    adapter = SteamAdapter(
        SteamOptions(
            steam_id="76561198044975919",
            max_missing=0,
            unsupported_store_handling="hide",
            unverified_ownership=True,
        ),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
    )

    plan = adapter.plan([game_list])

    assert plan.eligibility[0].eligible is True
    assert plan.eligibility[0].missing_ids == []
    assert plan.changes[0].added_ids == ["steam:10", "steam:20"]
# end def test_unverified_ownership_adds_every_listed_steam_id_without_gating


def test_hide_makes_a_bundle_with_an_unsupported_store_game_ineligible() -> None:
    game_list = _list("example/mixed", [10, 20], unsupported=True)
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", max_missing=None, unsupported_store_handling="hide"),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is False
    assert result.unsupported_ids == []
# end def test_hide_makes_a_bundle_with_an_unsupported_store_game_ineligible


def test_min_owned_one_selects_partial_ownership_and_exports_only_owned_ids() -> None:
    game_list = _list("example/partial", [10, 20, 30])
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", min_owned=1, max_missing=None),
        owned_app_ids_source=_fake_source([20]),  # type: ignore[arg-type]
    )

    plan = adapter.plan([game_list])

    assert plan.eligibility[0].eligible is True
    assert plan.eligibility[0].missing_ids == ["steam:10", "steam:30"]
    assert plan.changes[0].added_ids == ["steam:20"]
# end def test_min_owned_one_selects_partial_ownership_and_exports_only_owned_ids


def test_min_owned_one_requires_at_least_one_owned_steam_id() -> None:
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", min_owned=1, max_missing=None),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([_list("example/none", [10])])[0]

    assert result.eligible is False
# end def test_min_owned_one_requires_at_least_one_owned_steam_id


def test_no_bounds_is_eligible_even_with_zero_owned_games() -> None:
    game_list = _list("example/none-owned", [10, 20])
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", max_missing=None),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is True
    assert result.missing_ids == ["steam:10", "steam:20"]
# end def test_no_bounds_is_eligible_even_with_zero_owned_games


def test_pick_quota_still_applies_with_no_missing_bounds_set() -> None:
    # `pick_quota`, when set, always takes priority over the min/max bounds - there's no
    # "no bounds" special case that overrides an unmet quota.
    game_list = _list("example/byob", [10, 20, 30], pick_quota=2)
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", max_missing=None),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is False
# end def test_pick_quota_still_applies_with_no_missing_bounds_set


def test_pick_quota_met_is_eligible_regardless_of_missing_bounds() -> None:
    game_list = _list("example/byob", [10, 20, 30], pick_quota=2)
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", max_missing=0),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is True
# end def test_pick_quota_met_is_eligible_regardless_of_missing_bounds


def test_pick_quota_not_met_is_ineligible_even_with_min_owned_one() -> None:
    game_list = _list("example/byob", [10, 20, 30], pick_quota=2)
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", min_owned=1, max_missing=None),
        owned_app_ids_source=_fake_source([10]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate([game_list])[0]

    assert result.eligible is False
# end def test_pick_quota_not_met_is_ineligible_even_with_min_owned_one


def test_pick_quota_combines_with_highest_tier_selection() -> None:
    game_lists = [
        _list("example/byob/tier-1", [10, 20, 30], tier=1, pick_quota=1),
        _list("example/byob/tier-2", [10, 20, 30], tier=2, pick_quota=2),
    ]
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", tier_mode="highest"),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    plan = adapter.plan(game_lists)

    assert [change.list_id for change in plan.changes] == ["example/byob/tier-2"]
# end def test_pick_quota_combines_with_highest_tier_selection


def test_highest_tier_uses_the_tier_field_across_sibling_bundle_directories() -> None:
    game_lists = [
        _list("provider/bundle/ordinal/tier-1", [10], tier=1),
        _list("provider/bundle/ordinal/tier-3", [10, 20], tier=3),
        _list("humblebundle/bundle/items/tier-1", [10], tier=1),
        _list("humblebundle/bundle/items/tier-2", [10, 20], tier=2),
        _list("provider/choice/standalone", [10]),
    ]
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", tier_mode="highest"),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    plan = adapter.plan(game_lists)

    assert [change.list_id for change in plan.changes] == [
        "provider/bundle/ordinal/tier-3",
        "humblebundle/bundle/items/tier-2",
        "provider/choice/standalone",
    ]
# end def test_highest_tier_uses_the_tier_field_across_sibling_bundle_directories


def test_all_tiers_keeps_every_matching_tier() -> None:
    game_lists = [
        _list("provider/bundle/example/tier-1", [10], tier=1),
        _list("provider/bundle/example/tier-2", [10, 20], tier=2),
    ]
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", tier_mode="all"),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
    )

    plan = adapter.plan(game_lists)

    assert [change.list_id for change in plan.changes] == [
        "provider/bundle/example/tier-1",
        "provider/bundle/example/tier-2",
    ]
# end def test_all_tiers_keeps_every_matching_tier


def test_highest_tier_rejects_ambiguous_numeric_rank() -> None:
    game_lists = [
        _list("provider/bundle/example/tier-3", [10], tier=3),
        _list("provider/bundle/example/other-3", [10], tier=3),
    ]
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", tier_mode="highest"),
        owned_app_ids_source=_fake_source([10]),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="ambiguous tier rank"):
        adapter.plan(game_lists)
    # end with
# end def test_highest_tier_rejects_ambiguous_numeric_rank


def test_plan_prefixes_exported_collection_name() -> None:
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919"),
        owned_app_ids_source=_fake_source([220, 380, 420, 400, 440]),  # type: ignore[arg-type]
    )

    plan = adapter.plan(_orange_box())

    assert plan.changes[0].name == "🗃️ The Orange Box"
# end def test_plan_prefixes_exported_collection_name


def test_owned_app_ids_from_collection_reads_local_collection(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    source = owned_app_ids_from_collection(gateway, "Favorites")

    assert source() == {440}
# end def test_owned_app_ids_from_collection_reads_local_collection


def test_reconciliation_deletes_managed_collection_that_no_longer_matches(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    creator = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID),
        owned_app_ids_source=_fake_source([220, 380, 420, 400, 440]),  # type: ignore[arg-type]
        gateway=gateway,
    )
    staged = gateway.stage(creator.plan(_orange_box()), tmp_path / "Desktop")
    gateway.apply(staged, lambda _prompt: "REPLACE")
    reconciler = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, reconcile_managed=True),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    plan = reconciler.plan(_orange_box())

    assert [(change.action, change.list_id) for change in plan.changes] == [
        ("delete", "valve/the-orange-box")
    ]
# end def test_reconciliation_deletes_managed_collection_that_no_longer_matches


def test_reconciliation_deletes_superseded_lower_tier(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    game_lists = [
        _list("provider/bundle/example/tier-1", [10], tier=1),
        _list("provider/bundle/example/tier-2", [10, 20], tier=2),
    ]
    creator = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, tier_mode="all"),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
        gateway=gateway,
    )
    staged = gateway.stage(creator.plan(game_lists), tmp_path / "Desktop")
    gateway.apply(staged, lambda _prompt: "REPLACE")
    reconciler = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, tier_mode="highest", reconcile_managed=True),
        owned_app_ids_source=_fake_source([10, 20]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    plan = reconciler.plan(game_lists)

    assert [(change.action, change.list_id) for change in plan.changes] == [
        ("create-or-update", "provider/bundle/example/tier-2"),
        ("delete", "provider/bundle/example/tier-1"),
    ]
# end def test_reconciliation_deletes_superseded_lower_tier


def test_reconciliation_recognizes_legacy_unprefixed_collection(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    legacy_plan = SyncPlan(
        launcher="steam",
        account=STEAM_ID,
        eligibility=[],
        changes=[
            PlannedCollectionChange(
                list_id="valve/the-orange-box",
                target_id=steam_collection_id("valve/the-orange-box"),
                name="The Orange Box",
                action="create-or-update",
                added_ids=["steam:440"],
            )
        ],
    )
    staged = gateway.stage(legacy_plan, tmp_path / "Desktop")
    gateway.apply(staged, lambda _prompt: "REPLACE")
    reconciler = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, reconcile_managed=True),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    plan = reconciler.plan(_orange_box())

    assert len(plan.changes) == 1
    assert plan.changes[0].action == "delete"
    assert plan.changes[0].name == "The Orange Box"
# end def test_reconciliation_recognizes_legacy_unprefixed_collection


def test_reconciliation_deletes_prefixed_orphan_collection(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    removed_list = _list("removed/bundle/tier-1", [10])
    creator = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID),
        owned_app_ids_source=_fake_source([10]),  # type: ignore[arg-type]
        gateway=gateway,
    )
    staged = gateway.stage(creator.plan([removed_list]), tmp_path / "Desktop")
    gateway.apply(staged, lambda _prompt: "REPLACE")
    reconciler = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, reconcile_managed=True),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    plan = reconciler.plan([])

    assert len(plan.changes) == 1
    assert plan.changes[0].action == "delete"
    assert plan.changes[0].list_id is None
    assert plan.changes[0].name == "🗃️ removed/bundle/tier-1"
# end def test_reconciliation_deletes_prefixed_orphan_collection


def test_reconciliation_protects_collection_used_as_ownership_source(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    creator = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID),
        owned_app_ids_source=_fake_source([220, 380, 420, 400, 440]),  # type: ignore[arg-type]
        gateway=gateway,
    )
    staged = gateway.stage(creator.plan(_orange_box()), tmp_path / "Desktop")
    gateway.apply(staged, lambda _prompt: "REPLACE")
    reconciler = SteamAdapter(
        SteamOptions(
            steam_id=STEAM_ID,
            reconcile_managed=True,
            protected_collection_name="🗃️ The Orange Box",
        ),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    plan = reconciler.plan(_orange_box())

    assert plan.changes == []
# end def test_reconciliation_protects_collection_used_as_ownership_source


def test_reconciliation_rejects_prefixed_dynamic_collection(tmp_path: Path) -> None:
    steam_root = build_fake_steam(tmp_path)
    namespace_path = (
        steam_root / "userdata" / ACCOUNT_ID / "config/cloudstorage" / NAMESPACE_NAME
    )
    namespace = json.loads(namespace_path.read_text(encoding="utf-8"))
    dynamic_entry = next(entry for key, entry in namespace if key == "user-collections.uc-existing123")
    payload = json.loads(dynamic_entry["value"])
    payload["name"] = "🗃️ Dynamic"
    dynamic_entry["value"] = json.dumps(payload, separators=(",", ":"))
    namespace_path.write_text(json.dumps(namespace, separators=(",", ":")), encoding="utf-8")
    gateway = SteamFileGateway(steam_root, STEAM_ID)
    reconciler = SteamAdapter(
        SteamOptions(steam_id=STEAM_ID, reconcile_managed=True),
        owned_app_ids_source=_fake_source([]),  # type: ignore[arg-type]
        gateway=gateway,
    )

    with pytest.raises(ValueError, match="became dynamic"):
        reconciler.plan([])
    # end with
# end def test_reconciliation_rejects_prefixed_dynamic_collection


def test_adapter_requires_source_or_api_key() -> None:
    try:
        SteamAdapter(SteamOptions(steam_id="76561198044975919"))
    except ValueError as error:
        assert "owned_app_ids_source" in str(error)
    else:
        raise AssertionError("expected ValueError")
    # end try
# end def test_adapter_requires_source_or_api_key
