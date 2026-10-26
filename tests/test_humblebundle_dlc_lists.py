from __future__ import annotations

from game_collections.sources.humblebundle.dlc_lists import classify_dlc_list, looks_like_prose
from game_collections.sources.humblebundle.migrations import METADATA_MIGRATIONS
from game_collections.sources.humblebundle.models import HUMBLE_V2, HUMBLE_V3, HumbleItem, HumbleResolution
from game_collections.sources.humblebundle.parser import _parse_dlc_pack_details
from game_collections.sources.humblebundle.resolver import HumbleResolutionMap, StoreCandidate, StorefrontResolver


DAGON_BASE = "https://store.steampowered.com/app/1481400/Dagon_by_H_P_Lovecraft/"
DAGON_BULLETS = [
    "Dagon - The Eldritch Box DLC",
    "Dagon - The Little Glass Bottle DLC",
    "Dagon - The Railway Horror DLC",
]
# Real description_text of `dyinglight2stayhuman_breckenbundle`
# (archives/humblebundle/bundle/2026-09-30_dying-light-2-stay-human-complete-dlc-bundle/source.json).
BRECKEN_HTML = (
    '<p class="p1">Run, boy, run!</p>\n<strong> The bundle contains: </strong> <br>\n<ul>\n'
    '<li class="p1">Brecken Outfit — lead the way and move swiftly as one of the first runners.</li>\n'
    '<li class="p1">Voltaic Wrench<span class="Apple-converted-space">&nbsp; </span>'
    "— shock your enemies by bashing their heads in.</li>\n"
    "<li class=\"p1\">Brecken’s Paraglider — when running is not enough, fly to your destination.</li>\n</ul>"
)


def _candidate(title: str, appid: str = "1") -> StoreCandidate:
    return StoreCandidate(title=title, url=f"https://store.steampowered.com/app/{appid}/", qualified_id=f"steam:{appid}")
# end def _candidate


def _dlc_item(lists: list[list[str]], base_game_url: str | None = DAGON_BASE) -> HumbleItem:
    return HumbleItem(
        machine_name="dagon_dlcpack",
        title="Dagon DLC Pack",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        tags=["dlc"],
        base_game_url=base_game_url,
        dlc_lists=lists,
        resolution=HumbleResolution(),
    )
# end def _dlc_item


def test_looks_like_prose_accepts_real_titles_and_rejects_descriptions() -> None:
    assert not looks_like_prose("Dagon - The Eldritch Box DLC")
    assert not looks_like_prose("Our Life: Beginnings & Always: Step 1 Expansion")
    assert looks_like_prose("Brecken Outfit — lead the way and move swiftly as one of the first runners.")
# end def test_looks_like_prose_accepts_real_titles_and_rejects_descriptions


def test_brecken_explainer_list_is_no_without_searching() -> None:
    _base, lists = _parse_dlc_pack_details(BRECKEN_HTML)

    def search(_title: str) -> list[StoreCandidate]:
        raise AssertionError("prose must be rejected before any search")
    # end def search

    assert len(lists) == 1
    assert classify_dlc_list(lists[0], None, search) == "no"
# end def test_brecken_explainer_list_is_no_without_searching


def test_dagon_list_is_yes_when_first_bullet_exact_matches_with_a_base_game() -> None:
    assert classify_dlc_list(DAGON_BULLETS, DAGON_BASE, lambda _title: [_candidate(DAGON_BULLETS[0], "9")]) == "yes"
# end def test_dagon_list_is_yes_when_first_bullet_exact_matches_with_a_base_game


def test_list_without_exact_match_or_base_game_is_ask() -> None:
    assert classify_dlc_list(DAGON_BULLETS, DAGON_BASE, lambda _title: [_candidate("Something Else")]) == "ask"
    assert classify_dlc_list(DAGON_BULLETS, None, lambda _title: [_candidate(DAGON_BULLETS[0])]) == "ask"
