"""Parse isthereanydeal.com's bootstrap page, list API, and bundle detail pages."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from game_collections.sources.isthereanydeal.models import ItadItem, ItadListSummary, ItadPrice, ItadTier
from game_collections.sources.storefronts import STORE_ROOTS, StoreName, parse_store_identity


class ItadParseError(ValueError):
    """An isthereanydeal.com page or API response did not have the expected shape."""

# end class ItadParseError


def _strip_tags(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
# end def _strip_tags


TOKEN_PATTERN = re.compile(r'"token"\s*:\s*"([^"]+)"')
SHOPS_KEY_PATTERN = re.compile(r'"shops"\s*:\s*')


def _extract_balanced_object(html: str, start: int) -> str:
    """Return the `{...}` JSON object beginning at `start`, matching nested braces."""
    if start >= len(html) or html[start] != "{":
        raise ItadParseError("expected '{' while extracting a balanced object")
    # end if
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(html)):
        character = html[index]
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
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return html[start : index + 1]
            # end if
        # end if
    # end for
    raise ItadParseError("unterminated '{' while extracting a balanced object")
# end def _extract_balanced_object


def parse_bootstrap_page(html: str) -> tuple[str, dict[int, str]]:
    """Extract the anonymous session token and shop-id->name table from `/bundles/`.

    Both are embedded in an inline bootstrap script every anonymous visitor
    receives (`var g = {..., "shops": {"<id>": ["<name>", <flag>], ...}, ...,
    "token": "..."}`) - this is ordinary page scraping, not session/credential
    handling: the token is a plain anonymous CSRF-style value issued to any
    visitor, identical in value to the `sess2` cookie set on the same request.
    """
    token_match = TOKEN_PATTERN.search(html)
    if not token_match:
        raise ItadParseError("bootstrap page is missing its session token")
    # end if
    shops_key_match = SHOPS_KEY_PATTERN.search(html)
    if not shops_key_match:
        raise ItadParseError("bootstrap page is missing its shops table")
    # end if
    brace_start = html.index("{", shops_key_match.end() - 1)
    raw_object = _extract_balanced_object(html, brace_start)
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


GAME_LINK_PATTERN = re.compile(r"/game/([a-z0-9-]+)/info/")
TITLE_PATTERN = re.compile(r'<span class="game-title">(.*?)</a>', re.IGNORECASE | re.DOTALL)
TIER_HEADER_PATTERN = re.compile(r'<div class="tier-name[^"]*">(.*?)<div class="values', re.IGNORECASE | re.DOTALL)
TIER_PRICE_PATTERN = re.compile(
    r'<div>Price</div>\s*<div class="value__price[^"]*">([^<]*)</div>', re.IGNORECASE
)
TIER_LABEL_PATTERN = re.compile(r"^Tier\s+\d+\s*(?:\d+/\d+)?\s*(.*)$")
STORE_LINK_PATTERN = re.compile(
    "|".join(re.escape(root) for root in STORE_ROOTS.values()).join(("(", ")"))
    + r'[^"\'\s<>]*'
)


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


def _resolve_item_ids(html: str, start: int, end: int, bundle_id: int, slug: str) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for match in STORE_LINK_PATTERN.finditer(html, start, end):
        url = match.group(0)
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
# end def _resolve_item_ids


def parse_bundle_detail_page(html: str, bundle_id: int, expected_game_count: int) -> list[ItadTier]:
    """Extract cumulative tiers, prices, and per-game storefront IDs from an ITAD bundle page.

    Items render in ascending-tier DOM order with no per-item tier tag (unlike
    GreenManGaming's `hx-vals`), so tiers are built positionally: everything
    between one `tier-name` header and the next belongs to that tier, and each
    tier's `items` accumulate every earlier tier's items too (confirmed
    cumulative against a live 3-tier GreenManGaming-hosted bundle, where the
    per-boundary counts 2/2/2 summed to the page's advertised 6-game total).
    A single flat-price bundle or a "Build Your Own"/mix-and-match bundle
    (`byob` in the list API) both render as exactly one tier-name header
    covering every game, so no special-casing is needed for either shape.
    """
    game_positions: list[tuple[int, str]] = []
    seen_slugs: set[str] = set()
    for match in GAME_LINK_PATTERN.finditer(html):
        slug = match.group(1)
        if slug not in seen_slugs:
            seen_slugs.add(slug)
            game_positions.append((match.start(), slug))
        # end if
    # end for
    if not game_positions:
        raise ItadParseError(f"bundle {bundle_id} detail page has no games")
    # end if

    items_by_slug: dict[str, ItadItem] = {}
    ordered_slugs: list[str] = []
    for index, (pos, slug) in enumerate(game_positions):
        next_pos = game_positions[index + 1][0] if index + 1 < len(game_positions) else len(html)
        title_match = TITLE_PATTERN.search(html, pos, next_pos)
        if not title_match:
            raise ItadParseError(f"bundle {bundle_id} game {slug!r} is missing its title")
        # end if
        title = _strip_tags(title_match.group(1))
        if not title:
            raise ItadParseError(f"bundle {bundle_id} game {slug!r} has an empty title")
        # end if
        ids = _resolve_item_ids(html, pos, next_pos, bundle_id, slug)
        items_by_slug[slug] = ItadItem(slug=slug, title=title, ids=ids)
        ordered_slugs.append(slug)
    # end for

    tier_positions = [(match.start(), match.group(1)) for match in TIER_HEADER_PATTERN.finditer(html)]
    if not tier_positions:
        raise ItadParseError(f"bundle {bundle_id} detail page has no tier headers")
    # end if

    game_index_by_position = [pos for pos, _slug in game_positions]
    tiers: list[ItadTier] = []
    cumulative: list[str] = []
    seen_names: set[str] = set()
    for tier_index, (pos, header) in enumerate(tier_positions):
        next_pos = tier_positions[tier_index + 1][0] if tier_index + 1 < len(tier_positions) else len(html)
        new_slugs = [
            ordered_slugs[game_index]
            for game_index, game_pos in enumerate(game_index_by_position)
            if pos < game_pos < next_pos
        ]
        if not new_slugs:
            # A trailing "Add-on tier" (0 games of its own, always last) adds
            # no new content beyond the last real tier - seen on a live
            # bundle with 3 real games plus a zero-item add-on marketing
            # tier. Skip it rather than erroring or emitting a duplicate.
            continue
        # end if
        cumulative = [*cumulative, *new_slugs]
        name = _tier_name(header, tier_index)
        base_name = name
        suffix = 2
        while name in seen_names:
            name = f"{base_name} ({suffix})"
            suffix += 1
        # end while
        seen_names.add(name)
        price_match = TIER_PRICE_PATTERN.search(html, pos, next_pos)
        price = _tier_price(price_match.group(1)) if price_match else None
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
