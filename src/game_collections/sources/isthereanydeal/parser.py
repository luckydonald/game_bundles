"""Parse isthereanydeal.com's bootstrap page, list API, and bundle detail pages."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag

from game_collections.sources.isthereanydeal.models import ItadItem, ItadListSummary, ItadPrice, ItadTier
from game_collections.sources.storefronts import STORE_ROOTS, StoreName, parse_store_identity


class ItadParseError(ValueError):
    """An isthereanydeal.com page or API response did not have the expected shape."""

# end class ItadParseError


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


def _strip_tags(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
# end def _strip_tags


TOKEN_PATTERN = re.compile(r'"token"\s*:\s*"([^"]+)"')
SHOPS_KEY_PATTERN = re.compile(r'"shops"\s*:\s*')

# Every bundle detail page ships one shared inline script declaring both
# `var g = {...}` (token/shops/theme config) and `var page = [...]` (this
# page's own SSR'd state) - confirmed live, both assignments live in the same
# <script> tag. The anonymous bootstrap index page (`/bundles/`) carries the
# same script (it has its own `var page` too, for its listing state), but a
# script with only `var g` (no `var page`) is also valid, so the shared
# lookup matches either.
_BOOTSTRAP_SCRIPT_PATTERN = re.compile(r"var (?:g|page)\s*=")
_PAGE_SCRIPT_PATTERN = re.compile(r"var page\s*=")


def _find_page_script(html: str) -> str | None:
    """Return the text of the shared `var g`/`var page` bootstrap script, if present."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", string=_BOOTSTRAP_SCRIPT_PATTERN)
    if script is None:
        return None
    # end if
    return script.string if script.string is not None else script.get_text()
# end def _find_page_script


def _extract_balanced(text: str, start: int, open_char: str, close_char: str) -> str:
    """Return the `open_char...close_char` block beginning at `start`, matching nesting."""
    if start >= len(text) or text[start] != open_char:
        raise ItadParseError(f"expected {open_char!r} while extracting a balanced block")
    # end if
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escape:
                escape = False
            elif character == "\\":
                escape = True
            elif character == '"':
                in_string = False
            # end if
            continue
        # end if
        if character == '"':
            in_string = True
        elif character == open_char:
            depth += 1
        elif character == close_char:
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
            # end if
        # end if
    # end for
    raise ItadParseError(f"unterminated {open_char!r} while extracting a balanced block")
# end def _extract_balanced


def parse_bootstrap_page(html: str) -> tuple[str, dict[int, str]]:
    """Extract the anonymous session token and shop-id->name table from `/bundles/`.

    Both are embedded in an inline bootstrap script every anonymous visitor
    receives (`var g = {..., "shops": {"<id>": ["<name>", <flag>], ...}, ...,
    "token": "..."}`) - this is ordinary page scraping, not session/credential
    handling: the token is a plain anonymous CSRF-style value issued to any
    visitor, identical in value to the `sess2` cookie set on the same request.
    """
    text = _find_page_script(html)
    if text is None:
        raise ItadParseError("bootstrap page is missing its session token")
    # end if
    token_match = TOKEN_PATTERN.search(text)
    if not token_match:
        raise ItadParseError("bootstrap page is missing its session token")
    # end if
    shops_key_match = SHOPS_KEY_PATTERN.search(text)
    if not shops_key_match:
        raise ItadParseError("bootstrap page is missing its shops table")
    # end if
    brace_start = text.index("{", shops_key_match.end() - 1)
    raw_object = _extract_balanced(text, brace_start, "{", "}")
    try:
        parsed = json.loads(raw_object)
    except json.JSONDecodeError as error:
        raise ItadParseError(f"bootstrap page shops table is not valid JSON: {error}") from error
    # end try
    shop_names: dict[int, str] = {}
    for key, value in parsed.items():
        if not isinstance(value, list) or not value or not isinstance(value[0], str):
            raise ItadParseError(f"bootstrap page shop entry {key!r} has an unexpected shape")
        # end if
        try:
            shop_id = int(key)
        except ValueError as error:
            raise ItadParseError(f"bootstrap page shop id is not numeric: {key!r}") from error
        # end try
        shop_names[shop_id] = value[0]
    # end for
    return token_match.group(1), shop_names
# end def parse_bootstrap_page


