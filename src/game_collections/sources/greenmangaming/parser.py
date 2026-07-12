"""Parse the server-rendered HTML pages served by greenmangaming(bundles).com."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

from game_collections.sources.greenmangaming.models import (
    GmgArchive,
    GmgDates,
    GmgItem,
    GmgPrice,
    GmgResolution,
    GmgTier,
)
from game_collections.sources.greenmangaming.resolver import redeem_on_for_drm


GMG_ROOT = "https://www.greenmangaming.com/"
GMG_BUNDLES_ROOT = "https://www.greenmangamingbundles.com/"

# Bundle detail pages only ever advertise "video-games" as a relevant
# category for this project alongside "books-comics" and "software", which
# are ignored the same way Humble's Books/Software categories are.
RELEVANT_CATEGORY = "video-games"

ITEM_PATTERN = re.compile(
    r'<figure[^>]*hx-get="(/bundles/[a-z0-9-]+/product/(\d+)/)"'
    r'[^>]*hx-vals=\'(\{[^\']*\})\'.*?'
    r'<strong class="game-title">(.*?)</strong>',
    re.IGNORECASE | re.DOTALL,
)
RADIO_CARD_PATTERN = re.compile(
    r"<label[^>]*data-bundle-radio-card[^>]*>(.*?)</label>",
    re.IGNORECASE | re.DOTALL,
)
TIER_ID_PATTERN = re.compile(r'data-upgrade-tier-id="([^"]+)"')
TIER_VALUE_PATTERN = re.compile(r'value="([a-z0-9-]+):([\d.,]+)"')
TIER_NAME_PATTERN = re.compile(r'<span class="bundle-type[^"]*">([^<]+)</span>')
TIER_ITEM_COUNT_PATTERN = re.compile(r"<small>\s*(\d+)\s*Items?\s*</small>")
TIER_PRICE_PATTERN = re.compile(r'<span class="price">([^<]+)</span>')
CURRENCY_INPUT_PATTERN = re.compile(r'name="currency_code"\s+value="([^"]+)"')
H1_PATTERN = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


class GmgParseError(ValueError):
    """A Green Man Gaming page did not contain the expected structure."""

# end class GmgParseError


def _strip_tags(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
# end def _strip_tags


class _ProductCardParser(HTMLParser):
    """Collect (category, detail_url) pairs from the bundles index page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[tuple[str, str]] = []
        self._depth = 0
        self._card_depth: int | None = None
        self._category: str | None = None
        self._href: str | None = None
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "div":
            self._depth += 1
            classes = (values.get("class") or "").split()
            if self._card_depth is None and "product-card" in classes:
                self._card_depth = self._depth
                self._category = values.get("data-category")
                self._href = None
            # end if
        # end if
        if tag == "a" and self._card_depth is not None and self._href is None:
            classes = (values.get("class") or "").split()
            if "cta-button" in classes and values.get("href"):
                self._href = values["href"]
            # end if
        # end if
    # end def handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        # end if
        if self._card_depth is not None and self._depth == self._card_depth:
            if self._category is not None and self._href is not None:
                self.cards.append((self._category, self._href))
            # end if
            self._card_depth = None
            self._category = None
            self._href = None
        # end if
        self._depth -= 1
    # end def handle_endtag

# end class _ProductCardParser


def parse_bundle_index_page(html: str) -> list[str]:
    """Return the video-games bundle slugs currently listed on the index."""
    parser = _ProductCardParser()
    parser.feed(html)
    if not parser.cards:
        raise GmgParseError("bundles index page has no product cards")
    # end if
    slugs: list[str] = []
    seen: set[str] = set()
    for category, href in parser.cards:
        if category != RELEVANT_CATEGORY:
            continue
        # end if
        absolute = urljoin(GMG_BUNDLES_ROOT, href)
        path_parts = [part for part in urlparse(absolute).path.split("/") if part]
        if len(path_parts) < 2 or path_parts[0] != "bundles":
            raise GmgParseError(f"unexpected bundle detail URL: {absolute}")
        # end if
        slug = path_parts[1]
        if slug in seen:
            continue
        # end if
        seen.add(slug)
        slugs.append(slug)
    # end for
    return slugs
