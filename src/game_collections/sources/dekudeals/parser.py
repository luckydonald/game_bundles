"""Parse dekudeals.com's embedded Inertia.js page data and plain item-page markup."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urljoin

from game_collections.sources.dekudeals.models import DekuPrice


DEKU_ROOT = "https://www.dekudeals.com/"

# The bundles index and every bundle detail page are Inertia.js views: the
# full page props are embedded, HTML-entity-encoded, as one JSON object in
# `<div id="inertia-app" data-page="...">`. That JSON has no literal `"`
# (only `&quot;`), so the attribute's true end is the first raw `">` after it
# - far more robust than scraping the rendered cards/tables by hand.
_DATA_PAGE_MARKER = 'data-page="'
BUNDLE_LINK_PATTERN = re.compile(r"^/bundles/([a-z0-9-]+)/?$")


class DekuParseError(ValueError):
    """A dekudeals.com page did not contain the expected structure."""

# end class DekuParseError


def _inertia_props(html_text: str, label: str) -> dict[str, Any]:
    start_marker = html_text.find(_DATA_PAGE_MARKER)
    if start_marker == -1:
        raise DekuParseError(f"{label} is missing its inertia-app data-page attribute")
    # end if
    start = start_marker + len(_DATA_PAGE_MARKER)
    end = html_text.find('">', start)
    if end == -1:
        raise DekuParseError(f"{label}'s data-page attribute is not terminated")
    # end if
    try:
        payload = json.loads(html.unescape(html_text[start:end]))
    except ValueError as error:
        raise DekuParseError(f"{label}'s data-page attribute is not valid JSON: {error}") from error
    # end try
    props = payload.get("props")
    if not isinstance(props, dict):
        raise DekuParseError(f"{label}'s data-page payload has no props object")
    # end if
    return props
# end def _inertia_props


def bundle_slug(url: str) -> str:
    match = BUNDLE_LINK_PATTERN.match(url if url.startswith("/") else url.removeprefix(DEKU_ROOT.rstrip("/")))
    if not match:
        raise DekuParseError(f"URL does not look like a DekuDeals bundle page: {url}")
    # end if
    return match.group(1)
# end def bundle_slug


def _unix_ts(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if isinstance(value, int) else None
# end def _unix_ts


@dataclass(frozen=True, slots=True)
class DekuIndexEntry:
    """One bundle summary on the bundles index page.

    Fields confirmed live against a real fetch of `https://www.dekudeals.com/bundles`
    (`props.bundles[i]`, see the confidence-scored-dates plan). `created_at`/`ends_at`
    (unix timestamps) are the closest thing DekuDeals gives to a bundle's start/end
    date - the bundle detail page itself never reports a start date at all, and its own
    `ends_at` matches this same index value, so this doubles as a cross-check. `image`,
    `top_items`, `created_at_formatted`, and `ends_at_formatted` are known live fields,
    intentionally left unmodeled here (decorative/redundant, not needed for archiving).
    """

    slug: str
    name: str | None
    store: str | None
    tiering_style: str | None
    price: int | None
    price_formatted: str | None
    size: int | None
    created_at: datetime | None
    ends_at: datetime | None
    ends_at_label: str | None

# end class DekuIndexEntry


def parse_bundle_index_page(html_text: str) -> list[DekuIndexEntry]:
    """Return every bundle summary currently listed on the bundles index page."""
    props = _inertia_props(html_text, "bundles index page")
    bundles = props.get("bundles")
    if not isinstance(bundles, list) or not bundles:
        raise DekuParseError("bundles index page has no bundles list")
    # end if
    entries: list[DekuIndexEntry] = []
    seen: set[str] = set()
    for entry in bundles:
        slug = entry.get("slug") if isinstance(entry, dict) else None
        if not isinstance(slug, str) or not slug or slug in seen:
            continue
        # end if
        seen.add(slug)
        entries.append(
            DekuIndexEntry(
                slug=slug,
                name=entry.get("name") if isinstance(entry.get("name"), str) else None,
                store=entry.get("store") if isinstance(entry.get("store"), str) else None,
                tiering_style=entry.get("tiering_style") if isinstance(entry.get("tiering_style"), str) else None,
                price=entry.get("price") if isinstance(entry.get("price"), int) else None,
                price_formatted=entry.get("price_formatted") if isinstance(entry.get("price_formatted"), str) else None,
                size=entry.get("size") if isinstance(entry.get("size"), int) else None,
                created_at=_unix_ts(entry.get("created_at")),
                ends_at=_unix_ts(entry.get("ends_at")),
                ends_at_label=entry.get("ends_at_label") if isinstance(entry.get("ends_at_label"), str) else None,
            )
        )
    # end for
    if not entries:
        raise DekuParseError("bundles index page's bundles list has no slugs")
    # end if
    return entries
# end def parse_bundle_index_page


@dataclass(frozen=True, slots=True)
class DekuItemDraft:
    """One bundle item as reported by the bundle detail page, before id resolution."""

    slug: str
    title: str
    tier_ids: tuple[int, ...]

# end class DekuItemDraft


@dataclass(frozen=True, slots=True)
class DekuTierDraft:
    """One purchase tier/pick-option, before its items are resolved into `DekuTier`s."""

    identifier: str
    price: DekuPrice | None
    item_minimum: int | None

# end class DekuTierDraft


@dataclass(frozen=True, slots=True)
class DekuBundleDraft:
    """A parsed bundle detail page, before per-item storefront resolution."""

    machine_name: str
    url: str
    name: str
    store_name: str
    tiering_style: Literal["price_per_tier", "price_per_item"]
    real_url: str | None
    end: datetime | None
    tiers: tuple[DekuTierDraft, ...]
    items: tuple[DekuItemDraft, ...]

# end class DekuBundleDraft


def _price(raw_cents: Any, formatted: Any, label: str) -> DekuPrice | None:
    if raw_cents is None:
        return None
    # end if
    if not isinstance(raw_cents, int) or not isinstance(formatted, str) or not formatted:
        raise DekuParseError(f"{label} price is malformed")
    # end if
    return DekuPrice(raw=formatted, value=raw_cents / 100, currency=re.sub(r"[\d.,\s]+", "", formatted) or "?")
# end def _price


def parse_bundle_page(html_text: str, url: str) -> tuple[DekuBundleDraft, dict[str, Any]]:
    """Normalize one bundle detail page's embedded Inertia props."""
    props = _inertia_props(html_text, f"bundle page ({url})")
    bundle = props.get("bundle")
    tiers_raw = props.get("tiers")
    items_raw = props.get("items")
    if not isinstance(bundle, dict):
        raise DekuParseError(f"bundle page has no bundle object: {url}")
    # end if
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise DekuParseError(f"bundle page has no tiers: {url}")
    # end if
    if not isinstance(items_raw, list) or not items_raw:
        raise DekuParseError(f"bundle page has no items: {url}")
    # end if

    tiering_style = bundle.get("tiering_style")
    if tiering_style not in ("price_per_tier", "price_per_item"):
        raise DekuParseError(f"bundle page has an unrecognized tiering_style: {tiering_style!r} ({url})")
    # end if
    slug = bundle.get("slug")
    name = bundle.get("name")
    store_name = bundle.get("store_name")
    if not isinstance(slug, str) or not slug or not isinstance(name, str) or not name:
        raise DekuParseError(f"bundle page is missing slug/name: {url}")
    # end if
    if not isinstance(store_name, str) or not store_name:
        raise DekuParseError(f"bundle page is missing its store_name: {url}")
    # end if

    ends_at = bundle.get("ends_at")
    end = datetime.fromtimestamp(ends_at, tz=UTC) if isinstance(ends_at, int) else None
    real_url = bundle.get("url") if isinstance(bundle.get("url"), str) else None

    tier_drafts: list[DekuTierDraft] = []
    for tier in tiers_raw:
        if not isinstance(tier, dict) or "id" not in tier:
            raise DekuParseError(f"bundle page has a malformed tier: {url}")
        # end if
        tier_drafts.append(
            DekuTierDraft(
                identifier=str(tier["id"]),
                price=_price(tier.get("price"), tier.get("price_formatted"), "tier"),
                item_minimum=tier.get("item_minimum"),
            )
        )
    # end for

    item_drafts: list[DekuItemDraft] = []
    for item in items_raw:
        if not isinstance(item, dict):
            raise DekuParseError(f"bundle page has a malformed item: {url}")
        # end if
        item_slug = item.get("slug")
        item_name = item.get("name")
        if not isinstance(item_slug, str) or not item_slug or not isinstance(item_name, str) or not item_name:
            raise DekuParseError(f"bundle page has an item with no slug/name: {url}")
        # end if
        tier_ids = item.get("tiers")
        item_drafts.append(
            DekuItemDraft(
                slug=item_slug,
                title=item_name,
                tier_ids=tuple(tier_ids) if isinstance(tier_ids, list) else (),
            )
        )
    # end for

    draft = DekuBundleDraft(
        machine_name=slug,
        url=url,
        name=name,
        store_name=store_name,
        tiering_style=tiering_style,
        real_url=real_url,
        end=end,
        tiers=tuple(tier_drafts),
        items=tuple(item_drafts),
    )
    return draft, props
# end def parse_bundle_page


# One store-link row on an item page repeats the same `href` across three
# anchors, each tagged with the same `data-out-analytics-id`; only the
# `href` matters here (the qualified-id parsing happens in storefronts.py),
# so rows are deduped by that shared id before returning their URLs.
_ITEM_STORE_LINK_PATTERN = re.compile(r"data-out-analytics-id='([^']+)'\s+href='([^']+)'")


def parse_item_page(html_text: str, url: str) -> list[str]:
    """Return every distinct storefront URL listed on a DekuDeals `/items/<slug>` page."""
    seen_ids: set[str] = set()
    urls: list[str] = []
    for analytics_id, href in _ITEM_STORE_LINK_PATTERN.findall(html_text):
        if analytics_id in seen_ids:
            continue
        # end if
        seen_ids.add(analytics_id)
        urls.append(urljoin(url, html.unescape(href)))
    # end for
    if not urls:
        raise DekuParseError(f"item page has no storefront links: {url}")
    # end if
    return urls
# end def parse_item_page