def parse_list_page(raw: dict[str, Any]) -> tuple[bool, list[ItadListSummary]]:
    """Validate one page of `POST /bundles/api/list/` results."""
    if "done" not in raw or "data" not in raw:
        raise ItadParseError("list API response is missing 'done'/'data'")
    # end if
    done = raw["done"]
    data = raw["data"]
    if not isinstance(done, bool) or not isinstance(data, list):
        raise ItadParseError("list API response has an unexpected 'done'/'data' shape")
    # end if
    summaries = [ItadListSummary.model_validate(_without_tiers_preview(entry)) for entry in data]
    return done, summaries
# end def parse_list_page


def _without_tiers_preview(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop the list API's embedded tier/game preview before strict validation.

    Each summary entry also embeds a full tiers-with-games-with-shop-keys
    preview (price, per-game ITAD-internal id/slug/assets/platforms/DRM-free
    flag) - a higher-churn, ITAD-internal duplicate of the same tier/price
    data the detail page gives with real storefront IDs. `ItadListSummary`
    intentionally does not model it: it's unused (the detail page is the
    source of truth for tiers/games here) and would make every crawl brittle
    against ITAD's asset/platform/type enum churn for no benefit.
    """
    return {key: value for key, value in entry.items() if key != "tiers"}
# end def _without_tiers_preview


# Different bundle providers go through different affiliate networks: Humble
# and GreenManGaming links seen so far wrap the real URL in a `u=` parameter
# (impact.com-style), Fanatical's go through Awin (`ued=`), and IndieGala's
# `url` field is already the real, unwrapped provider link with no redirect
# at all.
_REDIRECT_URL_PARAMS: tuple[str, ...] = ("u", "ued")


def real_provider_url(redirect_url: str) -> str:
    """Decode the actual provider URL from an ITAD affiliate redirect link.

    Falls back to the given URL unchanged when it carries none of the known
    affiliate-wrapper query parameters - some providers (IndieGala) are
    linked directly with no redirect wrapper at all.
    """
    query = parse_qs(urlparse(redirect_url).query)
    for param in _REDIRECT_URL_PARAMS:
        values = query.get(param)
        if values:
            return values[0]
        # end if
    # end for
    return redirect_url
# end def real_provider_url


def real_provider_slug(redirect_url: str) -> str:
    """Return the provider's own bundle slug, decoded from the affiliate redirect URL."""
    target = real_provider_url(redirect_url)
    path_parts = [part for part in urlparse(target).path.split("/") if part]
    if not path_parts:
        raise ItadParseError(f"decoded provider URL has no path segment: {target}")
    # end if
    non_numeric = [part for part in path_parts if not part.isdecimal()]
    return non_numeric[-1] if non_numeric else path_parts[-1]
# end def real_provider_slug


GAME_HREF_PATTERN = re.compile(r"^/game/([a-z0-9-]+)/info/$")
TIER_LABEL_PATTERN = re.compile(r"^Tier\s+\d+\s*(?:\d+/\d+)?\s*(.*)$")


def _tier_price(raw: str) -> ItadPrice | None:
    stripped = raw.strip()
    if not stripped or stripped == "--":
        return None
    # end if
    match = re.match(r"([\d.,]+)\s*(\D+)$", stripped)
    if not match:
        raise ItadParseError(f"tier price is not a recognizable amount: {raw!r}")
    # end if
    amount_text, currency = match.groups()
    try:
        value = float(amount_text.replace(",", "."))
    except ValueError as error:
        raise ItadParseError(f"tier price is not a number: {raw!r}") from error
    # end try
    return ItadPrice(raw=stripped, value=value, currency=currency.strip())
# end def _tier_price


def _tier_name(header_text: str, index: int) -> str:
    stripped = _strip_tags(header_text)
    match = TIER_LABEL_PATTERN.match(stripped)
    label = match.group(1).strip() if match else ""
    if label:
        return label
    # end if
    if match:
        # Matched "Tier N" (with or without a "x/y" progress counter) but no
        # trailing display label (Bronze/Silver/Gold) - use the plain tier
        # number rather than leaking the counter noise into the name.
        return f"Tier {index + 1}"
    # end if
    return stripped or f"Tier {index + 1}"
# end def _tier_name


