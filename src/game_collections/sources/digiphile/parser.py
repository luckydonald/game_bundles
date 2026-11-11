"""Parse digiphile.co's server-rendered Next.js pages into normalized bundle archives.

digiphile.co is a Next.js app whose pages embed their full data as React Server Component "flight" chunks:
`<script>self.__next_f.push([1,"<fragment>"])</script>`. Concatenating the string fragments yields text which
contains plain JSON objects, `"bundles":[...]` on `/collections` (summaries only) and `"bundle":{...}` on
`/collections/<slug>` (the full bundle with tiers and products). Plain HTTP works, no browser is needed.
A slug which does not exist still answers HTTP 200 with a Next.js 404 page, so a missing payload, not the status
code, means the bundle is gone.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

from game_collections.sources.digiphile.models import (
    DigiphileArchive,
    DigiphileBundleType,
    DigiphileDates,
    DigiphileItem,
    DigiphileTier,
    DigiphileTierType,
)
from game_collections.sources.flight import decode_after_key, flight_text
from game_collections.sources.names import SourceName
from game_collections.sources.timestamps import build_scraped_timestamp


DIGIPHILE_ROOT = "https://www.digiphile.co/"
COLLECTIONS_URL = f"{DIGIPHILE_ROOT}collections"
DIGIPHILE_HOSTS = {"digiphile.co", "www.digiphile.co"}

PAGE_PATH_PATTERN = re.compile(r"^/collections/(?P<slug>[a-z0-9][a-z0-9-]*)/?$")

BUNDLE_TYPES: dict[str, DigiphileBundleType] = {"SteamGame": "steam-game", "EBook": "ebook"}
TIER_TYPES: dict[str, DigiphileTierType] = {"Base": "base", "Charity": "charity", "Upsell": "upsell"}
# Add-on tiers are ordered charity first, then upsell, each by price, so a rank stays stable between crawls.
ADD_ON_ORDER: dict[DigiphileTierType, int] = {"base": 0, "charity": 1, "upsell": 2}


class DigiphileParseError(ValueError):
    """The Digiphile page did not have the expected shape."""

# end class DigiphileParseError


def page_url(slug: str) -> str:
    """The public page of one bundle."""
    return f"{COLLECTIONS_URL}/{slug}"
# end def page_url


def bundle_slug(url: str) -> str:
    """Extract the slug from a Digiphile bundle page URL, rejecting anything else (a `?linkId=` query is ignored)."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in DIGIPHILE_HOSTS:
        raise ValueError(f"Digiphile URLs must use https://www.digiphile.co: {url}")
    # end if
    match = PAGE_PATH_PATTERN.match(parsed.path)
    if match is None:
        raise ValueError(f"expected a Digiphile bundle URL (/collections/<slug>): {url}")
    # end if
    return match.group("slug")
# end def bundle_slug


def extract_bundle_slugs(html: str) -> list[str]:
    """The slugs of every bundle listed on `/collections`, in page order."""
    for value in decode_after_key(flight_text(html), "bundles", list):
        slugs = [item["slug"] for item in value if isinstance(item, dict) and isinstance(item.get("slug"), str)]
        if slugs and len(slugs) == len(value):
            return slugs
        # end if
    # end for
    raise DigiphileParseError("no bundle list found on the Digiphile collections page")
# end def extract_bundle_slugs


def extract_bundle(html: str) -> dict[str, Any]:
    """The full raw bundle object of a `/collections/<slug>` page, kept verbatim for `source.json`."""
    for value in decode_after_key(flight_text(html), "bundle", dict):
        if isinstance(value.get("slug"), str) and isinstance(value.get("tiers"), list):
            return cast(dict[str, Any], value)
        # end if
    # end for
    raise DigiphileParseError("no bundle found on the page (unknown slug?)")
# end def extract_bundle


def require(item: dict[str, Any], key: str, expected: type | tuple[type, ...], context: str) -> Any:
    value = item.get(key)
    if not isinstance(value, expected) or isinstance(value, bool) and expected is not bool:
        raise DigiphileParseError(f"{context}: missing or malformed {key!r}")
    # end if
    return value
# end def require


def number(item: dict[str, Any], key: str, context: str) -> float:
    return float(require(item, key, (int, float), context))
# end def number


def timestamp(raw: dict[str, Any], key: str, context: str) -> datetime | None:
    value = raw.get(key)
    if value is None:
        return None
    # end if
    if not isinstance(value, str):
        raise DigiphileParseError(f"{context}: malformed {key!r}")
    # end if
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise DigiphileParseError(f"{context}: {key!r} is not an ISO timestamp: {value!r}") from error
    # end try
    if parsed.tzinfo is None:
        raise DigiphileParseError(f"{context}: {key!r} carries no UTC offset: {value!r}")
    # end if
    return parsed.astimezone(UTC)
# end def timestamp


