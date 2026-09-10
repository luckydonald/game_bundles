from __future__ import annotations

from pathlib import Path

from game_collections.launchers.steam.adapter import SteamAdapter, SteamOptions
from game_collections.lists import discover_game_lists, expand_list_tiers, load_game_list
from game_collections.migrations.bundle_variations import (
    apply_migration_step,
    plan_migration,
    step_would_change,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
# end def _write


def _apply_all(lists_root: Path, repository_root: Path) -> None:
    for step in plan_migration(lists_root):
        if step_would_change(step):
            apply_migration_step(step, lists_root, repository_root)
        # end if
    # end for
# end def _apply_all


def test_single_file_directory_is_flattened(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write(
        lists_root / "testprovider/bundle/single-offer/bundle.yml",
        "schema: 1\nname: Single Offer\ngames:\n  - name: One\n    ids: [steam:1]\n",
    )

    _apply_all(lists_root, tmp_path)

    new_path = lists_root / "testprovider/bundle/single-offer.yml"
    assert new_path.exists()
    assert not (lists_root / "testprovider/bundle/single-offer").exists()
    loaded = load_game_list(new_path, lists_root)
    assert loaded.data.tiers == []
    assert loaded.data.games[0].tiers == []
# end def test_single_file_directory_is_flattened


def test_cumulative_tiers_are_merged_with_full_tier_membership(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-1.yml",
        "schema: 1\nname: Multi Offer — Bronze\ntier: 1\n"
        "games:\n  - name: One\n    ids: [steam:1]\n",
    )
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-2.yml",
        "schema: 1\nname: Multi Offer — Gold\ntier: 2\n"
        "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
    )

    _apply_all(lists_root, tmp_path)

    new_path = lists_root / "testprovider/bundle/multi-offer.yml"
    assert new_path.exists()
    assert not (lists_root / "testprovider/bundle/multi-offer").exists()
    loaded = load_game_list(new_path, lists_root)
    assert loaded.data.name == "Multi Offer"
    assert [(tier.rank, tier.name) for tier in loaded.data.tiers] == [(1, "Bronze"), (2, "Gold")]
    games_by_name = {game.name: game for game in loaded.data.games}
    assert games_by_name["One"].tiers == [1, 2]
    assert games_by_name["Two"].tiers == [2]
# end def test_cumulative_tiers_are_merged_with_full_tier_membership


def test_byob_style_tiers_with_shared_pool_are_merged(tmp_path: Path) -> None:
    """Every rank shares the identical game pool, only `pick_quota` differs - not
    cumulative, so membership must come from each rank's own list, not be assumed
    contiguous."""
    lists_root = tmp_path / "lists"
    for rank, quota in ((1, 1), (2, 2)):
        _write(
            lists_root / f"testprovider/bundle/byob-offer/tier-{rank}.yml",
            f"schema: 1\nname: BYOB Offer — pick {quota}\ntier: {rank}\npick_quota: {quota}\n"
            "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
        )
    # end for

    _apply_all(lists_root, tmp_path)

    loaded = load_game_list(lists_root / "testprovider/bundle/byob-offer.yml", lists_root)
    assert [(tier.rank, tier.pick_quota) for tier in loaded.data.tiers] == [(1, 1), (2, 2)]
    assert all(game.tiers == [1, 2] for game in loaded.data.games)
# end def test_byob_style_tiers_with_shared_pool_are_merged


def test_choice_pick_option_directory_is_also_merged(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write(
        lists_root / "humblebundle/choice/2026-08/tier-1.yml",
        "schema: 1\nname: July 2026 Humble Choice — Basic\ntier: 1\npick_quota: 1\n"
        "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
    )
    _write(
        lists_root / "humblebundle/choice/2026-08/tier-2.yml",
        "schema: 1\nname: July 2026 Humble Choice — Premium\ntier: 2\npick_quota: 2\n"
        "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
    )

    _apply_all(lists_root, tmp_path)

    new_path = lists_root / "humblebundle/choice/2026-08.yml"
    assert new_path.exists()
    loaded = load_game_list(new_path, lists_root)
    assert [tier.rank for tier in loaded.data.tiers] == [1, 2]
# end def test_choice_pick_option_directory_is_also_merged


def test_migration_is_idempotent(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write(
        lists_root / "testprovider/bundle/single-offer/bundle.yml",
        "schema: 1\nname: Single Offer\ngames:\n  - name: One\n    ids: [steam:1]\n",
    )
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-1.yml",
        "schema: 1\nname: Multi Offer — Bronze\ntier: 1\ngames:\n  - name: One\n    ids: [steam:1]\n",
    )
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-2.yml",
        "schema: 1\nname: Multi Offer — Gold\ntier: 2\n"
        "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
    )

    _apply_all(lists_root, tmp_path)
    first_snapshot = {path: path.read_bytes() for path in sorted(lists_root.rglob("*.yml"))}

    _apply_all(lists_root, tmp_path)
    second_snapshot = {path: path.read_bytes() for path in sorted(lists_root.rglob("*.yml"))}

    assert first_snapshot == second_snapshot
# end def test_migration_is_idempotent


def test_migration_makes_highest_tier_selection_work_again(tmp_path: Path) -> None:
    """The merged file plus `expand_list_tiers` is what lets `--tiers highest`
    correctly drop the lower tier, mirroring the pre-merge per-file behavior."""
    lists_root = tmp_path / "lists"
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-1.yml",
        "schema: 1\nname: Multi Offer — Bronze\ntier: 1\ngames:\n  - name: One\n    ids: [steam:1]\n",
    )
    _write(
        lists_root / "testprovider/bundle/multi-offer/tier-2.yml",
        "schema: 1\nname: Multi Offer — Gold\ntier: 2\n"
        "games:\n  - name: One\n    ids: [steam:1]\n  - name: Two\n    ids: [steam:2]\n",
    )

    def selected_ids() -> set[str]:
        adapter = SteamAdapter(
            SteamOptions(steam_id="76561198044975919", tier_mode="highest"),
            owned_app_ids_source=lambda: {1, 2},  # type: ignore[arg-type]
        )
        game_lists = [
            expanded for game_list in discover_game_lists(lists_root) for expanded in expand_list_tiers(game_list)
        ]
        plan = adapter.plan(game_lists)
        return {change.list_id for change in plan.changes}
    # end def selected_ids

    _apply_all(lists_root, tmp_path)

    assert selected_ids() == {"testprovider/bundle/multi-offer#tier-2"}
# end def test_migration_makes_highest_tier_selection_work_again
