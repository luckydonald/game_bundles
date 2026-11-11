"""Parse humblebundle.com's Next.js pages (since November 2026) into the normalized Humble archives.

The three pages the crawler reads (`/bundles`, `/games/<slug>`, `/membership`) embed their data as React Server Component
flight rows (see `sources/flight.py`) instead of the former `webpack-*` JSON scripts. This module turns the new
shapes into the same `HumbleArchive` the rest of the pipeline already knows, so lists, resolver and archives stay unchanged.

What the new pages carry (verified live on 2026-11-11):

- `/bundles`: `{"relationTo": "algolia-hit", "value": {...}}` records, one per bundle, with `slug`, `url`, `productKey`,
  `productType`, `endDate`, `itemsCount`.
- `/games/<slug>`: a `bundlePage` object with `tiers[].bundleItems[]` (each tier lists *all* its items, the cheaper
  tier's items as back-references), `supportingCharities`, `startDate`, `endDate`, `keyExpirationDate` and the
  description as a text row.
- `/membership`: a `choice-media-carousel` CMS block whose `subscriptionProducts` are this month's games. Unlike the old
  page it has no pick quotas, no per-game YouTube links, no charity and no exact start/end of the month.

Not carried any more, so not filled: `cta_badge` (the "DLC" pack marker), `user_ratings`, `is_region_locked`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin

from game_collections.sources.flight import decode_after_key, find_key, flight_text, parse_rows, resolve
from game_collections.sources.humblebundle.models import (
    HumbleArchive,
    HumbleCharity,
    HumbleDates,
    HumbleItem,
    HumbleLink,
    HumblePrice,
    HumbleResolution,
    HumbleTier,
)
from game_collections.sources.humblebundle.parser import (
    CURRENCY_SYMBOLS,
    HUMBLE_ROOT,
    STORE_NAMES,
    HumbleParseError,
    _confidence,
    _datetime,
    _expiration,
    _markdown,
    _optional_url,
    _parse_edition_bundle_components,
    _required_mapping,
    _required_string,
)


NEXTJS_FORMAT = "nextjs"
CHOICE_DESCRIPTION_PATTERN = re.compile(r"Get (?P<month>[A-Za-z]+) (?P<year>\d{4}) Humble Choice\b.*?(?P<price>[^\s\d]{1,3}\d[\d.,]*) per month")
# Delivery methods which are not a game storefront: a perk redeemed elsewhere (the monthly IGN Plus subscription).
NON_STORE_DELIVERY = {"other-key", "external_key", "external-key"}
SYMBOL_CURRENCY_CODES = {symbol: code for code, symbol in CURRENCY_SYMBOLS.items()}


def is_nextjs_page(html: str) -> bool:
    """Whether a Humble page is the Next.js flavour (it embeds flight data) rather than the former webpack one."""
    return "self.__next_f.push(" in html
# end def is_nextjs_page


def amount_price(value: object, raw: str | None = None) -> HumblePrice | None:
    """A `{"amount": 8.88, "currencyCode": "EUR"}` price, as bundle tiers and MSRPs state them."""
    if not isinstance(value, Mapping):
        return None
    # end if
    amount = value.get("amount")
    code = value.get("currencyCode")
    if not isinstance(amount, int | float) or not isinstance(code, str) or not code:
        return None
    # end if
    symbol = CURRENCY_SYMBOLS.get(code.upper(), code.upper())
    return HumblePrice(raw=raw or f"{symbol}{amount:.2f}", value=float(amount), currency=symbol, currency_code=code.upper())
# end def amount_price


def cent_price(value: object) -> HumblePrice | None:
    """A `{"type": "centPrecision", "centAmount": 6998.99, "currencyCode": "EUR", "fractionDigits": 2}` price."""
    if not isinstance(value, Mapping) or not isinstance(value.get("centAmount"), int | float):
        return None
    # end if
    digits = value.get("fractionDigits")
    places = digits if isinstance(digits, int) else 2
    # The page ships binary-float noise such as 6498.999999999999 cents, so round to whole cents first.
    amount = round(float(value["centAmount"])) / 10**places
    return amount_price({"amount": amount, "currencyCode": value.get("currencyCode")})
# end def cent_price


def page_rows(html: str) -> dict[str, Any]:
    """The decoded flight rows of a page."""
    rows = parse_rows(flight_text(html))
    if not rows:
        raise HumbleParseError("page has no flight data")
    # end if
    return rows
# end def page_rows


def parse_bundle_index_nextjs(html: str) -> list[dict[str, Any]]:
    """The active Games bundles listed on `/bundles`, shaped like the former landing page products (`product_url`)."""
    rows = page_rows(html)
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows.values():
        for hit in _algolia_hits(row):
            value = hit.get("value")
            if not isinstance(value, dict) or value.get("productType") != "humble-bundle":
                continue
            # end if
            url = value.get("url")
            if not isinstance(url, str) or not url.startswith("/games/") or url in seen:
                continue
            # end if
            seen.add(url)
            products.append({**value, "product_url": url})
        # end for
    # end for
    if not products:
        raise HumbleParseError("bundles page has no Games bundles in its flight data")
    # end if
    return products
# end def parse_bundle_index_nextjs


def _algolia_hits(row: object) -> list[dict[str, Any]]:
    """Every `{"relationTo": "algolia-hit", ...}` record anywhere inside one decoded row."""
    hits: list[dict[str, Any]] = []
    if isinstance(row, dict):
        if row.get("relationTo") == "algolia-hit":
            hits.append(row)
        # end if
        for child in row.values():
            hits.extend(_algolia_hits(child))
        # end for
    elif isinstance(row, list):
        for child in row:
            hits.extend(_algolia_hits(child))
        # end for
    # end if
    return hits
# end def _algolia_hits


def extract_bundle_payload_nextjs(html: str, listing: Mapping[str, Any] | None) -> dict[str, Any]:
    """The plain-JSON payload a Games bundle archive is built from, back-references resolved."""
    rows = page_rows(html)
    for row in rows.values():
        page = find_key(row, "bundlePage")
        if isinstance(page, dict) and isinstance(page.get("tiers"), list):
            return {
                "kind": "bundle",
                "format": NEXTJS_FORMAT,
                "bundle_page": resolve(page, rows),
                "listing": dict(listing) if listing is not None else {},
            }
        # end if
    # end for
    raise HumbleParseError("bundle page is missing bundlePage in its flight data")
# end def extract_bundle_payload_nextjs


def _links(value: object) -> list[HumbleLink]:
    if not isinstance(value, list):
        return []
    # end if
    return [
        HumbleLink(name=raw["name"], url=_optional_url(raw.get("url")))
        for raw in value
        if isinstance(raw, dict) and isinstance(raw.get("name"), str) and raw["name"].strip()
    ]
# end def _links


def _redeem_on(delivery_methods: object) -> list[str]:
    if not isinstance(delivery_methods, list):
        return []
    # end if
    return sorted(
        {
            STORE_NAMES.get(str(store).casefold(), str(store).casefold())
            for store in delivery_methods
            if str(store).casefold() not in NON_STORE_DELIVERY
        }
    )
# end def _redeem_on


def _platforms(value: object) -> list[str]:
    return sorted({str(platform).title() for platform in value}) if isinstance(value, list) else []
# end def _platforms


def _bundle_item_nextjs(raw: Mapping[str, Any], product_key: str) -> HumbleItem:
    key = _required_string(raw.get("key"), "bundle item key")
    # `marathon_15thanniversaryscifiexposure_bundle` -> `marathon`, the machine name the former page used.
    machine_name = key.removesuffix(f"_{product_key}") or key
    title = _required_string(raw.get("title"), f"item {machine_name} title")
    description_html = raw.get("description") if isinstance(raw.get("description"), str) else ""
    description = _markdown(description_html)
    covers = raw.get("thumbnailImageUrl")
    ratings = {"steam": raw["steamRating"]} if isinstance(raw.get("steamRating"), int | float) else {}
    return HumbleItem(
        machine_name=machine_name,
        title=title,
        item_type="game" if raw.get("bundleType") == "games" else (str(raw["bundleType"]) if raw.get("bundleType") else None),
        is_game=raw.get("bundleType") == "games",
        retail_price=amount_price(raw.get("msrp")),
        cover_art_url=_optional_url(covers),
        developers=_links(raw.get("developers")),
        publishers=_links(raw.get("publishers")),
        redeem_on=_redeem_on(raw.get("deliveryMethods")),
        platforms=_platforms(raw.get("platforms")),
        description=description,
        key_expiration_text=_expiration(description),
        rating=ratings,
        resolution=HumbleResolution(),
        edition_component_titles=_parse_edition_bundle_components(title, description_html),
    )
# end def _bundle_item_nextjs


def build_bundle_archive_nextjs(
    payload: Mapping[str, Any], crawled: datetime
) -> tuple[HumbleArchive, dict[str, Any]]:
    """Build the normalized archive and source dict from an `extract_bundle_payload_nextjs` result."""
    page = _required_mapping(payload.get("bundle_page"), "bundlePage")
    listing = _required_mapping(payload.get("listing"), "bundle listing")
    slug = _required_string(page.get("slug"), "bundle slug")
    tiers_raw = page.get("tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise HumbleParseError("bundlePage tiers must contain a non-empty list")
    # end if
    # The tier skus are `<productKey>_<identifier>` (`..._bundle_initial`, `..._bundle_bt15`), the listing names the key.
    first_sku = _required_string(_required_mapping(tiers_raw[0], "tier").get("sku"), "tier sku")
    product_key = _required_string(listing.get("productKey") or first_sku.rsplit("_", 1)[0], "bundle product key")
    tiers: list[HumbleTier] = []
    # The page lists the cheapest tier first; the archive (and every list) has the highest, "Entire" one first.
    for index, tier_value in enumerate(reversed(tiers_raw)):
        tier = _required_mapping(tier_value, "tier")
        sku = _required_string(tier.get("sku"), "tier sku")
        items_raw = tier.get("bundleItems")
        if not isinstance(items_raw, list):
            raise HumbleParseError(f"tier {sku} bundleItems must contain a list")
        # end if
        items = [_bundle_item_nextjs(_required_mapping(item, f"tier {sku} item"), product_key) for item in items_raw]
        tiers.append(
            HumbleTier(
                identifier=sku.removeprefix(f"{product_key}_"),
                name=f"Entire {len(items)} Item Bundle" if index == 0 else f"{len(items)} Item Bundle",
                item_count=len(items),
                minimum_price=amount_price(tier.get("price")),
                items=items,
            )
        )
    # end for
    charities: list[HumbleCharity] = []
    for charity in page.get("supportingCharities") or []:
        if not isinstance(charity, dict) or not isinstance(charity.get("name"), str):
            continue
        # end if
        charities.append(
            HumbleCharity(
                name=charity["name"],
                url=_optional_url(charity.get("url")),
                description=_markdown(charity.get("description")),
                logo_url=_optional_url(charity.get("logo")),
            )
        )
    # end for
    description = _markdown(page.get("details") or page.get("description"))
    name = _required_string(page.get("title"), "bundle title")
    archive = HumbleArchive(
        kind="bundle",
        machine_name=product_key,
        url=urljoin(HUMBLE_ROOT, f"games/{slug}"),
        name=name,
        headline=_required_string(page.get("headline") or name, "bundle headline"),
        description=description,
        dates=HumbleDates(
            start=_confidence(_datetime(page.get("startDate"), "bundle start date")),
            end=_confidence(_datetime(page.get("endDate") or listing.get("endDate"), "bundle end date")),
            crawled=crawled.astimezone(UTC),
        ),
        charities=charities,
        key_expiration_text=_expiration(description),
        tiers=tiers,
    )
    return archive, {"bundle_page": dict(page), "listing": dict(listing), "format": NEXTJS_FORMAT}
# end def build_bundle_archive_nextjs


def extract_choice_payload_nextjs(html: str) -> dict[str, Any]:
    """The plain-JSON payload this month's Choice archive is built from, back-references resolved."""
    rows = page_rows(html)
    for row in rows.values():
        products = find_key(row, "subscriptionProducts")
        if isinstance(products, list) and products:
            return {
                "kind": "choice",
                "format": NEXTJS_FORMAT,
                "products": resolve(products, rows),
                "page_description": _meta_description(rows),
            }
        # end if
    # end for
    raise HumbleParseError("Choice page is missing subscriptionProducts in its flight data")
