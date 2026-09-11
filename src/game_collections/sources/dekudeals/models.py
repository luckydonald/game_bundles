"""Strict normalized models for archived dekudeals.com bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel


class DekuPrice(StrictModel):
    """A localized tier/pick price as shown on a DekuDeals bundle page."""

    raw: NonEmptyString
    value: float = Field(ge=0)
    currency: NonEmptyString

# end class DekuPrice


class DekuItem(StrictModel):
    """One game advertised within a DekuDeals bundle.

    DekuDeals bundle pages never link straight to a storefront - every game
    routes through DekuDeals' own `/items/<slug>` page, which is resolved
    separately (immediately, during the same crawl - see `crawler.py`) into
    `ids`. `ids` always includes `dekudeals:<slug>` itself, plus every
    storefront `sources.storefronts.qualified_ids_from_urls` recognized on
    that item page.
    """

    slug: NonEmptyString
    title: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)

# end class DekuItem


class DekuTier(StrictModel):
    """One purchase tier/pick-option on a DekuDeals bundle.

    Covers both real `tiering_style` values seen live: `price_per_tier`
    (cumulative price breakpoints, e.g. "Crawling Through the Dungeons" -
    each tier's own `price` is fixed and `items` is that tier's full,
    cumulative unlock list) and `price_per_item` (a Build Your Own bundle -
    each tier instead fixes an `item_minimum` pick count over one shared
    pool, with `price` being the per-item price at that count; see
    `DekuArchive.tiering_style`).
    """

    identifier: NonEmptyString
    price: DekuPrice | None = None
    item_minimum: int | None = Field(default=None, ge=1)
    items: list[DekuItem]

# end class DekuTier


class DekuDates(StrictModel):
    """Offer observation timestamp and its estimated expiry."""

    end: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.end, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("DekuDeals timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class DekuDates


class DekuArchive(StrictModel):
    """Normalized metadata for one DekuDeals bundle offer."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    machine_name: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    store_name: NonEmptyString
    provider_slug: NonEmptyString
    tiering_style: Literal["price_per_tier", "price_per_item"]
    real_url: HttpUrl | None = None
    dates: DekuDates
    tiers: list[DekuTier] = Field(min_length=1)

# end class DekuArchive
