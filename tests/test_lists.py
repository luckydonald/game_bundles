from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from game_collections.lists import ListLoadError, derive_list_id, discover_game_lists, load_game_list


REPO_ROOT = Path(__file__).parents[1]


def test_orange_box_is_valid_initial_data() -> None:
    loaded = load_game_list(
        REPO_ROOT / "lists/valve/the-orange-box.yml",
        REPO_ROOT / "lists",
    )

    assert loaded.id == "valve/the-orange-box"
    assert loaded.data.name == "The Orange Box"
    assert [game.ids for game in loaded.data.games] == [
        ["steam:220"],
        ["steam:380"],
        ["steam:420"],
        ["steam:400"],
        ["steam:440"],
    ]
# end def test_orange_box_is_valid_initial_data


def test_every_repository_list_validates() -> None:
    loaded = discover_game_lists(REPO_ROOT / "lists")
    ids = [game_list.id for game_list in loaded]
    assert "valve/the-orange-box" in ids
# end def test_every_repository_list_validates


def test_path_derived_id_accepts_source_filename_characters(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "bundle" / "Steam's-(Christmas)-sale+bonus-&-%20.yml"
    path.parent.mkdir(parents=True)
    path.write_text("schema: 1\nname: Sale\ngames:\n  - name: One\n    ids: [steam:440]\n", encoding="utf-8")

    assert derive_list_id(path, lists_root) == "bundle/Steam's-(Christmas)-sale+bonus-&-%20"
# end def test_path_derived_id_accepts_source_filename_characters


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "invalid.yml"
    path.write_text("schema: 1\nname: Invalid\ngames: []\nextra: true\n", encoding="utf-8")

    with pytest.raises(ListLoadError, match="extra"):
        load_game_list(path, lists_root)
    # end with
# end def test_unknown_fields_are_rejected


def test_references_accept_file_paths_and_urls(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "referenced.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "name": "Referenced",
                "references": [
                    {"name": "Local metadata", "path": "../archives/metadata.json"},
                    {"name": "Repository source", "path": "/archives/source.json"},
                    {"name": "Website", "url": "https://example.com/bundle"},
                ],
                "games": [{"name": "One", "ids": ["steam:440"]}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    loaded = load_game_list(path, lists_root)

    assert [reference.path for reference in loaded.data.references] == [
        "../archives/metadata.json",
        "/archives/source.json",
        None,
    ]
# end def test_references_accept_file_paths_and_urls


def test_duplicate_qualified_ids_are_rejected(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "invalid.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "name": "Invalid",
                "games": [
                    {"name": "One", "ids": ["steam:440"]},
                    {"name": "Two", "ids": ["steam:440"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ListLoadError, match="duplicate qualified"):
        load_game_list(path, lists_root)
    # end with
# end def test_duplicate_qualified_ids_are_rejected


def test_tier_field_is_optional_and_defaults_to_none(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "bundle.yml"
    path.write_text("schema: 1\nname: Bundle\ngames:\n  - name: One\n    ids: [steam:440]\n", encoding="utf-8")

    loaded = load_game_list(path, lists_root)

    assert loaded.data.tier is None
# end def test_tier_field_is_optional_and_defaults_to_none


def test_tier_field_round_trips_when_set(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "tier-2.yml"
    path.write_text(
        "schema: 1\nname: Tier 2\ntier: 2\ngames:\n  - name: One\n    ids: [steam:440]\n",
        encoding="utf-8",
    )

    loaded = load_game_list(path, lists_root)

    assert loaded.data.tier == 2
# end def test_tier_field_round_trips_when_set


def test_pick_quota_field_is_optional_and_defaults_to_none(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "bundle.yml"
    path.write_text("schema: 1\nname: Bundle\ngames:\n  - name: One\n    ids: [steam:440]\n", encoding="utf-8")

    loaded = load_game_list(path, lists_root)

    assert loaded.data.pick_quota is None
# end def test_pick_quota_field_is_optional_and_defaults_to_none


def test_pick_quota_field_round_trips_when_set(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "byob.yml"
    path.write_text(
        "schema: 1\nname: BYOB\npick_quota: 1\n"
        "games:\n  - name: One\n    ids: [steam:440]\n  - name: Two\n    ids: [steam:441]\n",
        encoding="utf-8",
    )

    loaded = load_game_list(path, lists_root)

    assert loaded.data.pick_quota == 1
# end def test_pick_quota_field_round_trips_when_set


def test_pick_quota_exceeding_game_count_is_rejected(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "invalid.yml"
    path.write_text(
        "schema: 1\nname: Invalid\npick_quota: 5\ngames:\n  - name: One\n    ids: [steam:440]\n",
        encoding="utf-8",
    )

    with pytest.raises(ListLoadError, match="pick_quota"):
        load_game_list(path, lists_root)
    # end with
# end def test_pick_quota_exceeding_game_count_is_rejected


def test_symlinked_lists_are_rejected(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    target = tmp_path / "outside.yml"
    target.write_text("schema: 1\nname: Outside\ngames: []\n", encoding="utf-8")
    linked = lists_root / "linked.yml"
    linked.symlink_to(target)

    with pytest.raises(ListLoadError, match="symlink"):
        derive_list_id(linked, lists_root)
    # end with
# end def test_symlinked_lists_are_rejected
