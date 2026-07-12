from __future__ import annotations

from game_collections.search import complete_game_list, selected_providers
from game_collections.sources.humblebundle.resolver import StoreCandidate, StorefrontResolver


def test_selected_providers_defaults_to_every_supported_store() -> None:
    assert selected_providers("all") == ("steam", "gog", "epic", "ubisoft", "humble")
# end def test_selected_providers_defaults_to_every_supported_store


def test_complete_game_list_fills_missing_ids_and_preserves_existing_ids() -> None:
    pages = {
        "steam": '<a href="https://store.steampowered.com/app/400/Portal/">Portal</a>',
        "gog": '<a href="https://www.gog.com/en/game/portal">Portal</a>',
    }

    def fetch(url: str) -> str:
        return pages["steam"] if "steampowered" in url else pages["gog"]
    # end def fetch

    raw = {
        "schema": 1,
        "name": "Draft",
        "games": [
            {"name": "Portal"},
            {"name": "Team Fortress 2", "ids": ["steam:440"]},
        ],
    }
    completed, unresolved = complete_game_list(
        raw,
        ("steam", "gog"),
        StorefrontResolver(fetch, lambda _item, _provider, _candidates: None),
        lambda _title, _provider, _candidates: None,
    )

    assert unresolved == []
    assert completed["games"] == [
        {"name": "Portal", "ids": ["steam:400", "gog:portal"]},
        {"name": "Team Fortress 2", "ids": ["steam:440"]},
    ]
    assert "ids" not in raw["games"][0]
# end def test_complete_game_list_fills_missing_ids_and_preserves_existing_ids


def test_complete_game_list_keeps_unresolved_game_as_draft() -> None:
    raw = {"schema": 1, "name": "Draft", "games": [{"name": "Unknown", "ids": []}]}
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates: None)

    completed, unresolved = complete_game_list(
        raw,
        ("steam",),
        resolver,
        lambda _title, _provider, _candidates: None,
    )

    assert unresolved == ["Unknown"]
    assert completed["games"] == [{"name": "Unknown"}]
# end def test_complete_game_list_keeps_unresolved_game_as_draft


def test_complete_game_list_uses_manual_candidate_selection() -> None:
    candidates = '<a href="https://store.steampowered.com/app/10/Other/">Other</a>'
    resolver = StorefrontResolver(lambda _url: candidates, lambda *_args: None)
    selected: list[StoreCandidate] = []

    def choose(
        _title: str,
        _provider: str,
        results: list[StoreCandidate],
    ) -> str | None:
        selected.extend(results)
        return results[0].url
    # end def choose

    completed, unresolved = complete_game_list(
        {"schema": 1, "name": "Draft", "games": [{"name": "Wanted"}]},
        ("steam",),
        resolver,
        choose,  # type: ignore[arg-type]
    )

    assert unresolved == []
    assert selected[0].qualified_id == "steam:10"
    assert completed["games"][0]["ids"] == ["steam:10"]
# end def test_complete_game_list_uses_manual_candidate_selection
