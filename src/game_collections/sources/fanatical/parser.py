"""Parse Fanatical's public bundle-list JSON into drafts ready for storefront resolution.

fanatical.com is a client-rendered SPA, so its HTML pages carry no bundle data. The page at
`/en/bundle/games` is fed by `GET /api/algolia/bundles`, a plain JSON list of every currently
listed bundle (confirmed live, no authentication, only a browser-like `User-Agent`). There is
no per-bundle detail endpoint, so a single bundle is looked up by slug in that same list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlparse

from game_collections.sources.fanatical.models import FanaticalBundleType, FanaticalPrices


FANATICAL_ROOT = "https://www.fanatical.com/"
BUNDLES_API_URL = f"{FANATICAL_ROOT}api/algolia/bundles"

PAGE_PATH_PATTERN = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?(?P<kind>bundle|pick-and-mix)/(?P<slug>[a-z0-9][a-z0-9-]*)/?$")
FANATICAL_HOSTS = {"fanatical.com", "www.fanatical.com"}


class FanaticalParseError(ValueError):
    """The Fanatical bundle JSON did not have the expected shape."""

# end class FanaticalParseError


@dataclass(frozen=True, slots=True)
class FanaticalProduct:
    """One product of a tier, before its storefront ids are resolved."""

    slug: str
    title: str
    product_type: str
    drm: tuple[str, ...]
    steam_app_id: int | None

# end class FanaticalProduct


@dataclass(frozen=True, slots=True)
class FanaticalDraftTier:
    """One tier as Fanatical lists it: `products` are only those *newly* unlocked by this tier."""

    identifier: str
    price: FanaticalPrices
    display_total: int
    products: tuple[FanaticalProduct, ...]

# end class FanaticalDraftTier


@dataclass(frozen=True, slots=True)
class FanaticalDraft:
    """One bundle as parsed from the list JSON, plus nothing resolved yet."""

    slug: str
    name: str
    bundle_type: FanaticalBundleType
    pay_what_you_want: bool
    discount_percent: int
    full_price: FanaticalPrices
    start: datetime | None
    end: datetime | None
    tiers: tuple[FanaticalDraftTier, ...] = field(default_factory=tuple)

# end class FanaticalDraft


def page_url(bundle_type: str, slug: str) -> str:
    """The public page of one bundle (`/en/bundle/<slug>` or `/en/pick-and-mix/<slug>`)."""
    return f"{FANATICAL_ROOT}en/{bundle_type}/{slug}"
# end def page_url


def bundle_slug(url: str) -> str:
    """Extract the slug from a Fanatical bundle page URL, rejecting anything else."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in FANATICAL_HOSTS:
        raise ValueError(f"Fanatical URLs must use https://www.fanatical.com: {url}")
    # end if
    match = PAGE_PATH_PATTERN.match(parsed.path)
    if match is None:
        raise ValueError(f"expected a Fanatical bundle or pick-and-mix URL: {url}")
    # end if
    return match.group("slug")
# end def bundle_slug


def parse_bundles_json(text: str) -> list[dict[str, Any]]:
    """Parse the list endpoint's body into its raw bundle items, keeping the payload verbatim."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise FanaticalParseError(f"bundle list is not valid JSON: {error}") from error
    # end try
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise FanaticalParseError("bundle list is not a JSON array of objects")
    # end if
    return cast(list[dict[str, Any]], data)
# end def parse_bundles_json


def _require(item: dict[str, Any], key: str, expected: type | tuple[type, ...], context: str) -> Any:
    value = item.get(key)
    if not isinstance(value, expected):
        raise FanaticalParseError(f"{context}: missing or malformed {key!r}")
    # end if
    return value
# end def _require


def _prices(value: Any, context: str) -> FanaticalPrices:
    if not isinstance(value, dict) or not value:
        raise FanaticalParseError(f"{context}: missing or malformed price")
    # end if
    prices: FanaticalPrices = {}
    for currency, amount in value.items():
        if isinstance(amount, bool) or not isinstance(amount, int | float) or amount < 0:
            raise FanaticalParseError(f"{context}: malformed {currency} price")
        # end if
        prices[str(currency)] = float(amount)
    # end for
    return prices
# end def _prices


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        return None
    # end if
    return datetime.fromtimestamp(value, tz=UTC)
# end def _timestamp


def _steam_app_id(product: dict[str, Any]) -> int | None:
    """Fanatical's `steamId`: an int for known apps, `""` or `None` when unknown (confirmed live)."""
    value = product.get("steamId")
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 and product.get("steamIdType") in ("app", "", None) else None
    # end if
    if isinstance(value, str) and value.isdecimal() and int(value) > 0:
        return int(value)
    # end if
    return None
