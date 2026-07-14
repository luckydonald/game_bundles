from __future__ import annotations

import html
import json
from datetime import UTC, datetime

from game_collections.sources.humblebundle.parser import (
    parse_bundle_index,
    parse_bundle_page,
    parse_choice_page,
)


CRAWLED = datetime(2026, 7, 12, 2, 3, tzinfo=UTC)


def _script(script_id: str, value: object) -> str:
    return f'<script id="{script_id}" type="application/json">{json.dumps(value)}</script>'
# end def _script


def test_bundle_index_returns_games_only() -> None:
    payload = {
        "data": {
            "books": {"mosaic": [{"products": [{"product_url": "/books/no"}]}]},
            "games": {
                "mosaic": [
                    {
                        "products": [
                            {
                                "machine_name": "sample_bundle",
                                "product_url": "/games/sample",
                                "start_date|datetime": "2026-07-01T18:00:00",
                                "end_date|datetime": "2026-07-22T18:00:00",
                            }
                        ]
                    }
                ]
            },
        }
    }

    products = parse_bundle_index(_script("landingPage-json-data", payload))

    assert [product["product_url"] for product in products] == ["/games/sample"]
# end def test_bundle_index_returns_games_only


def test_bundle_page_normalizes_metadata_and_cumulative_tiers() -> None:
    game = {
        "machine_name": "samplegame",
        "human_name": "Sample Game",
        "item_content_type": "game",
        "youtube_link": "video-id",
        "msrp_price|money": {"currency": "EUR", "amount": 19.99},
        "description_text": "<p>A <strong>great</strong> game.</p>",
        "developers": [{"developer-name": "Example Dev", "developer-url": "https://dev.example/"}],
        "publishers": [],
        "platforms_and_oses": {"game": {"steam": ["windows", "linux"]}},
        "availability_icons": {"delivery_icons": ["hb-steam"]},
        "resolved_paths": {"featured_image": "https://img.example/game.jpg"},
        "exclusive_countries": [],
        "is_region_locked": False,
        "user_ratings": {"steam_percent": 0.9},
        "cta_badge": None,
    }
    coupon = {
        **game,
        "machine_name": "coupon",
        "human_name": "Discount Coupon",
        "msrp_price|money": None,
        "cta_badge": {"badge": "coupon"},
    }
    payload = {
        "bundleData": {
            "machine_name": "sample_bundle",
            "page_url": "games/sample",
            "basic_data": {
                "human_name": "Sample Bundle",
                "short_marketing_blurb": "Play games. Help people.",
                "detailed_marketing_blurb": (
                    "<p>A <em>bundle</em> description.</p>"
                    '<p><span>Keys expire. Please redeem before July 17th, 2027.</span></p>'
                ),
                "end_time|datetime": "2026-07-22T18:00:00",
            },
            "tier_order": ["all", "basic"],
            "tier_display_data": {
                "all": {
                    "header": "Pay €10.00 or more to also unlock!",
                    "tier_item_machine_names": ["samplegame", "coupon"],
                },
                "basic": {
                    "header": "Pay €5.00 to unlock!",
                    "tier_item_machine_names": ["samplegame"],
                },
            },
            "tier_pricing_data": {
                "all": {"price|money": {"currency": "EUR", "amount": 10.0}},
                "basic": {"price|money": {"currency": "EUR", "amount": 5.0}},
            },
            "tier_item_data": {"samplegame": game, "coupon": coupon},
            "charity_data": {
                "charity_items": {
                    "example": {
                        "human_name": "Example Charity",
                        "description_text": "<p>Helps people.</p>",
                        "ppgf_info": {
                            "human_name": "Example Charity",
                            "url": "https://charity.example/",
                            "description": "<p>Helps people.</p>",
                            "logo_url": "https://charity.example/logo.png",
                        },
                    }
                }
            },
        }
    }
    listing = {
        "start_date|datetime": "2026-07-01T18:00:00",
        "end_date|datetime": "2026-07-22T18:00:00",
    }

    archive, source = parse_bundle_page(
        _script("webpack-bundle-page-data", payload),
        listing,
        CRAWLED,
    )

    assert archive.headline == "Play games. Help people."
    assert archive.description.startswith("A *bundle* description.")
    assert archive.key_expiration_text == "Keys expire. Please redeem before July 17th, 2027."
    assert archive.dates.start == datetime(2026, 7, 1, 18, tzinfo=UTC)
    assert [tier.name for tier in archive.tiers] == ["Entire 2 Item Bundle", "1 Item Bundle"]
    assert archive.tiers[0].minimum_price is not None
    assert archive.tiers[0].minimum_price.model_dump() == {
        "raw": "€10.00",
        "value": 10.0,
        "currency": "€",
        "currency_code": "EUR",
    }
    assert archive.tiers[0].items[0].description == "A **great** game."
    assert archive.tiers[0].items[0].platforms == ["Linux", "Windows"]
    assert archive.tiers[0].items[1].tags == ["Coupon"]
    assert archive.tiers[0].items[1].is_game is False
    assert source["listing"] == listing
# end def test_bundle_page_normalizes_metadata_and_cumulative_tiers


