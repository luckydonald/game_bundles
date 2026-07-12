from __future__ import annotations

from pathlib import Path

from game_collections.launchers.steam.adapter import SteamAdapter, SteamOptions
from game_collections.lists import LoadedGameList, load_game_list


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


def test_adapter_requires_source_or_api_key() -> None:
    try:
        SteamAdapter(SteamOptions(steam_id="76561198044975919"))
    except ValueError as error:
        assert "owned_app_ids_source" in str(error)
    else:
        raise AssertionError("expected ValueError")
    # end try
# end def test_adapter_requires_source_or_api_key
