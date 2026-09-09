from __future__ import annotations

from datetime import UTC, datetime

import pytest

from game_collections.search import complete_game_list, selected_providers
from game_collections.sources.humblebundle.resolver import StoreCandidate, StorefrontResolver
from game_collections.sources.isthereanydeal.models import ItadDates, ItadGameArchive
from game_collections.sources.isthereanydeal.resolver import ItadGameResolution
from game_collections.sources.prompting import ChosenNames


def test_selected_providers_defaults_to_every_supported_store() -> None:
    assert selected_providers(None, default="all") == (
        "steam",
        "gog",
        "epic",
        "ubisoft",
        "humble",
    )
# end def test_selected_providers_defaults_to_every_supported_store


def test_selected_providers_accepts_repeated_and_comma_separated_values() -> None:
    assert selected_providers(["steam,gog", "steam", "epic"], default="steam") == (
        "steam",
        "gog",
        "epic",
    )
# end def test_selected_providers_accepts_repeated_and_comma_separated_values


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
        StorefrontResolver(fetch, lambda _item, _provider, _candidates, **_kwargs: None),
        lambda _title, _provider, _candidates, **_kwargs: None,
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
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates, **_kwargs: None)

    completed, unresolved = complete_game_list(
        raw,
        ("steam",),
        resolver,
        lambda _title, _provider, _candidates, **_kwargs: None,
    )

    assert unresolved == ["Unknown"]
    assert completed["games"] == [
        {"name": "Unknown", "ids": ["unresolved:store:steam:unknown"]}
    ]
# end def test_complete_game_list_keeps_unresolved_game_as_draft