# end def _steam_app_id


def _product(raw: Any, context: str) -> FanaticalProduct:
    if not isinstance(raw, dict):
        raise FanaticalParseError(f"{context}: product is not an object")
    # end if
    drm = raw.get("drm") or []
    if not isinstance(drm, list):
        raise FanaticalParseError(f"{context}: malformed 'drm'")
    # end if
    return FanaticalProduct(
        slug=_require(raw, "slug", str, context),
        title=_require(raw, "name", str, context),
        product_type=_require(raw, "type", str, context),
        drm=tuple(str(value) for value in drm),
        steam_app_id=_steam_app_id(raw),
    )
# end def _product


def parse_bundle(item: dict[str, Any]) -> FanaticalDraft:
    """Parse one raw list entry into a draft bundle.

    Fanatical lists each tier's *additional* products only (a 3-tier comic bundle: 4 / 21 / 38 new
    products for 4 / 25 / 63 total), whereas a `pick-and-mix` lists the whole pick pool on its first
    tier alone and `null` on the rest (their `displayTotal` is the pick count). Both are kept raw here;
    the crawler turns them into the archived cumulative / shared-pool shape.
    """
    slug = _require(item, "slug", str, "bundle")
    context = f"bundle {slug}"
    bundle_type = _require(item, "type", str, context)
    if bundle_type not in ("bundle", "pick-and-mix"):
        raise FanaticalParseError(f"{context}: unsupported type {bundle_type!r}")
    # end if
    raw_tiers = _require(item, "bundle_tiers", list, context)
    tiers: list[FanaticalDraftTier] = []
    for index, raw_tier in enumerate(raw_tiers, start=1):
        tier_context = f"{context} tier {index}"
        if not isinstance(raw_tier, dict):
            raise FanaticalParseError(f"{tier_context}: tier is not an object")
        # end if
        raw_products = raw_tier.get("products") or []
        if not isinstance(raw_products, list):
            raise FanaticalParseError(f"{tier_context}: malformed 'products'")
        # end if
        total = _require(raw_tier, "displayTotal", int, tier_context)
        tiers.append(
            FanaticalDraftTier(
                identifier=f"tier-{index}",
                price=_prices(raw_tier.get("price"), tier_context),
                display_total=total,
                products=tuple(_product(raw, tier_context) for raw in raw_products),
            )
        )
    # end for
    if not tiers or not any(tier.products for tier in tiers):
        raise FanaticalParseError(f"{context}: no visible products (mystery bundle?)")
    # end if
    discount = item.get("discount_percent", 0)
    if not isinstance(discount, int) or isinstance(discount, bool) or not 0 <= discount <= 100:
        raise FanaticalParseError(f"{context}: malformed 'discount_percent'")
    # end if
    return FanaticalDraft(
        slug=slug,
        name=_require(item, "name", str, context),
        bundle_type=cast(FanaticalBundleType, bundle_type),
        pay_what_you_want=bool(item.get("pay_what_you_want")),
        discount_percent=discount,
        full_price=_prices(item.get("fullPrice"), context),
        start=_timestamp(item.get("available_valid_from")),
        end=_timestamp(item.get("available_valid_until")),
        tiers=tuple(tiers),
    )
# end def parse_bundle
