from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.sources.greenmangaming.crawler import (
    CrawledGmgOffer,
    crawl_gmg_offers,
    write_gmg_offer,
)
from game_collections.sources.greenmangaming.models import (
    GmgArchive,
    GmgDates,
    GmgItem,
    GmgPrice,
    GmgResolution,
    GmgTier,
)
from game_collections.sources.greenmangaming.resolver import GmgResolutionMap, StorefrontResolver


def _price(value: float) -> GmgPrice:
    return GmgPrice(raw=f"€{value}", value=value, currency="€", currency_code="EUR")
# end def _price


def _offer() -> CrawledGmgOffer:
    item = GmgItem(
        product_id="343",
        title="Afterimage",
        drm="Steam",
        redeem_on=["steam"],
        resolution=GmgResolution(ids=["steam:1235140"]),
    )
    duplicate = GmgItem(
        product_id="344",
        title="Sample Duplicate",
        drm="Steam",
        redeem_on=["steam"],
        resolution=GmgResolution(ids=["steam:1235140"]),
    )
    archive = GmgArchive(
        schema=1,
        slug="metroidvania-madness",
        url="https://www.greenmangamingbundles.com/bundles/metroidvania-madness/",
        name="METROIDVANIA MADNESS",
        currency_code="EUR",
        dates=GmgDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        tiers=[
            GmgTier(identifier="bronze", name="Bronze", item_count=2, price=_price(8.0), items=[item, duplicate]),
        ],
    )
    return CrawledGmgOffer(archive=archive, source={"zeta": 2, "alpha": 1})
# end def _offer


def test_writer_creates_archive_and_dedupes_shared_steam_ids(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    schema = tmp_path / "schemas/game-list.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}\n", encoding="utf-8")

    paths = write_gmg_offer(_offer(), lists_root, archive_root, tmp_path)

    list_path = lists_root / "greenmangaming/bundle/metroidvania-madness.yml"
    metadata_path = archive_root / "greenmangaming/bundle/metroidvania-madness/metadata.json"
    source_path = archive_root / "greenmangaming/bundle/metroidvania-madness/source.json"
    assert set(paths) == {list_path, metadata_path, source_path}

    loaded = load_game_list(list_path, lists_root)
    assert loaded.data.tiers == []
    assert loaded.data.name == "METROIDVANIA MADNESS — Bronze"
    assert loaded.data.crawlers == ["greenmangaming"]
    assert [(game.name, game.ids) for game in loaded.data.games] == [("Afterimage", ["steam:1235140"])]
    assert [reference.name for reference in loaded.data.references] == [
        "Green Man Gaming bundle",
        "Crawl metadata",
        "Crawl source",
    ]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["slug"] == "metroidvania-madness"
# end def test_writer_creates_archive_and_dedupes_shared_steam_ids


def test_writer_numbers_multiple_tiers(tmp_path: Path) -> None:
    offer = _offer()
    silver_item = GmgItem(
        product_id="345",
        title="Silver Game",
        drm="Steam",
        redeem_on=["steam"],
        resolution=GmgResolution(ids=["steam:9999"]),
    )
    silver_tier = GmgTier(
        identifier="silver", name="Silver", item_count=1, price=_price(12.0), items=[silver_item]
    )
    archive = offer.archive.model_copy(update={"tiers": [*offer.archive.tiers, silver_tier]})
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_gmg_offer(CrawledGmgOffer(archive=archive, source={}), tmp_path / "lists", tmp_path / "archives", tmp_path)

    lists_root = tmp_path / "lists"
    list_path = lists_root / "greenmangaming/bundle/metroidvania-madness.yml"
    assert {path for path in paths if path.suffix == ".yml"} == {list_path}

    loaded = load_game_list(list_path, lists_root)
    assert [tier.rank for tier in loaded.data.tiers] == [1, 2]
    assert loaded.data.name == "METROIDVANIA MADNESS"
    games_by_name = {game.name: game for game in loaded.data.games}
    assert games_by_name["Afterimage"].tiers == [1]
    assert games_by_name["Silver Game"].tiers == [2]
# end def test_writer_numbers_multiple_tiers


def test_writer_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    first = write_gmg_offer(_offer(), tmp_path / "lists", tmp_path / "archives", tmp_path)
    first_contents = {path: path.read_bytes() for path in first}
    second = write_gmg_offer(_offer(), tmp_path / "lists", tmp_path / "archives", tmp_path)

    assert first == second
    assert {path: path.read_bytes() for path in second} == first_contents
# end def test_writer_is_idempotent


def _bundle_item(product_id: str, tier_name: str, title: str) -> str:
    return (
        f'<figure class="bundle-item" hx-get="/bundles/metroidvania-madness/product/{product_id}/" '
        f'hx-vals=\'{{ "display_mode": "unlocked", "tier_name": "{tier_name}"}}\'>'
        f'<strong class="game-title">{title}</strong></figure>'
    )
# end def _bundle_item


def _tier_radio(identifier: str, name: str, item_count: int, price: str) -> str:
    return (
        '<label data-bundle-radio-card class="custom-radio-card">'
        f'<input type="radio" name="amount" data-upgrade-tier-id="{identifier}" value="{identifier}:{price}" />'
        f'<span class="bundle-type">{name}</span><small>{item_count} Items</small>'
        f'<span class="price">€{price}</span></label>'
    )