# end def parse_bundle_index_page


def bundle_url(slug: str) -> str:
    """Return the canonical bundle detail page URL for a slug."""
    return f"{GMG_BUNDLES_ROOT}bundles/{slug}/"
# end def bundle_url


def _tier_price(raw: str, currency_code: str, label: str) -> GmgPrice:
    match = re.match(r"([^\d]*)([\d.,]+)$", raw.strip())
    if not match:
        raise GmgParseError(f"{label} is not a recognizable price: {raw!r}")
    # end if
    symbol, amount_text = match.groups()
    try:
        value = float(amount_text.replace(",", ""))
    except ValueError as error:
        raise GmgParseError(f"{label} is not a number: {raw!r}") from error
    # end try
    symbol = symbol.strip() or currency_code
    return GmgPrice(raw=raw.strip(), value=value, currency=symbol, currency_code=currency_code)
# end def _tier_price


def parse_bundle_page(html: str, slug: str, crawled: datetime) -> tuple[GmgArchive, dict[str, Any]]:
    """Normalize one Green Man Gaming bundle detail page.

    Every item on the default render is shown "unlocked", tagged with the
    `tier_name` (from its `hx-vals`) it originally belongs to - so tiers are
    built by grouping items by that tag and accumulating in ascending price
    order, without needing extra `switch_tier` requests (confirmed against
    the live site: `switch_tier` responses for lower tiers return exactly
    the same cumulative sets this grouping produces).
    """
    title_match = H1_PATTERN.search(html)
    if not title_match:
        raise GmgParseError(f"bundle page is missing its <h1> title: {slug}")
    # end if
    name = _strip_tags(title_match.group(1))
    if not name:
        raise GmgParseError(f"bundle page title is empty: {slug}")
    # end if
    currency_match = CURRENCY_INPUT_PATTERN.search(html)
    if not currency_match:
        raise GmgParseError(f"bundle page is missing its currency_code field: {slug}")
    # end if
    currency_code = currency_match.group(1)

    items_by_tier_name: dict[str, list[GmgItem]] = {}
    seen_product_ids: set[str] = set()
    for match in ITEM_PATTERN.finditer(html):
        product_id = match.group(2)
        if product_id in seen_product_ids:
            continue
        # end if
        seen_product_ids.add(product_id)
        try:
            hx_vals = json.loads(match.group(3))
        except json.JSONDecodeError as error:
            raise GmgParseError(f"bundle item {product_id} has invalid hx-vals JSON: {error}") from error
        # end try
        tier_name = hx_vals.get("tier_name")
        if not isinstance(tier_name, str) or not tier_name:
            raise GmgParseError(f"bundle item {product_id} is missing its tier_name: {slug}")
        # end if
        title = _strip_tags(match.group(4))
        if not title:
            raise GmgParseError(f"bundle item {product_id} has an empty title: {slug}")
        # end if
        items_by_tier_name.setdefault(tier_name, []).append(
            GmgItem(product_id=product_id, title=title, resolution=GmgResolution())
        )
    # end for
    if not items_by_tier_name:
        raise GmgParseError(f"bundle page has no bundle items: {slug}")
    # end if

    tiers: list[GmgTier] = []
    cumulative: list[GmgItem] = []
    seen_tier_names: set[str] = set()
    for radio_match in RADIO_CARD_PATTERN.finditer(html):
        block = radio_match.group(1)
        identifier_match = TIER_ID_PATTERN.search(block)
        if identifier_match is None:
            # The pay-what-you-want "custom amount" card has no
            # data-upgrade-tier-id - it isn't a fixed tier, skip it.
            continue
        # end if
        identifier = identifier_match.group(1)
        name_match = TIER_NAME_PATTERN.search(block)
        count_match = TIER_ITEM_COUNT_PATTERN.search(block)
        price_match = TIER_PRICE_PATTERN.search(block)
        if not name_match or not count_match or not price_match:
            raise GmgParseError(f"tier {identifier} is missing name/item-count/price: {slug}")
        # end if
        tier_name = name_match.group(1).strip()
        if tier_name in seen_tier_names:
            continue
        # end if
        seen_tier_names.add(tier_name)
        item_count = int(count_match.group(1))
        new_items = items_by_tier_name.get(tier_name)
        if new_items is None:
            raise GmgParseError(f"tier {tier_name!r} has no matching bundle items: {slug}")
        # end if
        cumulative = [*cumulative, *new_items]
        if len(cumulative) != item_count:
            raise GmgParseError(
                f"tier {tier_name!r} advertises {item_count} items but grouping produced "
                f"{len(cumulative)}: {slug}"
            )
        # end if
        tiers.append(
            GmgTier(
                identifier=identifier,
                name=tier_name,
                item_count=item_count,
                price=_tier_price(price_match.group(1), currency_code, f"tier {tier_name} price"),
                items=list(cumulative),
            )
        )
    # end for
    if not tiers:
        raise GmgParseError(f"bundle page has no tier-selector radio cards: {slug}")
    # end if
    total_grouped = sum(len(items) for items in items_by_tier_name.values())
    if total_grouped != len(cumulative):
        raise GmgParseError(f"bundle page has items not covered by any tier: {slug}")
    # end if

    archive = GmgArchive(
        schema=1,
        slug=slug,
        url=bundle_url(slug),
        name=name,
        currency_code=currency_code,
        dates=GmgDates(end=None, crawled=crawled.astimezone(UTC)),
        tiers=tiers,
    )
    return archive, {"title_text": title_match.group(0)}
