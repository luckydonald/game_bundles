from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from game_collections.sources.dekudeals.parser import (
    DekuParseError,
    bundle_slug,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_item_page,
)


def _inertia_page(props: dict[str, object]) -> str:
    payload = {"component": "BundleShow", "props": props, "url": "/x", "version": "1", "onceProps": {}}
    encoded = html.escape(json.dumps(payload), quote=True)
    return f'<html><body><div id="inertia-app" data-page="{encoded}"><div>rendered</div></div></body></html>'
# end def _inertia_page


def test_bundle_index_returns_distinct_slugs_in_order() -> None:
    html_text = _inertia_page(
        {
            "bundles": [
                {"slug": "crawling-through-the-dungeons", "name": "Crawling", "created_at": 1788977421},
                {"slug": "build-your-own-killer-bundle", "name": "Killer", "created_at": None},
                {"slug": "crawling-through-the-dungeons", "name": "Crawling (dup)", "created_at": 1},
            ]
        }
    )

    entries = parse_bundle_index_page(html_text)

    assert [entry.slug for entry in entries] == [
        "crawling-through-the-dungeons",
        "build-your-own-killer-bundle",
    ]
    assert entries[0].created_at == datetime(2026, 9, 9, 18, 10, 21, tzinfo=UTC)
    assert entries[1].created_at is None
# end def test_bundle_index_returns_distinct_slugs_in_order


def test_bundle_index_requires_inertia_data() -> None:
    try:
        parse_bundle_index_page("<html></html>")
    except DekuParseError:
        return
    # end try
    raise AssertionError("expected DekuParseError")
# end def test_bundle_index_requires_inertia_data


def test_bundle_index_requires_a_bundles_list() -> None:
    try:
        parse_bundle_index_page(_inertia_page({"bundles": []}))
    except DekuParseError:
        return
    # end try
    raise AssertionError("expected DekuParseError")
# end def test_bundle_index_requires_a_bundles_list


def _price_tier_bundle() -> dict[str, object]:
    return {
        "bundle": {
            "slug": "crawling-through-the-dungeons",
            "name": "Crawling Through the Dungeons",
            "state": "published",
            "tiering_style": "price_per_tier",
            "store_name": "Humble",
            "ends_at": 1790827200,
            "ends_at_label": "Ends October 1",
            "url": "https://humblebundleinc.sjv.io/c/x?u=https%3A%2F%2Fwww.humblebundle.com%2Fgames%2Fcrawling",
        },
        "tiers": [
            {"id": 1367, "price": 1023, "price_formatted": "€10,23"},
            {"id": 1368, "price": 1432, "price_formatted": "€14,32"},
        ],
        "items": [
            {"name": "Crawl", "slug": "crawl", "platform": "steam", "tiers": [1367, 1368]},
            {"name": "The Bard's Tale Trilogy", "slug": "the-bards-tale-trilogy", "platform": "steam", "tiers": [1368]},
        ],
    }
# end def _price_tier_bundle


def test_bundle_page_parses_price_per_tier_bundle() -> None:
    url = "https://www.dekudeals.com/bundles/crawling-through-the-dungeons"
    draft, props = parse_bundle_page(_inertia_page(_price_tier_bundle()), url)

    assert draft.machine_name == "crawling-through-the-dungeons"
    assert draft.name == "Crawling Through the Dungeons"
    assert draft.store_name == "Humble"
    assert draft.tiering_style == "price_per_tier"
    assert draft.real_url is not None and "humblebundle.com" in draft.real_url
    assert draft.end is not None and draft.end.year == 2026
    assert [(tier.identifier, tier.price.raw if tier.price else None) for tier in draft.tiers] == [
        ("1367", "€10,23"),
        ("1368", "€14,32"),
    ]
    assert [(item.slug, item.tier_ids) for item in draft.items] == [
        ("crawl", (1367, 1368)),
        ("the-bards-tale-trilogy", (1368,)),
    ]
    assert props["bundle"]["slug"] == "crawling-through-the-dungeons"
# end def test_bundle_page_parses_price_per_tier_bundle


