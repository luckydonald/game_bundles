"""Builders for Fanatical list-endpoint items, shared by the Fanatical tests."""

from __future__ import annotations

from typing import Any


def product(slug: str, steam_id: Any = None, kind: str = "game", drm: list[str] | None = None) -> dict[str, Any]:
    return {
        "product_id": f"id-{slug}",
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "type": kind,
        "steamId": steam_id,
        "steamIdType": "app" if isinstance(steam_id, int) else "",
        "drm": ["steam"] if drm is None else drm,
    }
# end def product


def prices(amount: float) -> dict[str, float]:
    return {"GBP": amount, "USD": amount, "EUR": amount}
# end def prices


def raw_bundle(slug: str = "tiny-bundle", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": "Tiny Bundle",
        "slug": slug,
        "type": "bundle",
        "pay_what_you_want": False,
        "discount_percent": 90,
        "price": prices(1),
        "fullPrice": prices(30),
        "available_valid_from": 1790935200,
        "available_valid_until": 1793433600,
        "bundle_tiers": [
            {"displayTotal": 2, "price": prices(1), "products": [product("one", 11), product("two", 22)]},
            {"displayTotal": 3, "price": prices(5), "products": [product("three", 33)]},
        ],
    }
    item.update(overrides)
    return item
# end def raw_bundle
