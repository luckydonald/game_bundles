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
    assert len(ids) == 16
    assert "valve/the-orange-box" in ids
# end def test_every_repository_list_validates


def test_unknown_fields_are_rejected(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    lists_root.mkdir()
    path = lists_root / "invalid.yml"
    path.write_text("schema: 1\nname: Invalid\ngames: []\nextra: true\n", encoding="utf-8")

    with pytest.raises(ListLoadError, match="extra"):
        load_game_list(path, lists_root)
    # end with
# end def test_unknown_fields_are_rejected


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
