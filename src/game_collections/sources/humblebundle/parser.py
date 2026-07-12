"""Parse structured metadata embedded in public Humble pages."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from markdownify import markdownify

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


HUMBLE_ROOT = "https://www.humblebundle.com/"
EXPIRATION_PATTERN = re.compile(
    r"Keys? expire(?:s)?\.?\s*Please redeem(?: your key)? before [^.]+\.",
    re.IGNORECASE,
)
CURRENCY_SYMBOLS = {
    "AUD": "A$",
    "BRL": "R$",
    "CAD": "C$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
    "USD": "$",
}
STORE_NAMES = {
    "epic": "epic",
    "gog": "gog",
    "hb-epic": "epic",
    "hb-gog": "gog",
    "hb-steam": "steam",
    "hb-uplay": "ubisoft",
    "steam": "steam",
    "uplay": "ubisoft",
    "ubisoft": "ubisoft",
}


class HumbleParseError(ValueError):
    """A Humble page did not contain the expected structured data."""

# end class HumbleParseError


class _EmbeddedDataParser(HTMLParser):
    """Collect selected script contents and JSON-bearing attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._script_key: str | None = None
        self._script_parts: list[str] = []
        self.scripts: dict[str, str] = {}
        self.json_ld: list[str] = []
        self.attributes: dict[str, str] = {}
        self.machine_names: list[str] = []
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script":
            script_id = values.get("id")
            script_type = values.get("type")
            if script_id is not None:
                self._script_key = script_id
            elif script_type == "application/ld+json":
                self._script_key = "__json_ld__"
            else:
                self._script_key = None
            # end if
            self._script_parts = []
        # end if
        for name in ("data-content-choice-data", "data-charity"):
            value = values.get(name)
            if value and name not in self.attributes:
                self.attributes[name] = value
            # end if
        # end for
        machine_name = values.get("data-machine-name")
        if machine_name and machine_name not in self.machine_names:
            self.machine_names.append(machine_name)
        # end if
    # end def handle_starttag

    def handle_data(self, data: str) -> None:
        if self._script_key is not None:
            self._script_parts.append(data)
        # end if
    # end def handle_data

    def handle_endtag(self, tag: str) -> None:
        if tag != "script" or self._script_key is None:
            return
        # end if
        text = "".join(self._script_parts).strip()
        if self._script_key == "__json_ld__":
            self.json_ld.append(text)
        else:
            self.scripts[self._script_key] = text
        # end if
        self._script_key = None
        self._script_parts = []
    # end def handle_endtag

# end class _EmbeddedDataParser


def _embedded(html: str) -> _EmbeddedDataParser:
    parser = _EmbeddedDataParser()
    parser.feed(html)
    return parser
# end def _embedded


def _json_object(raw: str, label: str) -> dict[str, Any]:
    try:
        value: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise HumbleParseError(f"invalid {label} JSON: {error}") from error
    # end try
    if not isinstance(value, dict):
        raise HumbleParseError(f"{label} JSON must contain an object")
    # end if
    return value
# end def _json_object


def _required_mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HumbleParseError(f"{label} must contain an object")
    # end if
    return value
# end def _required_mapping


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HumbleParseError(f"{label} must contain a non-empty string")
    # end if
    return value.strip()
# end def _required_string


