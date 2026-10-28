"""Builders for Digiphile pages, shared by the Digiphile tests.

A page embeds its data as React Server Component flight chunks (`self.__next_f.push([1, "<fragment>"])`),
the builders split the JSON over two chunks like the real site does.
"""

from __future__ import annotations

import json
from typing import Any


def product(
    ulid: str, title: str, tier_id: str, app_id: int | None = None, kind: str = "SteamGame", order: int = 0
) -> dict[str, Any]:
    return {
        "id": ulid,
        "title": title,
        "price": 9.99,
        "type": kind,
        "bundleTierId": tier_id,
        "order": order,
        "steamGameMetadata": {"steamAppId": app_id} if kind == "SteamGame" else None,
    }
# end def product


def tier(tier_id: str, name: str, price: float, kind: str = "Base", order: int = 0) -> dict[str, Any]:
    return {"id": tier_id, "name": name, "price": price, "order": order, "type": kind, "bonusItems": []}
# end def tier


def raw_bundle(slug: str = "tiny-bundle", **overrides: Any) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "slug": slug,
        "title": "Tiny Bundle",
        "subtitle": "Small but mighty",
        "type": "SteamGame",
        "minPrice": 4,
        "suggestedPrice": 16,
        "startsAt": "2026-10-20T15:00:00+00:00",
        "endsAt": "2026-11-04T16:00:00+00:00",
        "bundleTypeTag": {"name": "Signature Series"},
        "charities": [{"charity": {"name": "Good Cause"}}],
        # Deliberately out of order: the parser sorts base tiers by price and puts add-ons last.
        "tiers": [
            tier("t-upsell", "Map DLC", 4, "Upsell"),
            tier("t-16", "Tier $16.00", 16),
            tier("t-charity", "Relief Fund", 2, "Charity"),
            tier("t-4", "Tier $4.00", 4),
        ],
        "products": [
            product("p-three", "Three", "t-16", 3),
            product("p-one", "One", "t-4", 1),
            product("p-two", "Two", "t-16", 2, order=1),
            product("p-ost", "Soundtrack", "t-charity", 4),
            product("p-dlc", "Map Pack", "t-upsell", 5),
        ],
        "productGroups": [],
    }
    bundle.update(overrides)
    return bundle
# end def raw_bundle


def page(payload: dict[str, Any], key: str = "bundle") -> str:
    """A bundle page whose flight data carries `payload` split across two chunks."""
    text = f'1e:[["$","div",null,{{"{key}":{json.dumps(payload)}}}]]'
    middle = len(text) // 2
    chunks = [[1, text[:middle]], [1, text[middle:]]]
    scripts = "".join(f"<script>self.__next_f.push({json.dumps(chunk)})</script>" for chunk in chunks)
    return f"<html><head><title>x</title></head><body>{scripts}</body></html>"
# end def page


def listing_page(*slugs: str) -> str:
    return page([{"slug": slug, "status": "Active"} for slug in slugs], key="bundles")  # type: ignore[arg-type]
# end def listing_page


NOT_FOUND_PAGE = (
    '<html><head><title>404: This page could not be found.</title></head><body>'
    '<script>self.__next_f.push([1,"0:[\\"$\\",\\"div\\",null,{}]"])</script></body></html>'
)