def _humble_tier_name(item_count: int, expected_game_count: int) -> str:
    """Match the dedicated Humble scraper's own tier-naming convention.

    See `humblebundle/crawler.py`'s `write_humble_offer`: the tier whose
    `item_count` equals the bundle's total game count is the full/"entire"
    one, every other tier is named by its own item count.
    """
    prefix = "entire-" if item_count == expected_game_count else ""
    return f"{prefix}{item_count}-item-bundle"
# end def _humble_tier_name


def _dedupe_tier_name(name: str, seen_names: set[str]) -> str:
    base_name = name
    suffix = 2
    while name in seen_names:
        name = f"{base_name} ({suffix})"
        suffix += 1
    # end while
    seen_names.add(name)
    return name
# end def _dedupe_tier_name


# Loose substrings for matching a shop's display name (from the reviewed
# `config/isthereanydeal-shops.yml`) against the provider of a resolved
# qualified ID - used only for a corroboration log line, never for
# resolution itself (`reviews[].url` + `parse_store_identity` remains the
# sole source of truth for ids).
_PROVIDER_SHOP_HINTS: dict[StoreName, str] = {
    "steam": "steam",
    "gog": "gog",
    "epic": "epic",
    "ubisoft": "ubisoft",
    "humble": "humble",
}


def _log_unmatched_shop_keys(
    keys: list[int], ids: list[str], shop_names: dict[int, str], bundle_id: int, slug: str, log: LogFn
) -> None:
    resolved_providers = {value.split(":", 1)[0] for value in ids if not value.startswith("unresolved:")}
    for shop_id in keys:
        shop_name = shop_names.get(shop_id)
        if shop_name is None:
            continue
        # end if
        hint = shop_name.casefold()
        matched = any(
            provider_hint in hint
            for provider, provider_hint in _PROVIDER_SHOP_HINTS.items()
            if provider in resolved_providers
        )
        if not matched:
            log(
                f"  bundle {bundle_id} {slug!r}: shop {shop_id} ({shop_name}) has no matching "
                f"resolved id (resolved: {sorted(resolved_providers) or 'none'})"
            )
        # end if
    # end for
# end def _log_unmatched_shop_keys


def _resolve_urls(urls: list[str], bundle_id: int, slug: str) -> list[str]:
    """Resolve every recognized storefront URL into a qualified ID, deduped and ordered."""
    ids: list[str] = []
    seen: set[str] = set()
    for url in urls:
        provider = next((name for name, root in STORE_ROOTS.items() if url.startswith(root)), None)
        if provider is None:
            continue
        # end if
        try:
            qualified_id = parse_store_identity(provider, url)
        except ValueError:
            continue
        # end try
        if qualified_id in seen:
            continue
        # end if
        seen.add(qualified_id)
        ids.append(qualified_id)
    # end for
    if not ids:
        ids.append(f"unresolved:source:isthereanydeal:{bundle_id}:{slug}")
    # end if
    return ids
# end def _resolve_urls


