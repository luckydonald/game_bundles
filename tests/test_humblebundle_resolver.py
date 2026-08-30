from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from game_collections.sources.humblebundle.models import (
    HumbleArchive,
    HumbleDates,
    HumbleItem,
    HumbleResolution,
    HumbleTier,
)
from game_collections.sources.humblebundle.resolver import (
    HumbleResolutionMap,
    StoreCandidate,
    StorefrontResolver,
    load_resolution_map,
    normalized_title,
    parse_store_candidates,
    parse_store_identity,
    render_resolution_map,
)


def _item(machine_name: str = "sample_game") -> HumbleItem:
    return HumbleItem(
        machine_name=machine_name,
        title="Sample Game™",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )
# end def _item


def _archive(item: HumbleItem) -> HumbleArchive:
    return HumbleArchive(
        schema=1,
        kind="bundle",
        machine_name="sample_bundle",
        url="https://www.humblebundle.com/games/sample",
        name="Sample Bundle",
        headline="Sample",
        description="Sample.",
        dates=HumbleDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        tiers=[
            HumbleTier(
                identifier="all",
                name="Entire 1 Item Bundle",
                item_count=1,
                items=[item],
            )
        ],
    )
# end def _archive


@pytest.mark.parametrize(
    ("provider", "value", "expected"),
    [
        ("steam", "440", "steam:440"),
        ("steam", "https://store.steampowered.com/app/440/Team_Fortress_2/", "steam:440"),
        ("gog", "https://www.gog.com/en/game/alpha_protocol", "gog:alpha_protocol"),
        ("epic", "https://store.epicgames.com/en-US/p/fortnite", "epic:fortnite"),
        ("epic", "https://www.epicgames.com/store/p/cyberpunk-2077", "epic:cyberpunk-2077"),
        ("ubisoft", "https://store.ubisoft.com/us/game/example.html", "ubisoft:example"),
        ("humble", "https://www.humblebundle.com/store/sample-game", "humble:sample-game"),
    ],
)
def test_parse_store_identity(provider: str, value: str, expected: str) -> None:
    assert parse_store_identity(provider, value) == expected  # type: ignore[arg-type]
# end def test_parse_store_identity


def test_parse_store_identity_rejects_wrong_host() -> None:
    with pytest.raises(ValueError, match="Steam URLs"):
        parse_store_identity("steam", "https://example.com/app/440")
    # end with
# end def test_parse_store_identity_rejects_wrong_host


def test_store_candidates_preserve_search_order_and_remove_duplicates() -> None:
    page = """
    <a href="https://store.steampowered.com/app/10/First/">
      <span class="title">First Game</span><div>1 Jan, 2026 9.99€</div>
    </a>
    <a href="https://store.steampowered.com/app/10/First/">First Duplicate</a>
    <a href="https://store.steampowered.com/app/20/Second/">Second Game</a>
    """

    candidates = parse_store_candidates("steam", page)

    assert [candidate.qualified_id for candidate in candidates] == ["steam:10", "steam:20"]
    assert candidates[0].title == "First Game"
# end def test_store_candidates_preserve_search_order_and_remove_duplicates


def test_normalized_title_ignores_case_punctuation_and_trademark() -> None:
    assert normalized_title("Sample Game™") == normalized_title("sample-game")
# end def test_normalized_title_ignores_case_punctuation_and_trademark


def test_unique_exact_match_is_accepted_without_prompt() -> None:
    page = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'
    prompted = False

    def choose(_item: HumbleItem, _provider: str, _candidates: list[StoreCandidate]) -> str | None:
        nonlocal prompted
        prompted = True
        return None
    # end def choose

    resolver = StorefrontResolver(lambda _url: page, choose)
    mapping = HumbleResolutionMap(schema=1, games={})

    resolved = resolver.resolve_archive(_archive(_item()), mapping)

    assert prompted is False
    assert resolved.tiers[0].items[0].resolution.ids == ["steam:42"]
    assert mapping.games == {"sample_game": ["steam:42"]}
# end def test_unique_exact_match_is_accepted_without_prompt