def test_bundle_page_parses_price_per_item_byob_bundle() -> None:
    props = {
        "bundle": {
            "slug": "build-your-own-killer-bundle",
            "name": "Build your own Killer Bundle",
            "state": "published",
            "tiering_style": "price_per_item",
            "store_name": "Fanatical",
            "ends_at": None,
            "url": "https://www.fanatical.com/en/pick-and-mix/build-your-own-killer-bundle",
        },
        "tiers": [
            {"id": 1355, "price": 120, "item_minimum": 5, "price_formatted": "€1,20"},
            {"id": 1356, "price": 100, "item_minimum": 10, "price_formatted": "€1,00"},
        ],
        "items": [
            {"name": "Rain World", "slug": "rain-world", "platform": "steam", "tiers": []},
        ],
    }
    url = "https://www.dekudeals.com/bundles/build-your-own-killer-bundle"

    draft, _source = parse_bundle_page(_inertia_page(props), url)

    assert draft.tiering_style == "price_per_item"
    assert [(tier.identifier, tier.item_minimum) for tier in draft.tiers] == [("1355", 5), ("1356", 10)]
    assert draft.end is None
# end def test_bundle_page_parses_price_per_item_byob_bundle


def test_bundle_page_rejects_unrecognized_tiering_style() -> None:
    props = _price_tier_bundle()
    props["bundle"]["tiering_style"] = "something_new"
    try:
        parse_bundle_page(_inertia_page(props), "https://www.dekudeals.com/bundles/x")
    except DekuParseError:
        return
    # end try
    raise AssertionError("expected DekuParseError")
# end def test_bundle_page_rejects_unrecognized_tiering_style


def test_bundle_slug_parses_full_and_relative_urls() -> None:
    assert bundle_slug("https://www.dekudeals.com/bundles/foo-bar") == "foo-bar"
    assert bundle_slug("/bundles/foo-bar") == "foo-bar"
# end def test_bundle_slug_parses_full_and_relative_urls


def test_bundle_slug_rejects_non_bundle_url() -> None:
    try:
        bundle_slug("https://www.dekudeals.com/items/foo-bar")
    except DekuParseError:
        return
    # end try
    raise AssertionError("expected DekuParseError")
# end def test_bundle_slug_rejects_non_bundle_url


def _item_row(analytics_id: str, href: str) -> str:
    return (
        f"<script>outAnalytics['{analytics_id}'] = {{}}</script>"
        f"<tr><td><a data-out-analytics-id='{analytics_id}' href='{href}' target='_blank'>logo</a></td>"
        f"<td><a data-out-analytics-id='{analytics_id}' href='{href}' target='_blank'>version</a></td>"
        f"<td><a data-out-analytics-id='{analytics_id}' href='{href}' target='_blank'>price</a></td></tr>"
    )
# end def _item_row


def test_item_page_returns_distinct_store_urls_in_order() -> None:
    url = "https://www.dekudeals.com/items/dungeon-drafters?platform=all"
    html_text = (
        "<html><body>"
        + _item_row("eshop_de:1", "https://www.nintendo.com/de-de/Games/Game-1.html")
        + _item_row("steam_de:package:2", "https://store.steampowered.com/app/1824580/Dungeon_Drafters?utm_source=dekudeals")
        + _item_row("amazon_de:3", "https://www.amazon.de/Dungeon-Drafters/dp/B0DMT96JFG?tag=deku0ba-21&amp;ref=x")
        + "</body></html>"
    )

    urls = parse_item_page(html_text, url)

    assert urls == [
        "https://www.nintendo.com/de-de/Games/Game-1.html",
        "https://store.steampowered.com/app/1824580/Dungeon_Drafters?utm_source=dekudeals",
        "https://www.amazon.de/Dungeon-Drafters/dp/B0DMT96JFG?tag=deku0ba-21&ref=x",
    ]
# end def test_item_page_returns_distinct_store_urls_in_order


def test_item_page_requires_at_least_one_store_link() -> None:
    try:
        parse_item_page("<html>no stores here</html>", "https://www.dekudeals.com/items/x")
    except DekuParseError:
        return
    # end try
    raise AssertionError("expected DekuParseError")
# end def test_item_page_requires_at_least_one_store_link
