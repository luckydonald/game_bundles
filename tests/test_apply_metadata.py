from __future__ import annotations

from pathlib import Path

from game_collections.apply.metadata import load_bundle_metadata
from game_collections.lists import LoadedGameList
from game_collections.models import GameList


def _list(list_id: str, *, tier: int | None = None) -> LoadedGameList:
    payload: dict[str, object] = {
        "schema": 1,
        "name": list_id,
        "games": [{"name": "One", "ids": ["steam:440"]}, {"name": "Two", "ids": ["steam:441"]}],
    }
    data = GameList.model_validate(payload)
    # Mirrors what `expand_list_tiers` produces for a real multi-variation bundle:
    # tier/grouping come from this synthetic id suffix (see `lists.split_tier_suffix`).
    full_id = list_id if tier is None else f"{list_id}#tier-{tier}"
    return LoadedGameList(id=full_id, path=Path(f"lists/{list_id}.yml"), data=data)
# end def _list


def test_humble_bundle_tier_shape() -> None:
    bundles = load_bundle_metadata(
        [_list("humblebundle/bundle/2026-07-01_sample-bundle", tier=2)]
    )

    assert bundles[0].source == "humblebundle"
    assert bundles[0].bundle_kind == "bundle"
    assert bundles[0].date == "2026-07-01"
    assert bundles[0].item_count == 2
    assert bundles[0].tier == 2
# end def test_humble_bundle_tier_shape


def test_humble_choice_month_shape() -> None:
    bundles = load_bundle_metadata([_list("humblebundle/choice/2026-07")])

    assert bundles[0].source == "humblebundle"
    assert bundles[0].bundle_kind == "choice"
    assert bundles[0].date == "2026-07"
    assert bundles[0].tier is None
# end def test_humble_choice_month_shape


def test_gmg_single_tier_bundle_yml_shape() -> None:
    bundles = load_bundle_metadata([_list("greenmangaming/bundle/2026-06-02_master-builders-collection/bundle")])

    assert bundles[0].source == "greenmangaming"
    assert bundles[0].date == "2026-06-02"
    assert bundles[0].tier is None
# end def test_gmg_single_tier_bundle_yml_shape


def test_standalone_list_without_bundle_directory() -> None:
    bundles = load_bundle_metadata([_list("valve/the-orange-box")])

    assert bundles[0].source == "valve"
    assert bundles[0].bundle_kind is None
    assert bundles[0].date is None
# end def test_standalone_list_without_bundle_directory


def test_dailyindiegame_flat_machine_name_has_no_date() -> None:
    bundles = load_bundle_metadata([_list("dailyindiegame/bundle/2352")])

    assert bundles[0].source == "dailyindiegame"
    assert bundles[0].bundle_kind == "bundle"
    assert bundles[0].date is None
# end def test_dailyindiegame_flat_machine_name_has_no_date
