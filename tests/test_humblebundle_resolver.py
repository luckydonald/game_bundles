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
    CandidateChooser,
    Fetcher,
    HumbleResolutionMap,
    NameCollector,
    StoreCandidate,
    StorefrontResolver,
    load_resolution_map,
    normalized_title,
    parse_store_candidates,
    parse_store_identity,
    render_resolution_map,
)
from game_collections.sources.prompting import EnterMultiple


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

    def choose(_item: HumbleItem, _provider: str, _candidates: list[StoreCandidate], **_kwargs: object) -> str | None:
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
    resolver = StorefrontResolver(lambda _url: page, lambda _item, _provider, _candidates, **_kwargs: None)
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
        lambda _item, _provider, candidates, **_kwargs: candidates[1].url,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["steam:43"]
# end def test_ambiguous_match_uses_selected_url


def test_blank_selection_persists_unresolved_fallback() -> None:
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates, **_kwargs: None)
    mapping = HumbleResolutionMap(schema=1, games={})

    ids = resolver.resolve_item(_item(), mapping)[0].ids

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
        lambda _item, _provider, _candidates, **_kwargs: None,
        steamdb_fetch=steamdb_fetch,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))[0].ids

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
        lambda _item, _provider, _candidates, **_kwargs: None,
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
    )[0].ids

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
        lambda _item, _provider, _candidates, **_kwargs: None,
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
    )[0].ids

    assert ids == ["steam:bundle/46228"]
# end def test_steamdb_fallback_can_resolve_to_a_bundle


def test_steamdb_sub_match_auto_expands_into_its_member_apps() -> None:
    # Trimmed from real steamdb.info pages captured live for sub/729916
    # ("Steelrising - Bastille Edition") - a search results row with no
    # matching steampowered.com listing, and its own "Apps in this package" table.
    steampowered_page = ""
    sub_search_page = """
    <tr class="package" data-subid="729916">
    <td><a href="/sub/729916/">729916</a></td>
    <td><a href="/sub/729916/"><mark>Steelrising</mark> - <mark>Bastille</mark> <mark>Edition</mark></a></td>
    </tr>
    """
    sub_apps_page = """
    <tr class="app" data-appid="2021370">
    <td><a href="/app/2021370/">2021370</a></td><td>DLC</td><td>Steelrising - Discus Chain</td>
    </tr><tr class="app" data-appid="2004261">
    <td><a href="/app/2004261/">2004261</a></td><td>DLC</td><td>Steelrising - Cagliostro's Secrets</td>
    </tr><tr class="app" data-appid="1283400">
    <td><a href="/app/1283400/">1283400</a></td><td>Game</td><td>Steelrising</td>
    </tr>
    """

    def steamdb_fetch(url: str) -> str:
        return sub_apps_page if "/sub/729916/" in url else sub_search_page
    # end def steamdb_fetch

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _title, _provider, _candidates, **_kwargs: None,
        steamdb_fetch=steamdb_fetch,
    )

    item = HumbleItem(
        machine_name="steelrising_bastilleedition",
        title="Steelrising - Bastille Edition",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )
    results = resolver.resolve_item(item, HumbleResolutionMap(schema=1, games={}))

    assert [entry.name for entry in results] == [
        "Steelrising - Discus Chain",
        "Steelrising - Cagliostro's Secrets",
        "Steelrising",
    ]
    assert [entry.ids for entry in results] == [["steam:2021370"], ["steam:2004261"], ["steam:1283400"]]
    assert all(entry.requires == [] for entry in results)
# end def test_steamdb_sub_match_auto_expands_into_its_member_apps


