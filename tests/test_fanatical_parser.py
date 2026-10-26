from __future__ import annotations

import json
from typing import Any

import pytest

from fanatical_data import prices, product, raw_bundle
from game_collections.sources.fanatical.parser import (
    FanaticalParseError,
    bundle_slug,
    page_url,
    parse_bundle,
    parse_bundles_json,
)


def test_parse_bundle_reads_tiers_prices_and_dates() -> None:
    draft = parse_bundle(raw_bundle())

    assert draft.slug == "tiny-bundle"
    assert draft.bundle_type == "bundle"
    assert draft.discount_percent == 90
    assert draft.full_price["USD"] == 30.0
    assert draft.start is not None and draft.start.isoformat() == "2026-10-02T10:00:00+00:00"
    assert draft.end is not None and draft.end.isoformat() == "2026-10-31T08:00:00+00:00"
    assert [tier.identifier for tier in draft.tiers] == ["tier-1", "tier-2"]
    assert [tier.display_total for tier in draft.tiers] == [2, 3]
    assert [[p.slug for p in tier.products] for tier in draft.tiers] == [["one", "two"], ["three"]]
    assert draft.tiers[0].products[0].steam_app_id == 11
# end def test_parse_bundle_reads_tiers_prices_and_dates


def test_parse_bundle_treats_empty_and_missing_steam_ids_as_unknown() -> None:
    item = raw_bundle(
        bundle_tiers=[
            {
                "displayTotal": 3,
                "price": prices(1),
                "products": [product("empty", ""), product("missing", None), product("textual", "440")],
            }
        ]
    )

    ids = {p.slug: p.steam_app_id for p in parse_bundle(item).tiers[0].products}

    assert ids == {"empty": None, "missing": None, "textual": 440}
# end def test_parse_bundle_treats_empty_and_missing_steam_ids_as_unknown


def test_parse_bundle_accepts_pick_and_mix_with_a_pool_on_the_first_tier_only() -> None:
    item = raw_bundle(
        slug="build-your-own",
        type="pick-and-mix",
        bundle_tiers=[
            {"displayTotal": 3, "price": prices(10), "products": [product("a", 1), product("b", 2)]},
            {"displayTotal": 5, "price": prices(16), "products": None},
        ],
    )

    draft = parse_bundle(item)

    assert draft.bundle_type == "pick-and-mix"
    assert [len(tier.products) for tier in draft.tiers] == [2, 0]
# end def test_parse_bundle_accepts_pick_and_mix_with_a_pool_on_the_first_tier_only


def test_parse_bundle_rejects_bundles_without_visible_products() -> None:
    item = raw_bundle(bundle_tiers=[{"displayTotal": 2, "price": prices(1), "products": None}])

    with pytest.raises(FanaticalParseError, match="no visible products"):
        parse_bundle(item)
# end def test_parse_bundle_rejects_bundles_without_visible_products


@pytest.mark.parametrize(
    "override",
    [{"type": "mystery"}, {"fullPrice": {}}, {"name": None}, {"discount_percent": 101}, {"bundle_tiers": "x"}],
)
def test_parse_bundle_rejects_a_changed_shape(override: dict[str, Any]) -> None:
    with pytest.raises(FanaticalParseError):
        parse_bundle(raw_bundle(**override))
# end def test_parse_bundle_rejects_a_changed_shape


def test_parse_bundles_json_requires_an_array_of_objects() -> None:
    assert parse_bundles_json(json.dumps([raw_bundle()]))[0]["slug"] == "tiny-bundle"
    for bad in ("{}", "[1]", "not json"):
        with pytest.raises(FanaticalParseError):
            parse_bundles_json(bad)
        # end with
    # end for
# end def test_parse_bundles_json_requires_an_array_of_objects


def test_bundle_slug_accepts_both_page_kinds_and_locales() -> None:
    assert bundle_slug("https://www.fanatical.com/en/bundle/coppafeel-charity-bundle") == "coppafeel-charity-bundle"
    assert bundle_slug("https://www.fanatical.com/de/pick-and-mix/build-your-own-x/") == "build-your-own-x"
    assert bundle_slug("https://fanatical.com/bundle/plain") == "plain"
# end def test_bundle_slug_accepts_both_page_kinds_and_locales


@pytest.mark.parametrize(
    "url",
    [
        "http://www.fanatical.com/en/bundle/x",
        "https://example.com/en/bundle/x",
        "https://www.fanatical.com/en/game/x",
    ],
)
def test_bundle_slug_rejects_foreign_or_non_bundle_urls(url: str) -> None:
    with pytest.raises(ValueError):
        bundle_slug(url)
# end def test_bundle_slug_rejects_foreign_or_non_bundle_urls


def test_page_url_uses_the_kind_specific_path() -> None:
    assert page_url("bundle", "a") == "https://www.fanatical.com/en/bundle/a"
    assert page_url("pick-and-mix", "a") == "https://www.fanatical.com/en/pick-and-mix/a"
# end def test_page_url_uses_the_kind_specific_path
