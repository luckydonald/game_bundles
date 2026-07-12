from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from game_collections.sources.greenmangaming.models import GmgArchive, GmgDates, GmgItem, GmgResolution, GmgTier
from game_collections.sources.greenmangaming.resolver import (
    GmgResolutionMap,
    StoreCandidate,
    StorefrontResolver,
    load_resolution_map,
    redeem_on_for_drm,
    render_resolution_map,
)


def _item(product_id: str = "346") -> GmgItem:
    return GmgItem(
        product_id=product_id,
        title="Sample Game™",
        drm="Steam",
        redeem_on=["steam"],
        resolution=GmgResolution(),
    )
# end def _item


def _archive(item: GmgItem) -> GmgArchive:
    return GmgArchive(
        schema=1,
        slug="sample-bundle",
        url="https://www.greenmangamingbundles.com/bundles/sample-bundle/",
        name="Sample Bundle",
        currency_code="EUR",
        dates=GmgDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        tiers=[
            GmgTier(
                identifier="bronze",
                name="Bronze",
                item_count=1,
                items=[item],
            )
        ],
    )
# end def _archive


def test_redeem_on_for_drm_maps_known_and_unknown_values() -> None:
    assert redeem_on_for_drm("Steam") == ["steam"]
    assert redeem_on_for_drm("GOG") == ["gog"]
    assert redeem_on_for_drm("Uplay") == ["ubisoft"]
    assert redeem_on_for_drm("Some Unknown DRM") == []
    assert redeem_on_for_drm(None) == []
# end def test_redeem_on_for_drm_maps_known_and_unknown_values


def test_unique_exact_match_is_accepted_without_prompt() -> None:
    page = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'
    prompted = False

    def choose(_item: GmgItem, _provider: str, _candidates: list[StoreCandidate]) -> str | None:
        nonlocal prompted
        prompted = True
        return None
    # end def choose

    resolver = StorefrontResolver(lambda _url: page, choose)
    mapping = GmgResolutionMap(schema=1, games={})

    resolved = resolver.resolve_archive(_archive(_item()), mapping)

    assert prompted is False
    assert resolved.tiers[0].items[0].resolution.ids == ["steam:42"]
    assert mapping.games == {"346": ["steam:42"]}
# end def test_unique_exact_match_is_accepted_without_prompt


def test_resolve_archive_logs_progress_per_distinct_game() -> None:
    page = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'
    resolver = StorefrontResolver(lambda _url: page, lambda _item, _provider, _candidates: None)
    messages: list[str] = []

    resolver.resolve_archive(_archive(_item()), GmgResolutionMap(schema=1, games={}), log=messages.append)

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

    ids = resolver.resolve_item(_item(), GmgResolutionMap(schema=1, games={}))

    assert ids == ["steam:43"]
# end def test_ambiguous_match_uses_selected_url


def test_blank_selection_persists_unresolved_fallback() -> None:
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates: None)
    mapping = GmgResolutionMap(schema=1, games={})

    ids = resolver.resolve_item(_item(), mapping)

    assert ids == ["unresolved:source:greenmangaming:346"]
    assert mapping.games == {"346": ids}
# end def test_blank_selection_persists_unresolved_fallback


def test_unrecognized_drm_skips_search_and_is_unresolved() -> None:
    item = GmgItem(product_id="9", title="Mystery Game", drm="Standalone Installer", redeem_on=[])
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates: None)

    ids = resolver.resolve_item(item, GmgResolutionMap(schema=1, games={}))

    assert ids == ["unresolved:source:greenmangaming:9"]
# end def test_unrecognized_drm_skips_search_and_is_unresolved


def test_resolution_map_round_trip_is_sorted(tmp_path: Path) -> None:
    mapping = GmgResolutionMap(
        schema=1,
        games={"9": ["steam:2"], "1": ["gog:alpha"]},
    )
    rendered = render_resolution_map(mapping)
    path = tmp_path / "map.yml"
    path.write_text(rendered, encoding="utf-8")

    assert rendered.index("'1':") < rendered.index("'9':")
    assert load_resolution_map(path) == mapping
# end def test_resolution_map_round_trip_is_sorted
