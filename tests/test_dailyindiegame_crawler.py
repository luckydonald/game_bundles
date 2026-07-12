from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.sources.dailyindiegame.crawler import (
    CrawledDigOffer,
    crawl_dig_offers,
    write_dig_offer,
)
from game_collections.sources.dailyindiegame.models import (
    DigArchive,
    DigDates,
    DigItem,
    DigPrice,
)


def _price(value: float) -> DigPrice:
    return DigPrice(raw=f"${value}", value=value, currency="$", currency_code="USD")
# end def _price


def _offer() -> CrawledDigOffer:
    archive = DigArchive(
        schema=1,
        machine_name="2351",
        url="https://www.dailyindiegame.com/site_weeklybundle_2351.html",
        name="DIG Bundle 2351 - ADULT",
        is_adult=True,
        dates=DigDates(
            end=datetime(2026, 8, 1, 3, 9, 13, tzinfo=UTC),
            crawled=datetime(2026, 7, 12, tzinfo=UTC),
        ),
        game_count=2,
        total_value=_price(105.91),
        bundle_price=_price(0.99),
        savings_percent=100,
        savings_amount=_price(104.92),
        items=[
            DigItem(
                title="The Office: Dirty Affairs",
                ids=["steam:4543360"],
                url="https://store.steampowered.com/app/4543360",
            ),
            DigItem(
                title="Sample Duplicate",
                ids=["steam:4543360"],
                url="https://store.steampowered.com/app/4543360",
            ),
        ],
    )
    return CrawledDigOffer(archive=archive, source={"zeta": 2, "alpha": 1})
# end def _offer


def test_writer_creates_archive_and_dedupes_shared_steam_ids(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    schema = tmp_path / "schemas/game-list.schema.json"
    schema.parent.mkdir(parents=True)
    schema.write_text("{}\n", encoding="utf-8")

    paths = write_dig_offer(_offer(), lists_root, archive_root, tmp_path)

    bundle_root = "dailyindiegame/bundle"
    list_path = lists_root / bundle_root / "2351.yml"
    metadata_path = archive_root / bundle_root / "2351/metadata.json"
    source_path = archive_root / bundle_root / "2351/source.json"
    assert set(paths) == {list_path, metadata_path, source_path}

    loaded = load_game_list(list_path, lists_root)
    assert loaded.data.name == "DIG Bundle 2351 - ADULT"
    assert [(game.name, game.ids) for game in loaded.data.games] == [
        ("The Office: Dirty Affairs", ["steam:4543360"])
    ]
    assert [reference.name for reference in loaded.data.references] == [
        "DailyIndieGame bundle",
        "Crawl metadata",
        "Crawl source",
    ]
    assert str(loaded.data.references[0].url) == "https://www.dailyindiegame.com/site_weeklybundle_2351.html"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["machine_name"] == "2351"
    assert source_path.read_text(encoding="utf-8").startswith('{\n  "alpha": 1,')
# end def test_writer_creates_archive_and_dedupes_shared_steam_ids


def test_writer_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    first = write_dig_offer(_offer(), tmp_path / "lists", tmp_path / "archives", tmp_path)
    first_contents = {path: path.read_bytes() for path in first}
    second = write_dig_offer(_offer(), tmp_path / "lists", tmp_path / "archives", tmp_path)

    assert first == second
    assert {path: path.read_bytes() for path in second} == first_contents
# end def test_writer_is_idempotent


BUNDLE_PAGE = """
<table><tr><td><span class="DIG-contentOrangeBIG">DIG Bundle 2351 - ADULT</span></td></tr></table>
<div id="countdown">Bundle ends in 20 days : 03 : 09 : 13</div>
<table><tr><td>
9 awesome STEAM games , worth a total of $105.91. Grab them now for only $0.99 and save 100% ($104.92)
</td></tr></table>
<table><tr>
<td>The Office: Dirty Affairs<br><br>
<a href="https://store.steampowered.com/app/4543360">view on STEAM</a><br><br>
<a href="site_gamelisting_4543360.html"></a></td>
</tr></table>
"""

GAME_LISTING_PAGE = """
<table><tr><td>The Office: Dirty Affairs $7.99 ( $7.99 ) You save: $0.00 (0%)Region: WORLDWIDE
VIEW STEAM PAGE Step into the world of high stakes corporate ambition.
<img src="dig3-images-steam/4543360.jpg"></td></tr></table>
"""

INDEX_PAGE = """
<table><tr><td><a href="site_weeklybundle_2351.html"><img src="a.png"></a></td></tr></table>
"""


def test_crawl_discovers_and_enriches_offers_from_index() -> None:
    pages = {
        "https://www.dailyindiegame.com/site_content_bundles.html": INDEX_PAGE,
        "https://www.dailyindiegame.com/site_weeklybundle_2351.html": BUNDLE_PAGE,
        "https://www.dailyindiegame.com/site_gamelisting_4543360.html": GAME_LISTING_PAGE,
    }

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_dig_offers(fetch, crawled=datetime(2026, 7, 12, tzinfo=UTC))

    assert report.errors == ()
    assert len(report.offers) == 1
    item = report.offers[0].archive.items[0]
    assert item.individual_price.value == 7.99
    assert item.region == "WORLDWIDE"
    assert str(item.cover_art_url) == "https://www.dailyindiegame.com/dig3-images-steam/4543360.jpg"
# end def test_crawl_discovers_and_enriches_offers_from_index


def test_crawl_isolates_per_offer_failures() -> None:
    def fetch(url: str) -> str:
        if url.endswith("site_weeklybundle_2351.html"):
            raise ValueError("boom")
        # end if
        return INDEX_PAGE
    # end def fetch

    report = crawl_dig_offers(fetch, crawled=datetime(2026, 7, 12, tzinfo=UTC))

    assert report.offers == ()
    assert len(report.errors) == 1
    assert "boom" in report.errors[0]
# end def test_crawl_isolates_per_offer_failures


def test_crawl_explicit_url_skips_index_discovery() -> None:
    pages = {
        "https://www.dailyindiegame.com/site_weeklybundle_2351.html": BUNDLE_PAGE,
        "https://www.dailyindiegame.com/site_gamelisting_4543360.html": GAME_LISTING_PAGE,
    }

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_dig_offers(
        fetch,
        urls=["https://www.dailyindiegame.com/site_weeklybundle_2351.html"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert len(report.offers) == 1
# end def test_crawl_explicit_url_skips_index_discovery