# end def test_list_without_exact_match_or_base_game_is_ask


def test_ambiguous_list_is_asked_once_per_list_and_cached() -> None:
    asked: list[tuple[str, list[str]]] = []

    def confirm(title: str, bullets: list[str]) -> bool:
        asked.append((title, bullets))
        return True
    # end def confirm

    resolver = StorefrontResolver(
        lambda _url: "", lambda _title, _provider, _candidates, **_kwargs: None, confirm_dlc_list=confirm
    )
    mapping = HumbleResolutionMap(schema=1, games={})
    item = _dlc_item([["Pack Alpha", "Pack Beta"]])

    assert resolver.confirmed_dlc_components(item, mapping) == ["Pack Alpha", "Pack Beta"]
    assert resolver.confirmed_dlc_components(item, mapping) == ["Pack Alpha", "Pack Beta"]

    assert asked == [("Dagon DLC Pack", ["Pack Alpha", "Pack Beta"])]
    assert mapping.dlc_lists == {"dagon_dlcpack::list1": True}
# end def test_ambiguous_list_is_asked_once_per_list_and_cached


def test_each_list_is_decided_on_its_own() -> None:
    answers = iter([False, True])
    resolver = StorefrontResolver(
        lambda _url: "",
        lambda _title, _provider, _candidates, **_kwargs: None,
        confirm_dlc_list=lambda _title, _bullets: next(answers),
    )
    mapping = HumbleResolutionMap(schema=1, games={})

    components = resolver.confirmed_dlc_components(_dlc_item([["Intro One"], ["Real DLC"]]), mapping)

    assert components == ["Real DLC"]
    assert mapping.dlc_lists == {"dagon_dlcpack::list1": False, "dagon_dlcpack::list2": True}
# end def test_each_list_is_decided_on_its_own


def test_default_resolver_answers_no_for_an_ambiguous_list() -> None:
    resolver = StorefrontResolver(lambda _url: "", lambda _title, _provider, _candidates, **_kwargs: None)

    assert resolver.confirmed_dlc_components(_dlc_item([["Pack Alpha"]]), HumbleResolutionMap(schema=1, games={})) == []
# end def test_default_resolver_answers_no_for_an_ambiguous_list


def test_later_undecidable_lists_are_not_asked_after_a_confirmed_list() -> None:
    def confirm(_title: str, _bullets: list[str]) -> bool:
        raise AssertionError("must not prompt for feature bullets after the DLC list")
    # end def confirm

    page = f'<a href="/app/5/">{DAGON_BULLETS[0]}</a>'
    resolver = StorefrontResolver(
        lambda _url: page, lambda _title, _provider, _candidates, **_kwargs: None, confirm_dlc_list=confirm
    )
    item = _dlc_item([DAGON_BULLETS, ["4 different periods of life to experience"]])
    # Searching is stubbed through a fetch that makes the first bullet an exact match.
    resolver.search_steam_safely = lambda _title: [_candidate(DAGON_BULLETS[0], "5")]  # type: ignore[method-assign]

    assert resolver.confirmed_dlc_components(item, HumbleResolutionMap(schema=1, games={})) == DAGON_BULLETS
# end def test_later_undecidable_lists_are_not_asked_after_a_confirmed_list


def test_metadata_migration_wraps_bundled_dlc_names_as_one_list() -> None:
    steps = dict(METADATA_MIGRATIONS)
    data = {"tiers": [{"items": [{"machine_name": "a", "bundled_dlc_names": ["X", "Y"]}, {"machine_name": "b"}]}]}

    migrated = steps[HUMBLE_V3](data)

    items = migrated["tiers"][0]["items"]
    assert items[0] == {"machine_name": "a", "dlc_lists": [["X", "Y"]]}
    assert items[1] == {"machine_name": "b", "dlc_lists": []}
    assert HUMBLE_V2 < HUMBLE_V3
# end def test_metadata_migration_wraps_bundled_dlc_names_as_one_list
