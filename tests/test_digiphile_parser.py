from __future__ import annotations

from datetime import UTC, datetime

import pytest

from digiphile_data import NOT_FOUND_PAGE, listing_page, page, product, raw_bundle, tier
from game_collections.sources.digiphile.parser import (
    DigiphileParseError,
    bundle_slug,
    extract_bundle,
    extract_bundle_slugs,
    parse_bundle,
)


OBSERVED = datetime(2026, 10, 28, tzinfo=UTC)


def test_extract_bundle_reads_the_chunked_flight_payload_verbatim() -> None:
    raw = raw_bundle()

    assert extract_bundle(page(raw)) == raw
# end def test_extract_bundle_reads_the_chunked_flight_payload_verbatim


def test_extract_bundle_rejects_the_soft_404_page() -> None:
    with pytest.raises(DigiphileParseError, match="no bundle found"):
        extract_bundle(NOT_FOUND_PAGE)
    # end with
# end def test_extract_bundle_rejects_the_soft_404_page


def test_extract_bundle_slugs_lists_every_bundle_in_page_order() -> None:
    assert extract_bundle_slugs(listing_page("b", "a")) == ["b", "a"]
    with pytest.raises(DigiphileParseError, match="no bundle list"):
        extract_bundle_slugs(NOT_FOUND_PAGE)
    # end with
# end def test_extract_bundle_slugs_lists_every_bundle_in_page_order


def test_parse_bundle_orders_tiers_and_accumulates_only_the_base_ones() -> None:
    archive = parse_bundle(raw_bundle(), OBSERVED)

    assert [(t.name, t.tier_type) for t in archive.tiers] == [
        ("Tier $4.00", "base"),
        ("Tier $16.00", "base"),
        ("Relief Fund", "charity"),
        ("Map DLC", "upsell"),
    ]
    assert [[item.title for item in t.items] for t in archive.tiers] == [
        ["One"],
        ["One", "Three", "Two"],
        ["Soundtrack"],
        ["Map Pack"],
    ]
    assert archive.tiers[0].items[0].ids == ["steam:1", "digiphile:p-one"]
    assert archive.bundle_type == "steam-game"
    assert archive.charities == ["Good Cause"]
    assert archive.curator_series == "Signature Series"
    assert archive.subtitle == "Small but mighty"
    assert (archive.min_price, archive.suggested_price) == (4, 16)
    assert archive.dates.start is not None and archive.dates.start.confidence == 1.0
    assert archive.dates.end is not None and archive.dates.end.iso.startswith("2026-11-04")
    assert archive.dates.crawled == OBSERVED
# end def test_parse_bundle_orders_tiers_and_accumulates_only_the_base_ones


def test_parse_bundle_ebooks_carry_only_the_anchor_id() -> None:
    raw = raw_bundle(
        type="EBook",
        tiers=[tier("t-5", "Tier $5.00", 5)],
        products=[product("c-1", "Comic", "t-5", kind="EBook")],
    )

    archive = parse_bundle(raw, OBSERVED)

    assert archive.bundle_type == "ebook"
    assert archive.tiers[0].items[0].ids == ["digiphile:c-1"]
# end def test_parse_bundle_ebooks_carry_only_the_anchor_id


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"products": [product("p", "No App", "t-4", None)]}, "no Steam app id"),
        ({"products": [product("p", "Lost", "t-nowhere", 1)]}, "unknown tier"),
        ({"tiers": [tier("t-4", "Odd", 4, "Mystery")]}, "unsupported tier type"),
        ({"type": "Audio"}, "unsupported type"),
        ({"startsAt": "2026-10-20T15:00:00"}, "no UTC offset"),
        ({"products": []}, "no products"),
    ],
)
def test_parse_bundle_fails_loudly_on_a_changed_shape(override: dict[str, object], message: str) -> None:
    with pytest.raises(DigiphileParseError, match=message):
        parse_bundle(raw_bundle(**override), OBSERVED)
    # end with
# end def test_parse_bundle_fails_loudly_on_a_changed_shape


def test_bundle_slug_accepts_collection_urls_and_ignores_the_query() -> None:
    assert bundle_slug("https://www.digiphile.co/collections/rts-renaissance?linkId=x&sourceId=deku") == "rts-renaissance"
    assert bundle_slug("https://digiphile.co/collections/rts-renaissance/") == "rts-renaissance"
# end def test_bundle_slug_accepts_collection_urls_and_ignores_the_query


@pytest.mark.parametrize(
    "url",
    [
        "http://www.digiphile.co/collections/x",
        "https://example.com/collections/x",
        "https://www.digiphile.co/collections",
        "https://www.digiphile.co/other/x",
    ],
)
def test_bundle_slug_rejects_anything_else(url: str) -> None:
    with pytest.raises(ValueError):
        bundle_slug(url)
    # end with
# end def test_bundle_slug_rejects_anything_else
