from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.models import Game
from game_collections.sources.isthereanydeal.crawler import (
    CrawledItadOffer,
    crawl_itad_offers,
    write_itad_offer,
)
from game_collections.sources.isthereanydeal.models import ItadArchive, ItadDates, ItadItem, ItadPrice, ItadTier
from game_collections.sources.isthereanydeal.parser import parse_list_page
from game_collections.sources.isthereanydeal.provider_config import ItadProviderConfig, ItadProviderMapping


def _summary(bundle_id: int = 1, byob: bool = False, is_mature: bool = False, title: str = "Metroidvania Madness") -> dict:
    return {
        "id": bundle_id,
        "title": title,
        "page": {"id": 73, "name": "GreenManGaming", "shopId": 36},
        "url": (
            "https://greenmangaming.sjv.io/c/x?u=https%3A%2F%2F"
            "www.greenmangamingbundles.com%2Fbundles%2Fmetroidvania-madness%2F"
        ),
        "isMature": is_mature,
        "isPending": False,
        "start": 1783715387,
        "expiry": 1785556800,
        "counts": {"games": 1, "media": 0, "waitlist": 0, "collection": 0, "comments": 0},
        "byob": byob,
        "tiers": [],
    }
# end def _summary


def _game_block(slug: str, title: str, appid: int) -> str:
    return f"""
    <div class="item svelte-16sk5um">
      <a href="/game/{slug}/info/" class="button svelte-16sk5um">
        <span class="game-title">{title}</span>
      </a>
      <div class="reviews svelte-lul36k">
        <a href="https://store.steampowered.com/app/{appid}/" class="simple">reviews</a>
      </div>
    </div>
    """
# end def _game_block


DETAIL_PAGE = f"""
<div class="tier-name svelte-1bcxd10"><div class="name svelte-1bcxd10">Tier 1</div></div>
<div class="values svelte-1bcxd10"><div>Price</div> <div class="value__price svelte-1lak40z">8,00 €</div></div>
<div class="tier tier--cards svelte-1bcxd10">{_game_block("grime", "GRIME", 1123050)}</div>
"""

DEFAULT_PROVIDER_CONFIG = ItadProviderConfig(
    schema=1,
    providers={"73": ItadProviderMapping(name="GreenManGaming", slug="greenmangaming")},
)


def _list_page_of(*summaries: dict):
    def list_page(tab: str, offset: int) -> tuple[bool, list]:
        if offset > 0:
            return True, []
        # end if
        _done, parsed = parse_list_page({"done": True, "data": list(summaries)})
        return True, parsed
    # end def list_page
    return list_page
# end def _list_page_of


def test_crawl_discovers_and_normalizes_offer_from_list_and_detail() -> None:
    pages = {"https://isthereanydeal.com/bundles/1/": DETAIL_PAGE}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    archive = report.offers[0].archive
    assert archive.provider_slug == "greenmangaming"
    assert archive.real_slug == "metroidvania-madness"
    assert archive.tiers[0].items[0].ids == ["steam:1123050", "isthereanydeal:grime"]
# end def test_crawl_discovers_and_normalizes_offer_from_list_and_detail


def test_crawl_fully_parses_mature_bundles() -> None:
    """The mature-content gate is purely visual - the detail page's own data isn't hidden."""
    pages = {"https://isthereanydeal.com/bundles/1/": DETAIL_PAGE}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary(is_mature=True)),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert report.offers[0].archive.tiers[0].items[0].ids == ["steam:1123050", "isthereanydeal:grime"]
# end def test_crawl_fully_parses_mature_bundles


def _json_detail_page(live_data: dict) -> str:
    page_json = json.dumps(["Bundle", {"liveData": live_data}])
    return '<html><script>var g = {"shops": {}, "token": "tok"}; ' f"var page = {page_json};</script></html>"
# end def _json_detail_page


def test_crawl_falls_back_to_html_parsing_and_logs_when_no_embedded_data() -> None:
    pages = {"https://isthereanydeal.com/bundles/1/": DETAIL_PAGE}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    messages: list[str] = []
    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        log=messages.append,
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert any("falling back to HTML parsing" in message for message in messages)
# end def test_crawl_falls_back_to_html_parsing_and_logs_when_no_embedded_data


def test_crawl_prefers_embedded_json_over_html_fallback() -> None:
    live_data = {
        "tiers": [
            {
                "price": [999, "EUR"],
                "addon": False,
                "note": "Gold",
                "games": [
                    {
                        "slug": "grime",
                        "title": "GRIME",
                        "reviews": [{"source": "Steam", "url": "https://store.steampowered.com/app/1123050/"}],
                        "keys": [61],
                    }
                ],
            }
        ]
    }
    pages = {"https://isthereanydeal.com/bundles/1/": _json_detail_page(live_data)}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    archive = report.offers[0].archive
    assert archive.tiers[0].name == "Gold"
    assert archive.tiers[0].price is not None
    assert archive.tiers[0].price.value == 9.99
# end def test_crawl_prefers_embedded_json_over_html_fallback


def test_crawl_records_error_when_both_parse_paths_fail() -> None:
    pages = {"https://isthereanydeal.com/bundles/1/": "<html>nothing here at all</html>"}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.offers == ()
    assert len(report.errors) == 1
# end def test_crawl_records_error_when_both_parse_paths_fail