def _markdown(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    # end if
    converted = markdownify(
        value,
        heading_style="atx",
        bullets="-",
        newline_style="backslash",
        strip_document="strip",
    )
    lines = [line.rstrip() for line in converted.splitlines()]
    result: list[str] = []
    blank = False
    for line in lines:
        if not line:
            if result and not blank:
                result.append("")
            # end if
            blank = True
            continue
        # end if
        result.append(line)
        blank = False
    # end for
    return "\n".join(result).strip()
# end def _markdown


def _expiration(markdown: str) -> str | None:
    match = EXPIRATION_PATTERN.search(markdown)
    if not match:
        return None
    # end if
    return " ".join(match.group(0).split())
# end def _expiration


def _datetime(value: object, label: str) -> datetime | None:
    if value is None:
        return None
    # end if
    raw = _required_string(value, label)
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    # end if
    return parsed.astimezone(UTC)
# end def _datetime


def _price(value: object, raw: str | None = None) -> HumblePrice | None:
    if value is None:
        return None
    # end if
    money = _required_mapping(value, "money")
    currency_code = _required_string(money.get("currency"), "money currency").upper()
    amount = money.get("amount")
    if not isinstance(amount, int | float):
        raise HumbleParseError("money amount must be numeric")
    # end if
    symbol = CURRENCY_SYMBOLS.get(currency_code, currency_code)
    rendered = raw or f"{symbol}{amount:.2f}"
    return HumblePrice(
        raw=rendered,
        value=float(amount),
        currency=symbol,
        currency_code=currency_code,
    )
# end def _price


def _links(value: object, name_key: str, url_key: str) -> list[HumbleLink]:
    if not isinstance(value, list):
        return []
    # end if
    links: list[HumbleLink] = []
    for raw in value:
        if not isinstance(raw, dict) or not isinstance(raw.get(name_key), str):
            continue
        # end if
        url = raw.get(url_key) if isinstance(raw.get(url_key), str) else None
        links.append(HumbleLink(name=raw[name_key], url=url))
    # end for
    return links
# end def _links


def _bundle_item(machine_name: str, value: object) -> HumbleItem:
    raw = _required_mapping(value, f"bundle item {machine_name}")
    badge = raw.get("cta_badge")
    tags: list[str] = []
    if isinstance(badge, dict) and isinstance(badge.get("badge"), str):
        tags.append(badge["badge"].title())
    # end if
    description = _markdown(raw.get("description_text"))
    platforms_and_oses = raw.get("platforms_and_oses")
    game_platforms: dict[str, Any] = {}
    if isinstance(platforms_and_oses, dict) and isinstance(platforms_and_oses.get("game"), dict):
        game_platforms = platforms_and_oses["game"]
    # end if
    redeem_on = sorted(
        {
            STORE_NAMES.get(str(store).casefold(), str(store).casefold())
            for store in game_platforms
        }
    )
    availability = raw.get("availability_icons")
    if isinstance(availability, dict) and isinstance(availability.get("delivery_icons"), list):
        redeem_on = sorted(
            set(redeem_on)
            | {
                STORE_NAMES.get(str(store).casefold(), str(store).removeprefix("hb-").casefold())
                for store in availability["delivery_icons"]
            }
        )
    # end if
    platforms = sorted(
        {
            str(platform).title()
            for values in game_platforms.values()
            if isinstance(values, list)
            for platform in values
        }
    )
    paths = raw.get("resolved_paths")
    cover: str | None = None
    if isinstance(paths, dict):
        for key in ("featured_image", "preview_image", "front_page_art_imgix"):
            if isinstance(paths.get(key), str) and paths[key]:
                cover = paths[key]
                break
            # end if
        # end for
    # end if
    youtube = raw.get("youtube_link")
    youtube_urls = [f"https://www.youtube.com/watch?v={youtube}"] if isinstance(youtube, str) else []
    item_type = raw.get("item_content_type") if isinstance(raw.get("item_content_type"), str) else None
    is_game = item_type == "game" and "Coupon" not in tags
    rating = raw.get("user_ratings") if isinstance(raw.get("user_ratings"), dict) else {}
    excluded = raw.get("exclusive_countries")
    return HumbleItem(
        machine_name=machine_name,
        title=_required_string(raw.get("human_name"), f"item {machine_name} title"),
        item_type=item_type,
        is_game=is_game,
        retail_price=_price(raw.get("msrp_price|money")),
        youtube_urls=youtube_urls,
        cover_art_url=cover,
        developers=_links(raw.get("developers"), "developer-name", "developer-url"),
        publishers=_links(raw.get("publishers"), "publisher-name", "publisher-url"),
        redeem_on=redeem_on,
        platforms=platforms,
        description=description,
        key_expiration_text=_expiration(description),
        tags=tags,
        rating=rating,
        region_locked=raw.get("is_region_locked") if isinstance(raw.get("is_region_locked"), bool) else None,
        excluded_countries=[str(item) for item in excluded] if isinstance(excluded, list) else [],
        resolution=HumbleResolution(),
    )
# end def _bundle_item


def parse_bundle_index(html: str) -> list[dict[str, Any]]:
    """Return active Games records from the Humble bundles landing page."""
    parser = _embedded(html)
    raw = parser.scripts.get("landingPage-json-data")
    if raw is None:
        raise HumbleParseError("bundles page is missing landingPage-json-data")
    # end if
    root = _json_object(raw, "bundles landing page")
    data = _required_mapping(root.get("data"), "bundles landing data")
    games = _required_mapping(data.get("games"), "bundles Games category")
    mosaic = games.get("mosaic")
    if not isinstance(mosaic, list):
        raise HumbleParseError("bundles Games mosaic must contain a list")
    # end if
    products: list[dict[str, Any]] = []
    for section in mosaic:
        if not isinstance(section, dict) or not isinstance(section.get("products"), list):
            continue
        # end if
        for product in section["products"]:
            if isinstance(product, dict) and str(product.get("product_url", "")).startswith("/games/"):
                products.append(product)
            # end if
        # end for
    # end for
    return products
# end def parse_bundle_index


def parse_bundle_page(
    html: str,
    listing: Mapping[str, Any] | None,
    crawled: datetime,
) -> tuple[HumbleArchive, dict[str, Any]]:
    """Normalize one Games bundle detail page and its optional index record."""
    parser = _embedded(html)
    raw = parser.scripts.get("webpack-bundle-page-data")
    if raw is None:
        raise HumbleParseError("bundle page is missing webpack-bundle-page-data")
    # end if
    root = _json_object(raw, "bundle page")
    bundle = _required_mapping(root.get("bundleData"), "bundleData")
    basic = _required_mapping(bundle.get("basic_data"), "bundle basic_data")
    page_url = _required_string(bundle.get("page_url"), "bundle page_url")
    description = _markdown(basic.get("detailed_marketing_blurb") or basic.get("description"))
    items_raw = _required_mapping(bundle.get("tier_item_data"), "bundle tier_item_data")
    all_items = {name: _bundle_item(name, value) for name, value in items_raw.items()}
    display = _required_mapping(bundle.get("tier_display_data"), "bundle tier_display_data")
    pricing = _required_mapping(bundle.get("tier_pricing_data"), "bundle tier_pricing_data")
    order = bundle.get("tier_order")
    if not isinstance(order, list) or not order:
        raise HumbleParseError("bundle tier_order must contain a non-empty list")
    # end if
    tiers: list[HumbleTier] = []
    for index, identifier_value in enumerate(order):
        identifier = _required_string(identifier_value, "tier identifier")
        tier_display = _required_mapping(display.get(identifier), f"tier display {identifier}")
        names = tier_display.get("tier_item_machine_names")
        if not isinstance(names, list):
            raise HumbleParseError(f"tier {identifier} item names must contain a list")
        # end if
        try:
            tier_items = [all_items[_required_string(name, "tier item machine name")] for name in names]
        except KeyError as error:
            raise HumbleParseError(f"tier references unknown item: {error.args[0]}") from error
        # end try
        item_count = len(tier_items)
        tier_name = f"Entire {item_count} Item Bundle" if index == 0 else f"{item_count} Item Bundle"
        tier_price = _required_mapping(pricing.get(identifier), f"tier pricing {identifier}")
        header = tier_display.get("header")
        raw_price: str | None = None
        if isinstance(header, str):
            match = re.search(r"(?:Pay\s+)?([^ ]+\d(?:[\d.,]*))(?:\s+or more)?", header)
            raw_price = match.group(1) if match else None
        # end if
        tiers.append(
            HumbleTier(
                identifier=identifier,
                name=tier_name,
                item_count=item_count,
                minimum_price=_price(tier_price.get("price|money"), raw_price),
                items=tier_items,
            )
        )
    # end for
    listing_data = dict(listing) if listing is not None else {}
    charities: list[HumbleCharity] = []
    charity_data = bundle.get("charity_data")
    if isinstance(charity_data, dict) and isinstance(charity_data.get("charity_items"), dict):
        for charity in charity_data["charity_items"].values():
            if not isinstance(charity, dict):
                continue
            # end if
            info = charity.get("ppgf_info") if isinstance(charity.get("ppgf_info"), dict) else {}
            name = info.get("human_name") or charity.get("human_name")
            if not isinstance(name, str):
                continue
            # end if
            charities.append(
                HumbleCharity(
                    name=name,
                    url=info.get("url") if isinstance(info.get("url"), str) else None,
                    description=_markdown(info.get("description") or charity.get("description_text")),
                    logo_url=info.get("logo_url") if isinstance(info.get("logo_url"), str) else None,
                )
            )
        # end for
    # end if
    archive = HumbleArchive(
        schema=1,
        kind="bundle",
        machine_name=_required_string(bundle.get("machine_name"), "bundle machine_name"),
        url=urljoin(HUMBLE_ROOT, page_url),
        headline=_required_string(
            basic.get("short_marketing_blurb") or basic.get("human_name"),
            "bundle headline",
        ),
        description=description,
        dates=HumbleDates(
            start=_datetime(listing_data.get("start_date|datetime"), "bundle start date"),
            end=_datetime(
                listing_data.get("end_date|datetime") or basic.get("end_time|datetime"),
                "bundle end date",
            ),
            crawled=crawled.astimezone(UTC),
        ),
        charities=charities,
        key_expiration_text=_expiration(description),
        tiers=tiers,
    )
    return archive, {"bundle_data": bundle, "listing": listing_data}
# end def parse_bundle_page


def _product_json_ld(parser: _EmbeddedDataParser) -> dict[str, Any]:
    for raw in parser.json_ld:
        value = _json_object(raw, "JSON-LD")
        if value.get("@type") == "Product":
            return value
        # end if
    # end for
    raise HumbleParseError("Choice page is missing Product JSON-LD")
# end def _product_json_ld


def parse_choice_page(html: str, crawled: datetime) -> tuple[HumbleArchive, dict[str, Any]]:
    """Normalize the active Humble Choice page."""
    parser = _embedded(html)
    content_raw = parser.attributes.get("data-content-choice-data")
    marketing_raw = parser.scripts.get("webpack-choice-marketing-data")
    if content_raw is None or marketing_raw is None:
        raise HumbleParseError("Choice page is missing content or marketing JSON")
    # end if
    content = _json_object(content_raw, "Choice content")
    marketing = _json_object(marketing_raw, "Choice marketing")
    product = _product_json_ld(parser)
    charity: dict[str, Any] = {}
    charity_raw = parser.attributes.get("data-charity")
    if charity_raw is not None:
        charity = _json_object(charity_raw, "Choice charity")
    # end if
    items: list[HumbleItem] = []
    ordered_names = [name for name in parser.machine_names if name in content]
    ordered_names.extend(name for name in content if name not in ordered_names)
    for machine_name in ordered_names:
        raw = _required_mapping(content[machine_name], f"Choice item {machine_name}")
        delivery = raw.get("delivery_methods") if isinstance(raw.get("delivery_methods"), list) else []
        redeem_on = sorted(
            {
                STORE_NAMES.get(str(store).casefold(), str(store).casefold())
                for store in delivery
                if str(store).casefold() != "other-key"
            }
        )
        title = _required_string(raw.get("title"), f"Choice item {machine_name} title")
        tags = ["Coupon"] if "coupon" in machine_name.casefold() or "coupon" in title.casefold() else []
        description = _markdown(
            raw.get("recommendation_copy_dict", {}).get("copy")
            if isinstance(raw.get("recommendation_copy_dict"), dict)
            else None
        )
        youtube_values = raw.get("youtube_links") if isinstance(raw.get("youtube_links"), list) else []
        items.append(
            HumbleItem(
                machine_name=machine_name,
                title=title,
                item_type="game" if redeem_on else "bonus",
                is_game=bool(redeem_on) and "Coupon" not in tags,
                retail_price=_price(raw.get("msrp")),
                youtube_urls=[f"https://www.youtube.com/watch?v={video}" for video in youtube_values],
                cover_art_url=raw.get("image") if isinstance(raw.get("image"), str) else None,
                redeem_on=redeem_on,
                platforms=[str(item).title() for item in raw.get("platforms", [])]
                if isinstance(raw.get("platforms"), list)
                else [],
                description=description,
                key_expiration_text=_expiration(description),
                tags=tags,
                genres=[str(item) for item in raw.get("genres", [])]
                if isinstance(raw.get("genres"), list)
                else [],
                rating=raw.get("user_rating") if isinstance(raw.get("user_rating"), dict) else {},
                resolution=HumbleResolution(),
            )
        )
    # end for
    offers = _required_mapping(product.get("offers"), "Choice JSON-LD offers")
    description = _markdown(product.get("description"))
    charities = []
    if isinstance(charity.get("charity_name"), str):
        charities.append(
            HumbleCharity(
                name=charity["charity_name"],
                description=_markdown(charity.get("charity_description")),
                logo_url=charity.get("charity_logo") if isinstance(charity.get("charity_logo"), str) else None,
            )
        )
    # end if
    price = _price(marketing.get("baseSubscriptionPrice|money"))
    tier_name = _required_string(product.get("name"), "Choice product name")
    archive = HumbleArchive(
        schema=1,
        kind="choice",
        machine_name=_required_string(
            marketing.get("activeContentMachineName") or product.get("sku"),
            "Choice machine name",
        ),
        url=_required_string(product.get("url"), "Choice URL"),
        headline=tier_name,
        description=description,
        dates=HumbleDates(
            start=_datetime(offers.get("validFrom"), "Choice start date"),
            end=_datetime(offers.get("validThrough"), "Choice end date"),
            crawled=crawled.astimezone(UTC),
        ),
        charities=charities,
        key_expiration_text=None,
        tiers=[
            HumbleTier(
                identifier="choice",
                name=tier_name,
                item_count=len(items),
                minimum_price=price,
                items=items,
            )
        ],
    )
    return archive, {
        "charity": charity,
        "choice_content": content,
        "choice_marketing": marketing,
        "product_json_ld": product,
    }
# end def parse_choice_page