def parse_bundle_detail_json(
    html: str,
    bundle_id: int,
    expected_game_count: int,
    provider_slug: str,
    shop_names: dict[int, str] | None = None,
    log: LogFn = _NO_LOG,
) -> list[ItadTier] | None:
    """Extract cumulative tiers/prices/IDs from the page's own embedded `var page` JSON.

    Every `/bundles/<id>/` detail page - including mature-rated ones, which
    only gate the page's *visual* rendering, not this embedded data - carries
    a `var page = ["Bundle", {"liveData": {"tiers": [...]}}];` script with the
    same information the HTML itself renders, structured. This is the primary
    parser: it's far more robust than DOM/regex scraping and works uniformly
    for mature bundles. Returns `None` (not an error) when the script isn't
    present at all, so callers can fall back to `parse_bundle_detail_page`;
    raises `ItadParseError` for anything present but malformed.
    """
    text = _find_page_script(html)
    if text is None:
        return None
    # end if
    match = _PAGE_SCRIPT_PATTERN.search(text)
    if not match:
        return None
    # end if
    bracket_start = text.index("[", match.end() - 1)
    raw_array = _extract_balanced(text, bracket_start, "[", "]")
    try:
        data = json.loads(raw_array)
    except json.JSONDecodeError as error:
        raise ItadParseError(f"bundle {bundle_id} embedded page data is not valid JSON: {error}") from error
    # end try
    if not isinstance(data, list) or len(data) < 2 or data[0] != "Bundle" or not isinstance(data[1], dict):
        raise ItadParseError(f"bundle {bundle_id} embedded page data has an unexpected shape")
    # end if
    live_data = data[1].get("liveData")
    if not isinstance(live_data, dict):
        raise ItadParseError(f"bundle {bundle_id} embedded page data is missing liveData")
    # end if
    tiers_raw = live_data.get("tiers")
    if not isinstance(tiers_raw, list) or not tiers_raw:
        raise ItadParseError(f"bundle {bundle_id} embedded page data has no tiers")
    # end if

    items_by_slug: dict[str, ItadItem] = {}
    cumulative: list[str] = []
    tiers: list[ItadTier] = []
    seen_names: set[str] = set()
    for tier_raw in tiers_raw:
        if not isinstance(tier_raw, dict):
            raise ItadParseError(f"bundle {bundle_id} has a malformed tier entry")
        # end if
        games_raw = tier_raw.get("games")
        if not isinstance(games_raw, list):
            raise ItadParseError(f"bundle {bundle_id} tier is missing its games list")
        # end if
        new_slugs: list[str] = []
        for game in games_raw:
            if not isinstance(game, dict):
                raise ItadParseError(f"bundle {bundle_id} has a malformed game entry")
            # end if
            slug, title = game.get("slug"), game.get("title")
            if not isinstance(slug, str) or not slug or not isinstance(title, str) or not title:
                raise ItadParseError(f"bundle {bundle_id} game entry is missing slug/title")
            # end if
            if slug in items_by_slug:
                continue
            # end if
            reviews = game.get("reviews")
            urls = [
                review["url"]
                for review in (reviews if isinstance(reviews, list) else [])
                if isinstance(review, dict) and isinstance(review.get("url"), str)
            ]
            ids = _resolve_urls(urls, bundle_id, slug)
            if shop_names:
                keys = game.get("keys")
                if isinstance(keys, list):
                    _log_unmatched_shop_keys(
                        [key for key in keys if isinstance(key, int)], ids, shop_names, bundle_id, slug, log
                    )
                # end if
            # end if
            items_by_slug[slug] = ItadItem(slug=slug, title=title, ids=ids)
            new_slugs.append(slug)
        # end for
        if not new_slugs:
            # A zero-game tier (e.g. a trailing marketing "add-on" row) adds
            # no new content - skip it rather than emitting an empty tier.
            continue
        # end if
        cumulative = [*cumulative, *new_slugs]
        note = tier_raw.get("note")
        if isinstance(note, str) and note.strip():
            name = note.strip()
        elif provider_slug == "humblebundle":
            name = _humble_tier_name(len(cumulative), expected_game_count)
        else:
            name = f"Tier {len(tiers) + 1}"
        # end if
        name = _dedupe_tier_name(name, seen_names)
        price_raw = tier_raw.get("price")
        price: ItadPrice | None = None
        if isinstance(price_raw, list) and len(price_raw) == 2:
            amount, currency = price_raw
            if not isinstance(amount, (int, float)) or not isinstance(currency, str):
                raise ItadParseError(f"bundle {bundle_id} tier price has an unexpected shape: {price_raw!r}")
            # end if
            value = amount / 100
            price = ItadPrice(raw=f"{value:.2f} {currency}", value=value, currency=currency)
        elif price_raw is not None:
            raise ItadParseError(f"bundle {bundle_id} tier price has an unexpected shape: {price_raw!r}")
        # end if
        tiers.append(
            ItadTier(
                identifier=f"tier-{len(tiers) + 1}",
                name=name,
                item_count=len(cumulative),
                price=price,
                items=[items_by_slug[slug] for slug in cumulative],
            )
        )
    # end for
    if not tiers:
        raise ItadParseError(f"bundle {bundle_id} has tiers but none contain any games")
    # end if
    if len(cumulative) != expected_game_count:
        raise ItadParseError(
            f"bundle {bundle_id} embedded tiers total {len(cumulative)} games, "
            f"list API advertised {expected_game_count}"
        )
    # end if
    return tiers
# end def parse_bundle_detail_json