def test_crawl_isolates_per_bundle_failures() -> None:
    def fetch(url: str) -> str:
        raise ValueError("boom")
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.offers == ()
    assert len(report.errors) == 1
    assert "boom" in report.errors[0]
# end def test_crawl_isolates_per_bundle_failures


def test_crawl_falls_back_to_slugified_name_for_unreviewed_provider() -> None:
    pages = {"https://isthereanydeal.com/bundles/1/": DETAIL_PAGE}

    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    empty_config = ItadProviderConfig(schema=1, providers={})
    messages: list[str] = []
    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        empty_config,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        log=messages.append,
    )

    assert report.errors == ()
    assert report.offers[0].archive.provider_slug == "greenmangaming"
    assert any("unreviewed ITAD provider" in message for message in messages)
# end def test_crawl_falls_back_to_slugified_name_for_unreviewed_provider


def _offer(bundle_id: int = 1) -> CrawledItadOffer:
    archive = ItadArchive(
        schema=1,
        id=bundle_id,
        title="Metroidvania Madness",
        provider_name="GreenManGaming",
        provider_slug="greenmangaming",
        real_slug="metroidvania-madness",
        url=f"https://isthereanydeal.com/bundles/{bundle_id}/",
        dates=ItadDates(start=datetime(2026, 7, 10, tzinfo=UTC), crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        tiers=[
            ItadTier(
                identifier="tier-1",
                name="Tier 1",
                item_count=1,
                price=ItadPrice(raw="8,00 €", value=8.0, currency="€"),
                items=[ItadItem(slug="grime", title="GRIME", ids=["steam:1123050"])],
            )
        ],
    )
    _done, summaries = parse_list_page({"done": True, "data": [_summary(bundle_id=bundle_id)]})
    return CrawledItadOffer(archive=archive, summary=summaries[0])
# end def _offer


def test_write_itad_offer_creates_archive_and_list(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_itad_offer(_offer(), lists_root, archive_root, tmp_path)

    metadata_path = archive_root / "isthereanydeal/bundle/1/metadata.json"
    source_path = archive_root / "isthereanydeal/bundle/1/source.json"
    list_path = lists_root / "greenmangaming/bundle/2026-07-10_metroidvania-madness/tier-1.yml"
    assert set(paths) == {metadata_path, source_path, list_path}

    loaded = load_game_list(list_path, lists_root)
    assert loaded.data.games == [Game(name="GRIME", ids=["steam:1123050"])]
    source = json.loads(source_path.read_text(encoding="utf-8"))
    assert source["title"] == "Metroidvania Madness"
    assert "tiers" not in source
# end def test_write_itad_offer_creates_archive_and_list


def test_write_itad_offer_skips_list_when_already_covered(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")
    existing = lists_root / "greenmangaming/bundle/metroidvania-madness/gold.yml"
    existing.parent.mkdir(parents=True)
    existing.write_text("schema: 1\nname: existing\ngames: []\n", encoding="utf-8")

    messages: list[str] = []
    paths = write_itad_offer(_offer(), lists_root, archive_root, tmp_path, log=messages.append)

    metadata_path = archive_root / "isthereanydeal/bundle/1/metadata.json"
    source_path = archive_root / "isthereanydeal/bundle/1/source.json"
    assert set(paths) == {metadata_path, source_path}
    assert any("Skipped metroidvania-madness" in message for message in messages)
# end def test_write_itad_offer_skips_list_when_already_covered


def test_write_itad_offer_skips_humble_choice_by_month_not_slug(tmp_path: Path) -> None:
    """Humble Choice lists live at `choice/<YYYY-MM>.yml`, sharing no slug text
    with ITAD's "Humble Choice <Month> <Year>" title - dedup must special-case it."""
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")
    choice_path = lists_root / "humblebundle/choice/2026-07.yml"
    choice_path.parent.mkdir(parents=True)
    choice_path.write_text("schema: 1\nname: existing\ngames: []\n", encoding="utf-8")

    offer = _offer()
    offer = CrawledItadOffer(
        archive=offer.archive.model_copy(update={"provider_slug": "humblebundle", "real_slug": "july-2026"}),
        summary=offer.summary.model_copy(update={"title": "Humble Choice July 2026"}),
    )
    messages: list[str] = []
    paths = write_itad_offer(offer, lists_root, archive_root, tmp_path, log=messages.append)

    metadata_path = archive_root / "isthereanydeal/bundle/1/metadata.json"
    source_path = archive_root / "isthereanydeal/bundle/1/source.json"
    assert set(paths) == {metadata_path, source_path}
    assert any("choice/2026-07.yml" in message for message in messages)
# end def test_write_itad_offer_skips_humble_choice_by_month_not_slug


def test_crawl_skips_fetch_entirely_for_a_cached_bundle(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    write_itad_offer(_offer(), tmp_path / "lists", archive_root, tmp_path)

    def fetch(url: str) -> str:
        raise AssertionError(f"fetch should not be called for a cached bundle: {url}")
    # end def fetch

    report = crawl_itad_offers(
        fetch,
        _list_page_of(_summary()),
        DEFAULT_PROVIDER_CONFIG,
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        archive_root=archive_root,
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert report.offers[0].archive == _offer().archive
# end def test_crawl_skips_fetch_entirely_for_a_cached_bundle