def parse_item(raw: Any, context: str) -> tuple[str, DigiphileItem]:
    """One product as `(bundleTierId, item)`; a Steam product's app id is mandatory, never guessed."""
    if not isinstance(raw, dict):
        raise DigiphileParseError(f"{context}: product is not an object")
    # end if
    product_id = require(raw, "id", str, context)
    title = require(raw, "title", str, context)
    product_context = f"{context} product {title!r}"
    product_type = require(raw, "type", str, product_context)
    ids: list[str] = []
    if product_type == "SteamGame":
        metadata = require(raw, "steamGameMetadata", dict, product_context)
        app_id = metadata.get("steamAppId")
        if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
            raise DigiphileParseError(f"{product_context}: no Steam app id")
        # end if
        ids.append(f"steam:{app_id}")
    # end if
    ids.append(f"digiphile:{product_id}")
    item = DigiphileItem(title=title, product_type=product_type, price=number(raw, "price", product_context), ids=ids)
    return require(raw, "bundleTierId", str, product_context), item
# end def parse_item


def parse_bundle(raw: dict[str, Any], observed: datetime) -> DigiphileArchive:
    """Parse one raw bundle object into the archived shape.

    Every product points at exactly one tier. A `Base` tier lists only the products it newly unlocks, so the archived
    base tiers accumulate (ordered by price), while a `Charity` or `Upsell` add-on keeps only its own products.
    """
    slug = require(raw, "slug", str, "bundle")
    context = f"bundle {slug}"
    raw_type = require(raw, "type", str, context)
    if raw_type not in BUNDLE_TYPES:
        raise DigiphileParseError(f"{context}: unsupported type {raw_type!r}")
    # end if

    raw_tiers = require(raw, "tiers", list, context)
    if not all(isinstance(tier, dict) for tier in raw_tiers):
        raise DigiphileParseError(f"{context}: tier is not an object")
    # end if
    tier_types: dict[str, DigiphileTierType] = {}
    for raw_tier in raw_tiers:
        raw_tier_type = require(raw_tier, "type", str, f"{context} tier")
        if raw_tier_type not in TIER_TYPES:
            raise DigiphileParseError(f"{context}: unsupported tier type {raw_tier_type!r}")
        # end if
        tier_types[require(raw_tier, "id", str, f"{context} tier")] = TIER_TYPES[raw_tier_type]
    # end for

    own_items: dict[str, list[tuple[int, DigiphileItem]]] = {tier_id: [] for tier_id in tier_types}
    for raw_product in require(raw, "products", list, context):
        tier_id, item = parse_item(raw_product, context)
        if tier_id not in own_items:
            raise DigiphileParseError(f"{context}: product {item.title!r} belongs to unknown tier {tier_id!r}")
        # end if
        own_items[tier_id].append((int(raw_product.get("order") or 0), item))
    # end for

    ordered = sorted(
        raw_tiers,
        key=lambda tier: (
            ADD_ON_ORDER[tier_types[tier["id"]]],
            number(tier, "price", context),
            int(tier.get("order") or 0),
            tier["id"],
        ),
    )
    tiers: list[DigiphileTier] = []
    unlocked: list[DigiphileItem] = []
    for raw_tier in ordered:
        tier_type = tier_types[raw_tier["id"]]
        items = [item for _order, item in sorted(own_items[raw_tier["id"]], key=lambda entry: entry[0])]
        if tier_type == "base":
            unlocked = [*unlocked, *items]
            items = list(unlocked)
        # end if
        tiers.append(
            DigiphileTier(
                identifier=raw_tier["id"],
                name=require(raw_tier, "name", str, context),
                tier_type=tier_type,
                price=number(raw_tier, "price", context),
                order=int(raw_tier.get("order") or 0),
                items=items,
            )
        )
    # end for
    if not any(tier.items for tier in tiers):
        raise DigiphileParseError(f"{context}: no products")
    # end if

    start = timestamp(raw, "startsAt", context)
    end = timestamp(raw, "endsAt", context)
    charities = [
        entry["charity"]["name"]
        for entry in raw.get("charities") or []
        if isinstance(entry, dict) and isinstance(entry.get("charity"), dict) and isinstance(entry["charity"].get("name"), str)
    ]
    series = raw.get("bundleTypeTag")
    subtitle = raw.get("subtitle")
    return DigiphileArchive(
        machine_name=slug,
        url=page_url(slug),
        name=require(raw, "title", str, context),
        subtitle=subtitle if isinstance(subtitle, str) and subtitle else None,
        bundle_type=BUNDLE_TYPES[raw_type],
        curator_series=series["name"] if isinstance(series, dict) and isinstance(series.get("name"), str) else None,
        charities=charities,
        min_price=number(raw, "minPrice", context),
        suggested_price=number(raw, "suggestedPrice", context),
        dates=DigiphileDates(
            start=build_scraped_timestamp(start, SourceName.DIGIPHILE, 1.0) if start else None,
            end=build_scraped_timestamp(end, SourceName.DIGIPHILE, 1.0) if end else None,
            first_seen=observed,
            crawled=observed,
        ),
        tiers=tiers,
    )
# end def parse_bundle