def test_choice_page_normalizes_attribute_json_and_markdown() -> None:
    content = {
        "samplegame": {
            "title": "Sample Game",
            "delivery_methods": ["steam"],
            "platforms": ["windows", "mac"],
            "msrp": {"currency": "EUR", "amount": 24.99},
            "image": "https://img.example/choice.jpg",
            "youtube_links": ["choice-video"],
            "genres": ["Adventure"],
            "user_rating": {"steam_percent": 0.95},
            "recommendation_copy_dict": {
                "copy": (
                    "<p>Explore a <strong>lovely</strong> world.</p>"
                    "<p>Keys expire. Please redeem your key before August 4th, 2027.</p>"
                )
            },
        },
        "bonus": {
            "title": "Subscription Bonus",
            "delivery_methods": ["other-key"],
            "platforms": [],
            "msrp": {"currency": "USD", "amount": 4.99},
            "image": "https://img.example/bonus.jpg",
            "youtube_links": [],
            "genres": [],
            "user_rating": {},
            "recommendation_copy_dict": {"copy": "<p>A bonus.</p>"},
        },
    }
    product = {
        "@context": "https://schema.org/",
        "@type": "Product",
        "name": "July 2026 Humble Choice",
        "sku": "july_2026_choice",
        "url": "https://www.humblebundle.com/membership",
        "description": "Get <strong>July Choice</strong>.",
        "offers": {
            "validFrom": "2026-07-07T17:00:00Z",
            "validThrough": "2026-08-04T17:00:00Z",
        },
    }
    marketing = {
        "activeContentMachineName": "july_2026_choice",
        "baseSubscriptionPrice|money": {"currency": "EUR", "amount": 12.99},
    }
    charity = {
        "charity_name": "Example Charity",
        "charity_description": "<span>Does good.</span>",
        "charity_logo": "https://charity.example/logo.jpg",
    }
    page = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        + _script("webpack-choice-marketing-data", marketing)
        + f'<div data-content-choice-data="{html.escape(json.dumps(content), quote=True)}" '
        'data-machine-name="samplegame"></div>'
        + '<div data-machine-name="bonus"></div>'
        + f'<button data-charity="{html.escape(json.dumps(charity), quote=True)}"></button>'
    )

    archive, source = parse_choice_page(page, CRAWLED)

    assert archive.machine_name == "july_2026_choice"
    assert archive.description == "Get **July Choice**."
    assert [item.machine_name for item in archive.tiers[0].items] == ["samplegame", "bonus"]
    assert archive.tiers[0].items[0].is_game is True
    assert archive.tiers[0].items[1].is_game is False
    assert archive.tiers[0].items[0].key_expiration_text == (
        "Keys expire. Please redeem your key before August 4th, 2027."
    )
    assert archive.charities[0].name == "Example Charity"
    assert source["choice_content"] == content
    assert archive.choice_pick_options == []
# end def test_choice_page_normalizes_attribute_json_and_markdown


def test_choice_page_builds_pick_options_from_tier_info_clamped_to_pool_size() -> None:
    # Verified live against a real Humble Choice page's `tierInfo`: a tier's raw
    # `choices` count (here premium=12) can exceed the month's actual game count
    # (here 2 real games + 1 bonus), and gets clamped rather than rejected.
    content = {
        "gameone": {
            "title": "Game One",
            "delivery_methods": ["steam"],
            "platforms": ["windows"],
            "msrp": {"currency": "EUR", "amount": 10.0},
            "youtube_links": [],
            "genres": [],
            "user_rating": {},
            "recommendation_copy_dict": {"copy": "One."},
        },
        "gametwo": {
            "title": "Game Two",
            "delivery_methods": ["steam"],
            "platforms": ["windows"],
            "msrp": {"currency": "EUR", "amount": 10.0},
            "youtube_links": [],
            "genres": [],
            "user_rating": {},
            "recommendation_copy_dict": {"copy": "Two."},
        },
        "bonus": {
            "title": "Bonus",
            "delivery_methods": ["other-key"],
            "platforms": [],
            "msrp": {"currency": "USD", "amount": 4.99},
            "youtube_links": [],
            "genres": [],
            "user_rating": {},
            "recommendation_copy_dict": {"copy": "A bonus."},
        },
    }
    product = {
        "@type": "Product",
        "name": "July 2026 Humble Choice",
        "sku": "july_2026_choice",
        "url": "https://www.humblebundle.com/membership",
        "description": "Choice.",
        "offers": {
            "validFrom": "2026-07-07T17:00:00Z",
            "validThrough": "2026-08-04T17:00:00Z",
        },
    }
    marketing = {
        "activeContentMachineName": "july_2026_choice",
        "baseSubscriptionPrice|money": {"currency": "EUR", "amount": 12.99},
        "tierInfo": {
            "lite": {"uses_choices": True, "choices": 0},
            "basic": {"uses_choices": True, "choices": 1},
            "premium": {"uses_choices": True, "choices": 12},
            "notreal": {"uses_choices": False, "choices": 5},
        },
    }
    page = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        + _script("webpack-choice-marketing-data", marketing)
        + f'<div data-content-choice-data="{html.escape(json.dumps(content), quote=True)}" '
        'data-machine-name="gameone"></div>'
        + '<div data-machine-name="gametwo"></div>'
        + '<div data-machine-name="bonus"></div>'
    )

    archive, _source = parse_choice_page(page, CRAWLED)

    assert [(option.tier_key, option.quota) for option in archive.choice_pick_options] == [
        ("basic", 1),
        ("premium", 2),
    ]
# end def test_choice_page_builds_pick_options_from_tier_info_clamped_to_pool_size
