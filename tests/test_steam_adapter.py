from __future__ import annotations

from pathlib import Path

from game_collections.launchers.steam.adapter import SteamAdapter, SteamOptions
from game_collections.launchers.steam.models import GetOwnedGamesResponse
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


class FakeSteamApiClient:
    def __init__(self, owned: list[int]) -> None:
        self.owned = owned
    # end def __init__

    def get_owned_games(self, _steam_id: str) -> GetOwnedGamesResponse:
        return GetOwnedGamesResponse.model_validate(
            {
                "response": {
                    "game_count": len(self.owned),
                    "games": [{"appid": app_id} for app_id in self.owned],
                }
            }
        )
    # end def get_owned_games

# end class FakeSteamApiClient


def test_orange_box_requires_every_game() -> None:
    game_lists = _orange_box()
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", api_key="unused"),
        api_client=FakeSteamApiClient([220, 380, 420, 400]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate(game_lists)[0]

    assert result.eligible is False
    assert result.missing_ids == ["steam:440"]
# end def test_orange_box_requires_every_game


def test_orange_box_is_eligible_when_complete() -> None:
    game_lists = _orange_box()
    adapter = SteamAdapter(
        SteamOptions(steam_id="76561198044975919", api_key="unused"),
        api_client=FakeSteamApiClient([220, 380, 420, 400, 440]),  # type: ignore[arg-type]
    )

    result = adapter.evaluate(game_lists)[0]

    assert result.eligible is True
    assert result.missing_ids == []
# end def test_orange_box_is_eligible_when_complete
