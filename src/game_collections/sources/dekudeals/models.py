"""Strict normalized models for archived dekudeals.com bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.timestamps import ScrapedTimestamp
from game_collections.versioning import LEGACY_VERSION, SchemaDateVersion, Versioned


DEKU_V1 = SchemaDateVersion(2026, 7, 20)
DEKU_V2 = SchemaDateVersion(2026, 9, 11, 14, 30)
DekuVersions = Literal[LEGACY_VERSION, DEKU_V1, DEKU_V2]
DekuCurrentVersion = Literal[DEKU_V2]
CURRENT_VERSION: DekuCurrentVersion = DEKU_V2


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
    """Offer availability and observation timestamps.

    `start`/`end` carry a confidence + provenance alongside the value itself (see
    `ScrapedTimestamp`). `start` comes from the bundles index page's own `created_at`
    (only available in discovery mode, not an explicit `--url` crawl); `end` comes from
    the bundle detail page's `ends_at` (also cross-checkable against the index's own
    `ends_at`). `first_seen` is set once, the first time this bundle is ever archived,
    and never overwritten afterward.
    """

    start: ScrapedTimestamp | None = None
    end: ScrapedTimestamp | None = None
    first_seen: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.first_seen, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("DekuDeals timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class DekuDates


class DekuArchive(StrictModel):
    """Normalized metadata for one DekuDeals bundle offer."""

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


VersionedDekuArchive = Versioned[DekuCurrentVersion, DekuArchive]