# end def _tier_radio


BUNDLE_PAGE = (
    '<h1 class="d-none d-xl-block">METROIDVANIA MADNESS</h1>'
    + _bundle_item("343", "Bronze", "Afterimage")
    + '<input type="hidden" name="currency_code" value="EUR" />'
    + _tier_radio("bronze", "Bronze", 1, "8.00")
)

PRODUCT_FRAGMENT = (
    "<dl><dt>DRM</dt><dd>Steam</dd><dt>Platform</dt><dd>Windows</dd></dl>"
    '<section id="gameDescriptionCollapse-343"><p>Afterimage is a Metroidvania.</p></section>'
)

INDEX_PAGE = (
    '<div class="product-grid">'
    '<div class="product-card" data-category="video-games">'
    '<a class="cta-button" href="https://www.greenmangamingbundles.com/bundles/metroidvania-madness/">View</a>'
    "</div></div>"
)

STORE_PAGE = '<a href="https://store.steampowered.com/app/1235140/afterimage/">Afterimage</a>'


def _resolver(page: str = STORE_PAGE) -> StorefrontResolver:
    return StorefrontResolver(lambda _url: page, lambda _item, _provider, _candidates, **_kwargs: None)
# end def _resolver


def test_crawl_discovers_and_resolves_offers_from_index() -> None:
    pages = {
        "https://www.greenmangaming.com/bundles/": INDEX_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/": BUNDLE_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/product/343/": PRODUCT_FRAGMENT,
        "https://store.steampowered.com/search/?term=Afterimage": STORE_PAGE,
    }

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    item = report.offers[0].archive.tiers[0].items[0]
    assert item.drm == "Steam"
    assert item.resolution.ids == ["steam:1235140"]
# end def test_crawl_discovers_and_resolves_offers_from_index


def test_crawl_isolates_per_offer_failures() -> None:
    def fetch(url: str) -> str:
        if url.endswith("metroidvania-madness/"):
            raise ValueError("boom")
        # end if
        return INDEX_PAGE
    # end def fetch

    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.offers == ()
    assert len(report.errors) == 1
    assert "boom" in report.errors[0]
# end def test_crawl_isolates_per_offer_failures


def test_crawl_explicit_url_skips_index_discovery() -> None:
    pages = {
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/": BUNDLE_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/product/343/": PRODUCT_FRAGMENT,
        "https://store.steampowered.com/search/?term=Afterimage": STORE_PAGE,
    }

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        urls=["https://www.greenmangamingbundles.com/bundles/metroidvania-madness/"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert len(report.offers) == 1
# end def test_crawl_explicit_url_skips_index_discovery


def test_crawl_skips_fetch_entirely_for_a_cached_bundle(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    write_gmg_offer(_offer(), tmp_path / "lists", archive_root, tmp_path)

    def fetch(url: str) -> str:
        raise AssertionError(f"fetch should not be called for a cached bundle: {url}")
    # end def fetch

    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        urls=["https://www.greenmangamingbundles.com/bundles/metroidvania-madness/"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        archive_root=archive_root,
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert report.offers[0].archive == _offer().archive
# end def test_crawl_skips_fetch_entirely_for_a_cached_bundle


def test_crawl_refetches_when_cached_schema_is_stale(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    write_gmg_offer(_offer(), tmp_path / "lists", archive_root, tmp_path)
    metadata_path = archive_root / "greenmangaming/bundle/metroidvania-madness/metadata.json"
    metadata_path.write_text(
        metadata_path.read_text(encoding="utf-8").replace('"schema": 1', '"schema": 2'),
        encoding="utf-8",
    )
    pages = {
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/": BUNDLE_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/product/343/": PRODUCT_FRAGMENT,
        "https://store.steampowered.com/search/?term=Afterimage": STORE_PAGE,
    }
    fetched: list[str] = []

    def fetch(url: str) -> str:
        fetched.append(url)
        return pages[url]
    # end def fetch

    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        urls=["https://www.greenmangamingbundles.com/bundles/metroidvania-madness/"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        archive_root=archive_root,
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert fetched  # the stale cache was ignored and a real fetch happened
# end def test_crawl_refetches_when_cached_schema_is_stale


def test_crawl_logs_progress_and_invokes_on_offer_per_bundle() -> None:
    pages = {
        "https://www.greenmangaming.com/bundles/": INDEX_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/": BUNDLE_PAGE,
        "https://www.greenmangamingbundles.com/bundles/metroidvania-madness/product/343/": PRODUCT_FRAGMENT,
        "https://store.steampowered.com/search/?term=Afterimage": STORE_PAGE,
    }

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    messages: list[str] = []
    offers: list[CrawledGmgOffer] = []
    report = crawl_gmg_offers(
        fetch,
        _resolver(),
        GmgResolutionMap(schema=1, games={}),
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        log=messages.append,
        on_offer=offers.append,
    )

    assert any("Bundle 1/1: metroidvania-madness" in message for message in messages)
    assert any("Game 1/1" in message for message in messages)
    assert offers == list(report.offers)
# end def test_crawl_logs_progress_and_invokes_on_offer_per_bundle
