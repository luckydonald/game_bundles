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

    def choose(_item: GmgItem, _provider: str, _candidates: list[StoreCandidate], **_kwargs: object) -> str | None:
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
    resolver = StorefrontResolver(lambda _url: page, lambda _item, _provider, _candidates, **_kwargs: None)
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
        lambda _item, _provider, candidates, **_kwargs: candidates[1].url,
    )

    ids = resolver.resolve_item(_item(), GmgResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["steam:43"]
# end def test_ambiguous_match_uses_selected_url


def test_blank_selection_persists_unresolved_fallback() -> None:
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates, **_kwargs: None)
    mapping = GmgResolutionMap(schema=1, games={})

    ids = resolver.resolve_item(_item(), mapping)[0].ids

    assert ids == ["unresolved:source:greenmangaming:346"]
    assert mapping.games == {"346": ids}
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

    ids = resolver.resolve_item(_item(), GmgResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["steam:42"]
    assert steamdb_called is False
# end def test_unique_steampowered_match_skips_steamdb_fallback


def test_ambiguous_steampowered_match_falls_back_to_steamdb() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    steamdb_page = '<a href="/app/3011360/">Sample Game</a>'

    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates, **_kwargs: None,
        steamdb_fetch=lambda _url: steamdb_page,
    )

    ids = resolver.resolve_item(_item(), GmgResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["steam:3011360"]
# end def test_ambiguous_steampowered_match_falls_back_to_steamdb


def test_no_steamdb_fetch_behaves_like_steampowered_only() -> None:
    steampowered_page = """
    <a href="https://store.steampowered.com/app/1/other/">Other Game</a>
    <a href="https://store.steampowered.com/app/2/other/">Other Game</a>
    """
    resolver = StorefrontResolver(
        lambda _url: steampowered_page,
        lambda _item, _provider, _candidates, **_kwargs: None,
    )

    ids = resolver.resolve_item(_item(), GmgResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["unresolved:source:greenmangaming:346"]
# end def test_no_steamdb_fetch_behaves_like_steampowered_only


def test_unrecognized_drm_skips_search_and_is_unresolved() -> None:
    item = GmgItem(product_id="9", title="Mystery Game", drm="Standalone Installer", redeem_on=[])
    resolver = StorefrontResolver(lambda _url: "", lambda _item, _provider, _candidates, **_kwargs: None)

    ids = resolver.resolve_item(item, GmgResolutionMap(schema=1, games={}))[0].ids

    assert ids == ["unresolved:source:greenmangaming:9"]
# end def test_unrecognized_drm_skips_search_and_is_unresolved


def test_resolve_archive_known_names_excludes_current_item_but_includes_others() -> None:
    """`known_names` passed to `choose` must exclude the item being resolved (so accepting the
    "Multiple…" default, which is the item's own title, isn't rejected as a self-collision) but
    include every other distinct item's title (so a name colliding with one is caught live -
    see `ai/errors/5.txt`, where "Destiny 2: The Edge of Fate" was re-typed as a split name for a
    different item in the same bundle and only failed much later, at final GameList validation).
    """
    seen: list[set[str] | None] = []

    def choose(
        _item: GmgItem, _provider: str, _candidates: list[StoreCandidate], known_names: set[str] | None = None,
        **_kwargs: object,
    ) -> str | None:
        seen.append(set(known_names) if known_names is not None else None)
        return None
    # end def choose

    ambiguous_page = """
    <a href="https://store.steampowered.com/app/1/game/">Ambiguous</a>
    <a href="https://store.steampowered.com/app/2/game/">Ambiguous</a>
    """
    item_a = GmgItem(product_id="1", title="Alpha", drm="Steam", redeem_on=["steam"], resolution=GmgResolution())
    item_b = GmgItem(product_id="2", title="Beta", drm="Steam", redeem_on=["steam"], resolution=GmgResolution())
    archive = GmgArchive(
        schema=1,
        slug="sample-bundle",
        url="https://www.greenmangamingbundles.com/bundles/sample-bundle/",
        name="Sample Bundle",
        currency_code="EUR",
        dates=GmgDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        tiers=[GmgTier(identifier="bronze", name="Bronze", item_count=2, items=[item_a, item_b])],
    )
    resolver = StorefrontResolver(lambda _url: ambiguous_page, choose)

    resolver.resolve_archive(archive, GmgResolutionMap(schema=1, games={}))

    assert seen[0] is not None and "alpha" not in seen[0] and "beta" in seen[0]
    assert seen[1] is not None and "beta" not in seen[1] and "alpha" in seen[1]
# end def test_resolve_archive_known_names_excludes_current_item_but_includes_others


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