def test_complete_game_list_uses_manual_candidate_selection() -> None:
    candidates = '<a href="https://store.steampowered.com/app/10/Other/">Other</a>'
    resolver = StorefrontResolver(lambda _url: candidates, lambda *_args: None)
    selected: list[StoreCandidate] = []

    def choose(
        _title: str,
        _provider: str,
        results: list[StoreCandidate],
        **_kwargs: object,
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


def test_complete_game_list_splits_a_title_declared_multiple_into_grouped_games() -> None:
    def fetch(url: str) -> str:
        if "Combo+Pack" in url:
            return ""
        if "Game+A" in url:
            return '<a href="https://store.steampowered.com/app/10/game-a/">Game A</a>'
        # end if
        return '<a href="https://store.steampowered.com/app/20/game-b/">Game B</a>'
    # end def fetch

    def choose(title: str, _provider: str, _candidates: list[StoreCandidate], **_kwargs: object) -> object:
        if title == "Combo Pack":
            return ChosenNames(names=["Game A", "Game B"])
        # end if
        return None
    # end def choose

    completed, unresolved = complete_game_list(
        {"schema": 1, "name": "Draft", "games": [{"name": "Combo Pack"}]},
        ("steam",),
        StorefrontResolver(fetch, lambda *_args: None),
        choose,  # type: ignore[arg-type]
    )

    assert unresolved == []
    names = [game["name"] for game in completed["games"]]
    assert names == ["Game A", "Game B"]
    assert completed["games"][0]["ids"] == ["steam:10"]
    assert completed["games"][1]["ids"] == ["steam:20"]
    assert completed["games"][0]["group"] == completed["games"][1]["group"]
    assert completed["games"][0]["group"]["name"] == "Combo Pack"
# end def test_complete_game_list_splits_a_title_declared_multiple_into_grouped_games


def test_blank_skips_a_game_with_any_proper_id() -> None:
    searched: list[str] = []

    def fetch(url: str) -> str:
        searched.append(url)
        return ""
    # end def fetch

    completed, unresolved = complete_game_list(
        {"schema": 1, "name": "Draft", "games": [{"name": "Portal", "ids": ["gog:portal"]}]},
        ("steam",),
        StorefrontResolver(fetch, lambda *_args: None),
        lambda *_args: None,
        "blank",
    )

    assert searched == []
    assert unresolved == []
    assert completed["games"][0]["ids"] == ["gog:portal"]
# end def test_blank_skips_a_game_with_any_proper_id


def test_missing_does_not_retry_a_store_failure_but_unresolved_does() -> None:
    raw = {
        "schema": 1,
        "name": "Draft",
        "games": [{"name": "Portal", "ids": ["unresolved:store:steam:portal"]}],
    }
    searches: list[str] = []

    def fetch(url: str) -> str:
        searches.append(url)
        return '<a href="https://store.steampowered.com/app/400/Portal/">Portal</a>'
    # end def fetch

    missing, _unresolved = complete_game_list(
        raw,
        ("steam",),
        StorefrontResolver(fetch, lambda *_args: None),
        lambda *_args: None,
        "missing",
    )
    retried, _unresolved = complete_game_list(
        raw,
        ("steam",),
        StorefrontResolver(fetch, lambda *_args: None),
        lambda *_args: None,
        "unresolved",
    )

    assert missing["games"][0]["ids"] == ["unresolved:store:steam:portal"]
    assert retried["games"][0]["ids"] == ["steam:400"]
    assert len(searches) == 1
# end def test_missing_does_not_retry_a_store_failure_but_unresolved_does


def test_refetch_all_replaces_only_ids_for_selected_stores() -> None:
    page = '<a href="https://store.steampowered.com/app/401/Portal_New/">Portal</a>'
    completed, unresolved = complete_game_list(
        {
            "schema": 1,
            "name": "Draft",
            "games": [{"name": "Portal", "ids": ["steam:400", "gog:portal"]}],
        },
        ("steam",),
        StorefrontResolver(lambda _url: page, lambda *_args: None),
        lambda *_args: None,
        "refetch_all",
    )

    assert unresolved == []
    assert completed["games"][0]["ids"] == ["gog:portal", "steam:401"]
# end def test_refetch_all_replaces_only_ids_for_selected_stores


def test_success_removes_source_unresolved_marker() -> None:
    page = '<a href="https://store.steampowered.com/app/400/Portal/">Portal</a>'
    completed, _unresolved = complete_game_list(
        {
            "schema": 1,
            "name": "Draft",
            "games": [
                {"name": "Portal", "ids": ["unresolved:source:humblebundle:portal"]}
            ],
        },
        ("steam",),
        StorefrontResolver(lambda _url: page, lambda *_args: None),
        lambda *_args: None,
        "blank",
    )

    assert completed["games"][0]["ids"] == ["steam:400"]
# end def test_success_removes_source_unresolved_marker


def _itad_resolution(slug: str, appid: int) -> ItadGameResolution:
    archive = ItadGameArchive(
        schema=1,
        slug=slug,
        title=slug,
        appid=appid,
        ids=[f"steam:{appid}", f"isthereanydeal:{slug}"],
        url=f"https://isthereanydeal.com/game/{slug}/info/",
        dates=ItadDates(crawled=datetime(2026, 7, 13, tzinfo=UTC)),
    )
    return ItadGameResolution(archive=archive, source={})
# end def _itad_resolution


def test_complete_game_list_resolves_isthereanydeal_marker() -> None:
    completed, unresolved = complete_game_list(
        {
            "schema": 1,
            "name": "Draft",
            "games": [
                {
                    "name": "WildStar",
                    "ids": ["unresolved:source:isthereanydeal:2126:wildstar"],
                }
            ],
        },
        ("isthereanydeal",),
        StorefrontResolver(lambda _url: "", lambda *_args: None),
        lambda *_args: None,
        "unresolved",
        itad_resolve=lambda slug: _itad_resolution(slug, 376870),
    )

    assert completed["games"][0]["ids"] == ["steam:376870", "isthereanydeal:wildstar"]
    assert unresolved == []
# end def test_complete_game_list_resolves_isthereanydeal_marker


def test_complete_game_list_leaves_non_matching_games_untouched() -> None:
    completed, _unresolved = complete_game_list(
        {
            "schema": 1,
            "name": "Draft",
            "games": [{"name": "Already Resolved", "ids": ["steam:1"]}],
        },
        ("isthereanydeal",),
        StorefrontResolver(lambda _url: "", lambda *_args: None),
        lambda *_args: None,
        "unresolved",
        itad_resolve=lambda _slug: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    assert completed["games"][0]["ids"] == ["steam:1"]
# end def test_complete_game_list_leaves_non_matching_games_untouched


def test_complete_game_list_raises_when_itad_resolve_omitted() -> None:
    with pytest.raises(ValueError, match="itad_resolve"):
        complete_game_list(
            {"schema": 1, "name": "Draft", "games": [{"name": "X", "ids": ["unresolved:source:isthereanydeal:1:x"]}]},
            ("isthereanydeal",),
            StorefrontResolver(lambda _url: "", lambda *_args: None),
            lambda *_args: None,
            "unresolved",
        )
    # end with
# end def test_complete_game_list_raises_when_itad_resolve_omitted