def test_resolve_archive_logs_progress_per_distinct_game() -> None:
    page = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'
    resolver = StorefrontResolver(lambda _url: page, lambda _item, _provider, _candidates: None)
    messages: list[str] = []

    resolver.resolve_archive(_archive(_item()), HumbleResolutionMap(schema=1, games={}), log=messages.append)

    assert any("Game 1/1" in message and "Sample Game" in message for message in messages)
# end def test_resolve_archive_logs_progress_per_distinct_game


def test_ambiguous_match_uses_selected_url() -> None:
    page = """
    <a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>
    <a href="https://store.steampowered.com/app/43/sample/">Sample Game</a>
    """
    resolver = StorefrontResolver(
        lambda _url: page,
        lambda _item, _provider, candidates: candidates[1].url,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))

    assert ids == ["steam:43"]
# end def test_ambiguous_match_uses_selected_url


def test_blank_selection_persists_unresolved_fallback() -> None:
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates: None)
    mapping = HumbleResolutionMap(schema=1, games={})

    ids = resolver.resolve_item(_item(), mapping)

    assert ids == ["unresolved:source:humblebundle:sample_game"]
    assert mapping.games == {"sample_game": ids}
# end def test_blank_selection_persists_unresolved_fallback


def test_unique_steampowered_match_skips_steamdb_fallback() -> None:
    steampowered_page = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'
    steamdb_called = False

    def steamdb_fetch(_url: str) -> str:
        nonlocal steamdb_called
        steamdb_called = True
        return ""
    # end def steamdb_fetch

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates: None,
        steamdb_fetch=steamdb_fetch,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))

    assert ids == ["steam:42"]
    assert steamdb_called is False
# end def test_unique_steampowered_match_skips_steamdb_fallback


def test_ambiguous_steampowered_match_falls_back_to_steamdb() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    steamdb_page = '<a href="/app/3011360/">Primordialis</a>'

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates: None,
        steamdb_fetch=lambda _url: steamdb_page,
    )

    ids = resolver.resolve_item(
        HumbleItem(
            machine_name="primordialis",
            title="Primordialis",
            item_type="game",
            is_game=True,
            redeem_on=["steam"],
            resolution=HumbleResolution(),
        ),
        HumbleResolutionMap(schema=1, games={}),
    )

    assert ids == ["steam:3011360"]
# end def test_ambiguous_steampowered_match_falls_back_to_steamdb


def test_steamdb_fallback_can_resolve_to_a_bundle() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    steamdb_page = '<a href="/bundle/46228/">Forgive Me Father 2 Deluxe Edition</a>'

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates: None,
        steamdb_fetch=lambda _url: steamdb_page,
    )

    ids = resolver.resolve_item(
        HumbleItem(
            machine_name="forgive_me_father_2_deluxe",
            title="Forgive Me Father 2 Deluxe Edition",
            item_type="game",
            is_game=True,
            redeem_on=["steam"],
            resolution=HumbleResolution(),
        ),
        HumbleResolutionMap(schema=1, games={}),
    )

    assert ids == ["steam:bundle/46228"]
# end def test_steamdb_fallback_can_resolve_to_a_bundle


def test_no_steamdb_fetch_behaves_like_steampowered_only() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates: None,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))

    assert ids == ["unresolved:source:humblebundle:sample_game"]
# end def test_no_steamdb_fetch_behaves_like_steampowered_only


def test_steamdb_fetch_error_falls_back_to_steampowered_candidates() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>
    <a href="https://store.steampowered.com/app/43/sample/">Sample Game</a>
    """

    def failing_steamdb_fetch(_url: str) -> str:
        raise OSError("network unavailable")
    # end def failing_steamdb_fetch

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, candidates: candidates[1].url,
        steamdb_fetch=failing_steamdb_fetch,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))

    assert ids == ["steam:43"]
# end def test_steamdb_fetch_error_falls_back_to_steampowered_candidates


def test_resolution_map_round_trip_is_sorted(tmp_path: Path) -> None:
    mapping = HumbleResolutionMap(
        schema=1,
        games={"zeta": ["steam:2"], "alpha": ["gog:alpha"]},
    )
    rendered = render_resolution_map(mapping)
    path = tmp_path / "map.yml"
    path.write_text(rendered, encoding="utf-8")

    assert rendered.index("alpha:") < rendered.index("zeta:")
    assert load_resolution_map(path) == mapping
# end def test_resolution_map_round_trip_is_sorted
