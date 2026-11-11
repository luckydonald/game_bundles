"""Humble Bundle's Next.js pages, against trimmed copies of the real pages saved on 2026-11-11."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from game_collections.sources.humblebundle.crawler import build_offer_archive
from game_collections.sources.humblebundle.nextjs import (
    extract_bundle_payload_nextjs,
    extract_choice_payload_nextjs,
    is_nextjs_page,
    parse_bundle_index_nextjs,
)
from game_collections.sources.humblebundle.parser import HumbleParseError


FIXTURES = Path(__file__).parent / "fixtures" / "humblebundle"
CRAWLED = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
# end def fixture


def test_is_nextjs_page() -> None:
    assert is_nextjs_page(fixture("bundles-index.html"))
    assert not is_nextjs_page('<script id="landingPage-json-data" type="application/json">{}</script>')
# end def test_is_nextjs_page


def test_bundle_index_lists_games_bundles() -> None:
    products = parse_bundle_index_nextjs(fixture("bundles-index.html"))

    urls = [product["product_url"] for product in products]
    assert "/games/15th-anniversary-scifi-exposure" in urls
    assert all(url.startswith("/games/") for url in urls)
    assert len(urls) == len(set(urls))
    sci_fi = next(product for product in products if product["slug"] == "15th-anniversary-scifi-exposure")
    assert sci_fi["productKey"] == "15thanniversaryscifiexposure_bundle"
# end def test_bundle_index_lists_games_bundles


def test_bundle_index_without_bundles_is_an_error() -> None:
    with pytest.raises(HumbleParseError, match="no Games bundles"):
        parse_bundle_index_nextjs(fixture("membership-november-2026.html"))
    # end with
# end def test_bundle_index_without_bundles_is_an_error


def test_bundle_page_builds_the_cumulative_tiers_highest_first() -> None:
    listing = {"productKey": "15thanniversaryscifiexposure_bundle"}
    payload = extract_bundle_payload_nextjs(fixture("bundle-15th-anniversary-scifi-exposure.html"), listing)

    archive, source = build_offer_archive(payload, CRAWLED)

    assert archive.kind == "bundle"
    assert archive.machine_name == "15thanniversaryscifiexposure_bundle"
    assert archive.url.unicode_string() == "https://www.humblebundle.com/games/15th-anniversary-scifi-exposure"
    assert archive.name == "Humble 15th Anniversary - Sci-Fi Exposure Bundle"
    assert archive.headline == "Sci-fi like you’ve never seen before"
    assert [(tier.identifier, tier.name, tier.item_count) for tier in archive.tiers] == [
        ("bt25", "Entire 8 Item Bundle", 8),
        ("bt15", "6 Item Bundle", 6),
        ("initial", "3 Item Bundle", 3),
    ]
    assert archive.tiers[2].minimum_price is not None
    assert archive.tiers[2].minimum_price.value == pytest.approx(8.88)
    assert archive.tiers[2].minimum_price.currency_code == "EUR"
    # The cheaper tiers' items are back-references on the page, they must resolve to the same games.
    assert [item.machine_name for item in archive.tiers[0].items][-3:] == [
        item.machine_name for item in archive.tiers[2].items
    ]
    assert archive.tiers[0].items[0].machine_name == "marathon"
    assert archive.tiers[0].items[0].title == "Marathon"
    assert archive.tiers[0].items[0].redeem_on == ["steam"]
    assert archive.tiers[0].items[0].platforms == ["Windows"]
    assert archive.tiers[0].items[0].developers[0].name == "Bungie"
    assert archive.charities[0].name == "charity: water"
    assert archive.dates.start is not None
    assert archive.dates.start.iso == "2026-10-21T18:00+00:00"
    assert archive.dates.end is not None
    assert archive.dates.end.iso == "2026-11-12T05:00+00:00"
    assert archive.description.startswith("**Sci-fi like you’ve never seen before.**")
    assert source["format"] == "nextjs"
# end def test_bundle_page_builds_the_cumulative_tiers_highest_first


def test_bundle_page_without_bundle_data_is_an_error() -> None:
    with pytest.raises(HumbleParseError, match="bundlePage"):
        extract_bundle_payload_nextjs(fixture("bundles-index.html"), None)
    # end with
# end def test_bundle_page_without_bundle_data_is_an_error


def test_choice_page_builds_this_months_games() -> None:
    payload = extract_choice_payload_nextjs(fixture("membership-november-2026.html"))

    archive, _source = build_offer_archive(payload, CRAWLED)

    assert archive.kind == "choice"
    assert archive.machine_name == "november_2026_choice"
    assert archive.name == "November 2026 Humble Choice"
    assert archive.url.unicode_string() == "https://www.humblebundle.com/membership"
    assert len(archive.tiers) == 1
    assert archive.tiers[0].minimum_price is not None
    assert archive.tiers[0].minimum_price.raw == "$11.99"
    assert archive.tiers[0].minimum_price.currency_code == "USD"
    games = [item for item in archive.tiers[0].items if item.is_game]
    assert [item.machine_name for item in games][:2] == ["mafia_theoldcountry_choice", "theouterworlds2_choice"]
    assert len(games) == 8
    assert games[0].title == "Mafia: The Old Country"
    assert games[0].redeem_on == ["steam"]
    assert games[0].retail_price is not None
    assert games[0].retail_price.value == pytest.approx(64.99)
    assert games[1].redeem_on == ["blizzard"]
    # The IGN Plus perk is not a game, it is delivered outside any storefront.
    perk = archive.tiers[0].items[-1]
    assert (perk.machine_name, perk.is_game, perk.tags, perk.redeem_on) == ("ignplus_choice_2026_11", False, ["coupon"], [])
# end def test_choice_page_builds_this_months_games


def test_choice_page_without_products_is_an_error() -> None:
    with pytest.raises(HumbleParseError, match="subscriptionProducts"):
        extract_choice_payload_nextjs(fixture("bundles-index.html"))
    # end with
# end def test_choice_page_without_products_is_an_error