def test_no_steamdb_fetch_behaves_like_steampowered_only() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates, **_kwargs: None,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))[0].ids

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
        lambda _item, _provider, candidates, **_kwargs: candidates[1].url,
        steamdb_fetch=failing_steamdb_fetch,
    )

    ids = resolver.resolve_item(_item(), HumbleResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["steam:43"]
# end def test_steamdb_fetch_error_falls_back_to_steampowered_candidates


def test_resolve_item_splits_a_dlc_pack_and_attaches_requires() -> None:
    page = '<a href="https://store.steampowered.com/app/99/dlc-one/">DLC One</a>'
    item = HumbleItem(
        machine_name="some_dlc_pack",
        title="Some DLC Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        tags=["dlc"],
        base_game_url="https://store.steampowered.com/app/1129190/Our_Life_Beginnings__Always/",
        bundled_dlc_names=["DLC One"],
        resolution=HumbleResolution(),
    )
    resolver = StorefrontResolver(lambda _url: page, lambda _title, _provider, _candidates, **_kwargs: None)

    results = resolver.resolve_item(item, HumbleResolutionMap(schema=1, games={}))

    assert len(results) == 1
    assert results[0].name == "DLC One"
    assert results[0].ids == ["steam:99"]
    assert results[0].requires == ["steam:1129190"]
# end def test_resolve_item_splits_a_dlc_pack_and_attaches_requires


def test_resolve_item_splits_an_edition_bundle_without_requires() -> None:
    pages = {
        "Steelrising": '<a href="https://store.steampowered.com/app/1283400/steelrising/">Steelrising</a>',
        "Steelrising+-+Discus+Chain": (
            '<a href="https://store.steampowered.com/app/2021370/discus-chain/">Steelrising - Discus Chain</a>'
        ),
        "Steelrising+-+Cagliostro%27s+Secrets": (
            '<a href="https://store.steampowered.com/app/2004261/cagliostros-secrets/">'
            "Steelrising - Cagliostro's Secrets</a>"
        ),
    }

    def fetch(url: str) -> str:
        for query, page in sorted(pages.items(), key=lambda pair: -len(pair[0])):
            if query in url:
                return page
            # end if
        # end for
        return ""
    # end def fetch

    item = HumbleItem(
        machine_name="steelrising_bastilleedition",
        title="Steelrising - Bastille Edition",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        edition_component_titles=["Steelrising", "Steelrising - Discus Chain", "Steelrising - Cagliostro's Secrets"],
        resolution=HumbleResolution(),
    )
    resolver = StorefrontResolver(fetch, lambda _title, _provider, _candidates, **_kwargs: None)

    results = resolver.resolve_item(item, HumbleResolutionMap(schema=1, games={}))

    assert [entry.name for entry in results] == [
        "Steelrising",
        "Steelrising - Discus Chain",
        "Steelrising - Cagliostro's Secrets",
    ]
    assert results[0].ids == ["steam:1283400"]
    assert results[1].ids == ["steam:2021370"]
    assert results[2].ids == ["steam:2004261"]
    assert all(entry.requires == [] for entry in results)
# end def test_resolve_item_splits_an_edition_bundle_without_requires


def _combo_pack_fixtures() -> tuple[CandidateChooser, Fetcher, NameCollector]:
    """Shared fixtures for a "Combo Pack" title whose "Multiple…" splits into two exact matches."""
    page = ""

    def choose(title: str, _provider: object, _candidates: object, **_kwargs: object) -> EnterMultiple | None:
        if title == "Combo Pack":
            return EnterMultiple()
        # end if
        return None
    # end def choose

    def fetch(url: str) -> str:
        if "Game+A" in url:
            return '<a href="https://store.steampowered.com/app/10/game-a/">Game A</a>'
        # end if
        if "Game+B" in url:
            return '<a href="https://store.steampowered.com/app/20/game-b/">Game B</a>'
        # end if
        return page
    # end def fetch

    names = iter(["Game A", "Game B"])

    def collect_name(_count: int, _known_names: set[str] | None = None) -> str | None:
        return next(names, None)
    # end def collect_name

    return choose, fetch, collect_name
# end def _combo_pack_fixtures


def test_choosing_multiple_splits_a_title_into_separate_resolved_games() -> None:
    choose, fetch, collect_name = _combo_pack_fixtures()
    resolver = StorefrontResolver(fetch, choose, collect_name=collect_name)
    mapping = HumbleResolutionMap(schema=1, games={})

    item = HumbleItem(
        machine_name="combo_pack",
        title="Combo Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )
    results = resolver.resolve_item(item, mapping)

    assert [entry.name for entry in results] == ["Game A", "Game B"]
    assert results[0].ids == ["steam:10"]
    assert results[1].ids == ["steam:20"]
    # Each split sub-title is cached under its own compound key so a re-run doesn't re-prompt.
    assert mapping.games == {"combo_pack::1": ["steam:10"], "combo_pack::2": ["steam:20"]}
# end def test_choosing_multiple_splits_a_title_into_separate_resolved_games


def test_choosing_multiple_announces_each_name_s_exact_match_immediately() -> None:
    # The per-name search happens interleaved with collection - each name is resolved (and, on a
    # unique exact match, announced) before the next name is asked for, not batched afterward.
    choose, fetch, collect_name = _combo_pack_fixtures()
    announced: list[tuple[str, str]] = []
    resolver = StorefrontResolver(
        fetch, choose, collect_name=collect_name, announce_exact_match=lambda qid, url: announced.append((qid, url))
    )
    item = HumbleItem(
        machine_name="combo_pack",
        title="Combo Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )

    resolver.resolve_item(item, HumbleResolutionMap(schema=1, games={}))

    assert announced == [
        ("steam:10", "https://store.steampowered.com/app/10/game-a/"),
        ("steam:20", "https://store.steampowered.com/app/20/game-b/"),
    ]
# end def test_choosing_multiple_announces_each_name_s_exact_match_immediately


def test_choosing_multiple_never_offers_multiple_again_for_a_collected_name() -> None:
    # A name collected under "Multiple…" must not itself offer to split further - the chooser
    # receives allow_multiple=False for it, unlike the initial, top-level choice.
    seen_allow_multiple: list[bool] = []

    def choose(title: str, _provider: object, _candidates: object, *, allow_multiple: bool, **_kwargs: object) -> object:
        seen_allow_multiple.append(allow_multiple)
        if title == "Combo Pack":
            return EnterMultiple()
        # end if
        return None
    # end def choose

    names = iter(["Ambiguous Game"])

    def collect_name(_count: int, _known_names: set[str] | None = None) -> str | None:
        return next(names, None)
    # end def collect_name

    page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    resolver = StorefrontResolver(lambda _url: page, choose, collect_name=collect_name)
    item = HumbleItem(
        machine_name="combo_pack",
        title="Combo Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )

    resolver.resolve_item(item, HumbleResolutionMap(schema=1, games={}))

    assert seen_allow_multiple == [True, False]
# end def test_choosing_multiple_never_offers_multiple_again_for_a_collected_name


def test_resolve_archive_writes_splits_for_a_plain_item_resolved_into_several_games() -> None:
    # A plain item (no `bundled_dlc_names`/`edition_component_titles`) whose resolution still
    # discovers several distinct games - e.g. the user declaring "Multiple…" for a title like
    # "Torchlight 1-3 Bundle" - must produce separate `Game` entries downstream, not one entry
    # whose `ids` silently mixes three unrelated games' appids together.
    choose, fetch, collect_name = _combo_pack_fixtures()
    resolver = StorefrontResolver(fetch, choose, collect_name=collect_name)
    item = HumbleItem(
        machine_name="combo_pack",
        title="Combo Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(),
    )

    resolved = resolver.resolve_archive(_archive(item), HumbleResolutionMap(schema=1, games={}))

    resolution = resolved.tiers[0].items[0].resolution
    assert resolution.ids == []
    assert [(split.name, split.ids) for split in resolution.splits] == [
        ("Game A", ["steam:10"]),
        ("Game B", ["steam:20"]),
    ]
# end def test_resolve_archive_writes_splits_for_a_plain_item_resolved_into_several_games


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