# end def extract_choice_payload_nextjs


def _meta_description(rows: Mapping[str, Any]) -> str:
    """The page's `<meta name="description">`, which names the month and the monthly price."""
    for row in rows.values():
        if not isinstance(row, list):
            continue
        # end if
        for content in decode_meta(row):
            if CHOICE_DESCRIPTION_PATTERN.search(content):
                return content
            # end if
        # end for
    # end for
    raise HumbleParseError("Choice page has no 'Get <month> <year> Humble Choice' description")
# end def _meta_description


def decode_meta(value: object) -> list[str]:
    """Every `content` of a `["$", "meta", key, {"name": "description", "content": ...}]` element inside a row."""
    found: list[str] = []
    if isinstance(value, list):
        if len(value) > 3 and value[:2] == ["$", "meta"] and isinstance(value[3], dict):
            props = value[3]
            if props.get("name") == "description" and isinstance(props.get("content"), str):
                found.append(props["content"])
            # end if
        # end if
        for child in value:
            found.extend(decode_meta(child))
        # end for
    elif isinstance(value, dict):
        for child in value.values():
            found.extend(decode_meta(child))
        # end for
    # end if
    return found
# end def decode_meta


def build_choice_archive_nextjs(
    payload: Mapping[str, Any], crawled: datetime
) -> tuple[HumbleArchive, dict[str, Any]]:
    """Build the normalized archive and source dict from an `extract_choice_payload_nextjs` result."""
    description = _required_string(payload.get("page_description"), "Choice page description")
    match = CHOICE_DESCRIPTION_PATTERN.search(description)
    if match is None:
        raise HumbleParseError(f"Choice description has an unexpected shape: {description}")
    # end if
    month, year = match.group("month"), match.group("year")
    products = payload.get("products")
    if not isinstance(products, list):
        raise HumbleParseError("Choice products must contain a list")
    # end if
    items: list[HumbleItem] = []
    for value in products:
        raw = _required_mapping(value, "Choice product")
        machine_name = _required_string(raw.get("id"), "Choice product id")
        title = _required_string(raw.get("title"), f"Choice item {machine_name} title")
        redeem_on = _redeem_on(raw.get("deliveryMethods"))
        delivery = {str(method).casefold() for method in raw.get("deliveryMethods") or []}
        is_coupon = "coupon" in machine_name.casefold() or "coupon" in title.casefold() or bool(delivery & NON_STORE_DELIVERY)
        tags = ["coupon"] if is_coupon else []
        text = _markdown(raw.get("description"))
        genres = raw.get("genres")
        items.append(
            HumbleItem(
                machine_name=machine_name,
                title=title,
                item_type="game" if redeem_on else "bonus",
                is_game=bool(redeem_on) and "coupon" not in tags,
                retail_price=cent_price(_required_mapping(raw.get("displayPrice") or {}, "price").get("currentPrice")),
                cover_art_url=_optional_url(raw.get("thumbnail")),
                developers=_links(raw.get("developers")),
                redeem_on=redeem_on,
                platforms=_platforms(raw.get("platforms")),
                description=text,
                key_expiration_text=_expiration(text),
                tags=tags,
                genres=[str(genre) for genre in genres] if isinstance(genres, list) else [],
                resolution=HumbleResolution(),
            )
        )
    # end for
    price_raw = match.group("price")
    symbol = re.match(r"[^\d]+", price_raw)
    price = (
        HumblePrice(
            raw=price_raw,
            value=float(re.sub(r"[^\d.]", "", price_raw)),
            currency=symbol.group(0),
            currency_code=SYMBOL_CURRENCY_CODES.get(symbol.group(0), symbol.group(0)),
        )
        if symbol is not None
        else None
    )
    name = f"{month} {year} Humble Choice"
    archive = HumbleArchive(
        kind="choice",
        machine_name=f"{month.casefold()}_{year}_choice",
        url=urljoin(HUMBLE_ROOT, "membership"),
        name=name,
        headline=name,
        description=description,
        dates=HumbleDates(crawled=crawled.astimezone(UTC)),
        tiers=[HumbleTier(identifier="choice", name=name, item_count=len(items), minimum_price=price, items=items)],
    )
    return archive, {"products": payload["products"], "page_description": description, "format": NEXTJS_FORMAT}
# end def build_choice_archive_nextjs
