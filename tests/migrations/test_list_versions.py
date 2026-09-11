from __future__ import annotations

from pathlib import Path

import yaml

from game_collections.lists import load_game_list
from game_collections.migrations.list_versions import (
    apply_bundle_migration_group,
    apply_unit_state,
    bundle_commit_message,
    build_unit_trajectory,
    discover_list_units,
    plan_bundle_migrations,
)


def _write(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
# end def _write


def _run_unit(unit: Path, lists_root: Path, repository_root: Path) -> list[int]:
    versions: list[int] = []
    for snapshot in build_unit_trajectory(unit, lists_root):
        versions.append(snapshot.version)
        apply_unit_state(snapshot.data, repository_root)
    # end for
    return versions
# end def _run_unit


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    lists_root = tmp_path / "lists"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")
    return lists_root, tmp_path
# end def _setup


def test_single_tier_bundle_is_flattened_one_level_up_in_two_steps(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    unit = lists_root / "testprovider/bundle/solo-bundle"
    _write(unit / "bundle.yml", {"schema": 1, "name": "Solo Bundle", "games": [{"name": "Only Game", "ids": ["steam:9"]}]})

    versions = _run_unit(unit, lists_root, repository_root)

    assert versions == [2, 3]
    final_path = lists_root / "testprovider/bundle/solo-bundle.yml"
    assert final_path.exists()
    assert not unit.exists()
    loaded = load_game_list(final_path, lists_root)
    assert loaded.data.name == "Solo Bundle"
    assert loaded.data.tiers == []
    assert [game.name for game in loaded.data.games] == ["Only Game"]
# end def test_single_tier_bundle_is_flattened_one_level_up_in_two_steps


def test_multi_tier_bundle_merges_cumulatively_one_step_per_sibling(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    unit = lists_root / "testprovider/bundle/my-bundle"
    _write(unit / "tier-1.yml", {"schema": 1, "name": "My Bundle — Bronze", "games": [{"name": "Game A", "ids": ["steam:1"]}]})
    _write(
        unit / "tier-2.yml",
        {
            "schema": 1,
            "name": "My Bundle — Silver",
            "games": [{"name": "Game A", "ids": ["steam:1"]}, {"name": "Game B", "ids": ["steam:2"]}],
        },
    )
    _write(
        unit / "tier-3.yml",
        {
            "schema": 1,
            "name": "My Bundle — Gold",
            "games": [
                {"name": "Game A", "ids": ["steam:1"]},
                {"name": "Game B", "ids": ["steam:2"]},
                {"name": "Game C", "ids": ["steam:3"]},
            ],
        },
    )

    versions = _run_unit(unit, lists_root, repository_root)

    assert versions == [2, 3, 4, 5]
    final_path = lists_root / "testprovider/bundle/my-bundle.yml"
    assert final_path.exists()
    assert not unit.exists()
    loaded = load_game_list(final_path, lists_root)
    assert loaded.data.name == "My Bundle"
    assert [(t.rank, t.name) for t in loaded.data.tiers] == [(1, "Bronze"), (2, "Silver"), (3, "Gold")]
    memberships = {game.name: game.tiers for game in loaded.data.games}
    assert memberships == {"Game A": [1, 2, 3], "Game B": [2, 3], "Game C": [3]}
# end def test_multi_tier_bundle_merges_cumulatively_one_step_per_sibling


def test_choice_directory_is_merged_without_any_tiers_py_rename(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    unit = lists_root / "humblebundle/choice/2026-01"
    _write(unit / "tier-1.yml", {"schema": 1, "tier": 1, "name": "2026-01 — pick 3", "games": [{"name": "Choice A", "ids": ["steam:11"]}]})
    _write(
        unit / "tier-2.yml",
        {
            "schema": 1,
            "tier": 2,
            "name": "2026-01 — pick 6",
            "games": [{"name": "Choice A", "ids": ["steam:11"]}, {"name": "Choice B", "ids": ["steam:12"]}],
        },
    )

    _run_unit(unit, lists_root, repository_root)

    final_path = lists_root / "humblebundle/choice/2026-01.yml"
    assert final_path.exists()
    loaded = load_game_list(final_path, lists_root)
    assert [(t.rank, t.name) for t in loaded.data.tiers] == [(1, "pick 3"), (2, "pick 6")]
    memberships = {game.name: game.tiers for game in loaded.data.games}
    assert memberships == {"Choice A": [1, 2], "Choice B": [2]}
# end def test_choice_directory_is_merged_without_any_tiers_py_rename


def test_flat_non_directory_list_only_bumps_schema(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    flat_path = lists_root / "dailyindiegame/bundle/2351.yml"
    _write(flat_path, {"schema": 1, "name": "DIG Bundle 2351", "games": [{"name": "Flat Game", "ids": ["steam:42"]}]})

    versions = _run_unit(flat_path, lists_root, repository_root)

    assert versions == [2]
    assert yaml.safe_load(flat_path.read_text(encoding="utf-8"))["schema"] == 2
    loaded = load_game_list(flat_path, lists_root)
    assert loaded.data.name == "DIG Bundle 2351"
# end def test_flat_non_directory_list_only_bumps_schema


def test_discover_list_units_finds_directories_and_flat_files(tmp_path: Path) -> None:
    lists_root, _repository_root = _setup(tmp_path)
    _write(lists_root / "testprovider/bundle/my-bundle/tier-1.yml", {"schema": 1, "name": "x", "games": [{"name": "A", "ids": ["steam:1"]}]})
    _write(lists_root / "dailyindiegame/bundle/1.yml", {"schema": 1, "name": "y", "games": [{"name": "B", "ids": ["steam:2"]}]})

    units = discover_list_units(lists_root)

    assert lists_root / "testprovider/bundle/my-bundle" in units
    assert lists_root / "dailyindiegame/bundle/1.yml" in units
# end def test_discover_list_units_finds_directories_and_flat_files


def test_plan_bundle_migrations_groups_across_units_by_version(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    solo = lists_root / "testprovider/bundle/solo-bundle"
    multi = lists_root / "testprovider/bundle/my-bundle"
    _write(solo / "bundle.yml", {"schema": 1, "name": "Solo Bundle", "games": [{"name": "Only Game", "ids": ["steam:9"]}]})
    _write(multi / "tier-1.yml", {"schema": 1, "name": "My Bundle — Bronze", "games": [{"name": "Game A", "ids": ["steam:1"]}]})
    _write(
        multi / "tier-2.yml",
        {"schema": 1, "name": "My Bundle — Silver", "games": [{"name": "Game A", "ids": ["steam:1"]}, {"name": "Game B", "ids": ["steam:2"]}]},
    )
    units = [solo, multi]

    groups = list(plan_bundle_migrations(units, lists_root))

    # solo has 2 steps (targets 2, 3); multi (2 tiers) has 3 (targets 2, 3, 4) - both
    # advance together through 2 and 3, then multi continues alone through 4.
    assert [group.version for group, _snapshots in groups] == [2, 3, 4]
    assert set(groups[0][0].units) == {solo, multi}
    assert set(groups[1][0].units) == {solo, multi}
    assert groups[2][0].units == (multi,)
    assert bundle_commit_message(groups[0][0]) == "[lists] bundle: Migrated 2 bundle list unit(s) to schema 2."

    for group, snapshots in groups:
        apply_bundle_migration_group(group, snapshots, repository_root)
    # end for

    assert (lists_root / "testprovider/bundle/solo-bundle.yml").exists()
    assert (lists_root / "testprovider/bundle/my-bundle.yml").exists()
# end def test_plan_bundle_migrations_groups_across_units_by_version


def test_already_current_unit_yields_no_steps(tmp_path: Path) -> None:
    lists_root, repository_root = _setup(tmp_path)
    unit = lists_root / "testprovider/bundle/solo-bundle"
    _write(unit / "bundle.yml", {"schema": 1, "name": "Solo Bundle", "games": [{"name": "Only Game", "ids": ["steam:9"]}]})
    _run_unit(unit, lists_root, repository_root)
    final_path = lists_root / "testprovider/bundle/solo-bundle.yml"

    assert list(build_unit_trajectory(final_path, lists_root)) == []
# end def test_already_current_unit_yields_no_steps