def parse_bundle_detail_page(html: str, bundle_id: int, expected_game_count: int) -> list[ItadTier]:
    """Extract cumulative tiers, prices, and per-game storefront IDs from an ITAD bundle page.

    Fallback path, used only when `parse_bundle_detail_json` finds no
    embedded page data. Walks a BeautifulSoup tree in document order rather
    than matching regexes over serialized markup, mirroring the same
    positional assumption the embedded JSON confirmed is correct: items
    render in ascending-tier order with no per-item tier tag, so everything
    between one `.tier-name` header and the next belongs to that tier, each
    tier's `items` accumulating every earlier tier's items too. A single
    flat-price bundle or a "Build Your Own"/mix-and-match bundle (`byob` in
    the list API) both render as exactly one tier-name header covering every
    game, so no special-casing is needed for either shape.
    """
    soup = BeautifulSoup(html, "html.parser")

    tier_headers: list[Tag] = []
    tier_slugs: list[list[str]] = []
    tier_prices: list[str | None] = []
    titles_by_slug: dict[str, str] = {}
    urls_by_slug: dict[str, list[str]] = {}
    ordered_slugs: list[str] = []
    current_slug: str | None = None

    for element in soup.find_all(True):
        classes = element.get("class") or []
        if "tier-name" in classes:
            tier_headers.append(element)
            tier_slugs.append([])
            tier_prices.append(None)
            current_slug = None
            continue
        # end if
        if "value__price" in classes:
            if tier_prices:
                tier_prices[-1] = element.get_text(strip=True)
            # end if
            continue
        # end if
        if element.name != "a":
            continue
        # end if
        href = element.get("href") or ""
        game_match = GAME_HREF_PATTERN.match(href)
        if game_match:
            slug = game_match.group(1)
            if slug not in titles_by_slug:
                title_tag = element.find(class_="game-title")
                title = _strip_tags(title_tag.get_text(" ") if title_tag is not None else element.get_text(" "))
                if not title:
                    raise ItadParseError(f"bundle {bundle_id} game {slug!r} has an empty title")
                # end if
                titles_by_slug[slug] = title
                urls_by_slug[slug] = []
                ordered_slugs.append(slug)
                if tier_slugs:
                    tier_slugs[-1].append(slug)
                # end if
            # end if
            current_slug = slug
            continue
        # end if
        if current_slug is not None and any(href.startswith(root) for root in STORE_ROOTS.values()):
            urls_by_slug[current_slug].append(href)
        # end if
    # end for

    if not ordered_slugs:
        raise ItadParseError(f"bundle {bundle_id} detail page has no games")
    # end if
    if not tier_headers:
        raise ItadParseError(f"bundle {bundle_id} detail page has no tier headers")
    # end if

    items_by_slug = {
        slug: ItadItem(slug=slug, title=titles_by_slug[slug], ids=_resolve_urls(urls_by_slug[slug], bundle_id, slug))
        for slug in ordered_slugs
    }

    tiers: list[ItadTier] = []
    cumulative: list[str] = []
    seen_names: set[str] = set()
    for tier_index, (header, new_slugs, price_text) in enumerate(zip(tier_headers, tier_slugs, tier_prices)):
        if not new_slugs:
            # A trailing "Add-on tier" (0 games of its own, always last) adds
            # no new content beyond the last real tier - seen on a live
            # bundle with 3 real games plus a zero-item add-on marketing
            # tier. Skip it rather than erroring or emitting a duplicate.
            continue
        # end if
        cumulative = [*cumulative, *new_slugs]
        name = _dedupe_tier_name(_tier_name(header.get_text(" ", strip=True), tier_index), seen_names)
        price = _tier_price(price_text) if price_text is not None else None
        tiers.append(
            ItadTier(
                identifier=f"tier-{len(tiers) + 1}",
                name=name,
                item_count=len(cumulative),
                price=price,
                items=[items_by_slug[slug] for slug in cumulative],
            )
        )
    # end for
    if not tiers:
        raise ItadParseError(f"bundle {bundle_id} has tier headers but none contain any games")
    # end if
    if len(cumulative) != len(ordered_slugs):
        raise ItadParseError(f"bundle {bundle_id} has games not covered by any tier")
    # end if
    if len(cumulative) != expected_game_count:
        raise ItadParseError(
            f"bundle {bundle_id} tiers total {len(cumulative)} games, "
            f"list API advertised {expected_game_count}"
        )
    # end if
    return tiers
# end def parse_bundle_detail_page
