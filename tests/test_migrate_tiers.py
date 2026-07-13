from __future__ import annotations

import json
from pathlib import Path

import pytest

from game_collections.lists import discover_game_lists, load_game_list
from game_collections.launchers.steam.adapter import SteamAdapter, SteamOptions
from game_collections.migrate_tiers import (
    TierMigrationError,
    apply_migration_step,
    plan_migration,
    step_would_change,
)


def _write_list(path: Path, name: str, *, metadata_ref: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    references = ""
    if metadata_ref is not None:
        references = f"references:\n  - name: Crawl metadata\n    path: {metadata_ref}\n"
    # end if
    path.write_text(
        f"schema: 1\nname: {name}\n{references}games:\n  - name: One\n    ids: [steam:440]\n",
        encoding="utf-8",
    )
# end def _write_list


def _apply_all(lists_root: Path, repository_root: Path) -> None:
    for step in plan_migration(lists_root):
        if step_would_change(step, lists_root):
            apply_migration_step(step, lists_root, repository_root)
        # end if
    # end for
# end def _apply_all


def test_single_tier_directory_is_renamed_to_bundle_yml(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "testprovider/bundle/single-offer/tier-1.yml", "Single Offer")

    _apply_all(lists_root, tmp_path)

    new_path = lists_root / "testprovider/bundle/single-offer/bundle.yml"
    assert new_path.exists()
    assert not (lists_root / "testprovider/bundle/single-offer/tier-1.yml").exists()
    loaded = load_game_list(new_path, lists_root)
    assert loaded.data.tier is None
# end def test_single_tier_directory_is_renamed_to_bundle_yml


def test_multi_numeric_tier_directory_keeps_names_and_gets_tier_field(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-1.yml", "Multi Offer — Tier 1")
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-2.yml", "Multi Offer — Tier 2")

    _apply_all(lists_root, tmp_path)

    first = load_game_list(lists_root / "testprovider/bundle/multi-offer/tier-1.yml", lists_root)
    second = load_game_list(lists_root / "testprovider/bundle/multi-offer/tier-2.yml", lists_root)
    assert first.data.tier == 1
    assert second.data.tier == 2
# end def test_multi_numeric_tier_directory_keeps_names_and_gets_tier_field


def test_legacy_humble_item_bundle_naming_is_renumbered_by_item_count(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "humblebundle/bundle/legacy-items/2-item-bundle.yml", "Legacy — Small")
    _write_list(lists_root / "humblebundle/bundle/legacy-items/entire-5-item-bundle.yml", "Legacy — Entire")

    _apply_all(lists_root, tmp_path)

    bundle_dir = lists_root / "humblebundle/bundle/legacy-items"
    assert not (bundle_dir / "2-item-bundle.yml").exists()
    assert not (bundle_dir / "entire-5-item-bundle.yml").exists()
    small = load_game_list(bundle_dir / "tier-1.yml", lists_root)
    entire = load_game_list(bundle_dir / "tier-2.yml", lists_root)
    assert small.data.name == "Legacy — Small"
    assert small.data.tier == 1
    assert entire.data.name == "Legacy — Entire"
    assert entire.data.tier == 2
# end def test_legacy_humble_item_bundle_naming_is_renumbered_by_item_count


def test_legacy_gmg_identifier_naming_is_renumbered_via_archive_metadata(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archives_root = tmp_path / "archives"
    metadata_path = archives_root / "greenmangaming/bundle/legacy-named/metadata.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps({"tiers": [{"identifier": "bronze"}, {"identifier": "gold"}]}),
        encoding="utf-8",
    )
    _write_list(
        lists_root / "greenmangaming/bundle/legacy-named/bronze.yml",
        "Legacy — Bronze",
        metadata_ref="../../../../archives/greenmangaming/bundle/legacy-named/metadata.json",
    )
    _write_list(
        lists_root / "greenmangaming/bundle/legacy-named/gold.yml",
        "Legacy — Gold",
        metadata_ref="../../../../archives/greenmangaming/bundle/legacy-named/metadata.json",
    )

    _apply_all(lists_root, tmp_path)

    bundle_dir = lists_root / "greenmangaming/bundle/legacy-named"
    assert not (bundle_dir / "bronze.yml").exists()
    assert not (bundle_dir / "gold.yml").exists()
    bronze = load_game_list(bundle_dir / "tier-1.yml", lists_root)
    gold = load_game_list(bundle_dir / "tier-2.yml", lists_root)
    assert bronze.data.name == "Legacy — Bronze"
    assert bronze.data.tier == 1
    assert gold.data.name == "Legacy — Gold"
    assert gold.data.tier == 2
# end def test_legacy_gmg_identifier_naming_is_renumbered_via_archive_metadata


def test_legacy_gmg_identifier_naming_without_metadata_reference_raises(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "greenmangaming/bundle/unresolvable/bronze.yml", "Unresolvable — Bronze")
    _write_list(lists_root / "greenmangaming/bundle/unresolvable/gold.yml", "Unresolvable — Gold")

    with pytest.raises(TierMigrationError):
        plan_migration(lists_root)
    # end with
# end def test_legacy_gmg_identifier_naming_without_metadata_reference_raises


def test_migration_is_idempotent(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "testprovider/bundle/single-offer/tier-1.yml", "Single Offer")
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-1.yml", "Multi Offer — Tier 1")
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-2.yml", "Multi Offer — Tier 2")

    _apply_all(lists_root, tmp_path)
    first_snapshot = {path: path.read_bytes() for path in sorted(lists_root.rglob("*.yml"))}

    _apply_all(lists_root, tmp_path)
    second_snapshot = {path: path.read_bytes() for path in sorted(lists_root.rglob("*.yml"))}

    assert first_snapshot == second_snapshot
# end def test_migration_is_idempotent


def test_migration_makes_highest_tier_selection_work_again(tmp_path: Path) -> None:
    """Before migration, un-tiered legacy files are always-included (no tier field to rank
    by); migration is what lets `--tiers highest` correctly drop the lower tier again.
    """
    lists_root = tmp_path / "lists"
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-1.yml", "Multi Offer — Tier 1")
    _write_list(lists_root / "testprovider/bundle/multi-offer/tier-2.yml", "Multi Offer — Tier 2")

    def selected_ids() -> set[str]:
        adapter = SteamAdapter(
            SteamOptions(steam_id="76561198044975919", tier_mode="highest"),
            owned_app_ids_source=lambda: {440},  # type: ignore[arg-type]
        )
        game_lists = discover_game_lists(lists_root)
        plan = adapter.plan(game_lists)
        return {change.list_id for change in plan.changes}
    # end def selected_ids

    assert selected_ids() == {
        "testprovider/bundle/multi-offer/tier-1",
        "testprovider/bundle/multi-offer/tier-2",
    }

    _apply_all(lists_root, tmp_path)

    assert selected_ids() == {"testprovider/bundle/multi-offer/tier-2"}
# end def test_migration_makes_highest_tier_selection_work_again