# end def parse_bundle_page


DRM_PATTERN = re.compile(r"<dt>DRM</dt>\s*<dd>\s*(.*?)\s*</dd>", re.IGNORECASE | re.DOTALL)
PLATFORM_PATTERN = re.compile(r"<dt>Platform</dt>\s*<dd>\s*(.*?)\s*</dd>", re.IGNORECASE | re.DOTALL)
DEVELOPER_PATTERN = re.compile(r"<dt>Developer</dt>\s*<dd>\s*(.*?)\s*</dd>", re.IGNORECASE | re.DOTALL)
PUBLISHER_PATTERN = re.compile(r"<dt>Publisher</dt>\s*<dd>\s*(.*?)\s*</dd>", re.IGNORECASE | re.DOTALL)
DESCRIPTION_PATTERN = re.compile(
    r'id="gameDescriptionCollapse-\d+"[^>]*>(.*?)</section>', re.IGNORECASE | re.DOTALL
)


def parse_product_fragment(html: str, product_id: str) -> dict[str, Any]:
    """Extract one bundle item's DRM/platform/developer/publisher/description."""
    drm_match = DRM_PATTERN.search(html)
    if not drm_match:
        raise GmgParseError(f"product fragment {product_id} is missing its DRM field")
    # end if
    drm = _strip_tags(drm_match.group(1)) or None
    platform_match = PLATFORM_PATTERN.search(html)
    developer_match = DEVELOPER_PATTERN.search(html)
    publisher_match = PUBLISHER_PATTERN.search(html)
    description_match = DESCRIPTION_PATTERN.search(html)
    return {
        "drm": drm,
        "platform": _strip_tags(platform_match.group(1)) if platform_match else None,
        "developer": _strip_tags(developer_match.group(1)) if developer_match else None,
        "publisher": _strip_tags(publisher_match.group(1)) if publisher_match else None,
        "description": _strip_tags(description_match.group(1)) if description_match else "",
        "redeem_on": redeem_on_for_drm(drm),
    }
# end def parse_product_fragment
