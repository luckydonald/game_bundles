"""Strict normalized models for archived fanatical.com bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.timestamps import ScrapedTimestamp
from game_collections.versioning import SchemaDateVersion, Versioned


FANATICAL_V1 = SchemaDateVersion(2026, 10, 26)
FanaticalVersions = Literal[FANATICAL_V1]
FanaticalCurrentVersion = Literal[FANATICAL_V1]
CURRENT_VERSION: FanaticalCurrentVersion = FANATICAL_V1

# `bundle`: fixed price breakpoints, each tier unlocking more products. `pick-and-mix`: Fanatical's
# "Build your own" bundles, one shared pool where every tier instead fixes how many products may be picked.
FanaticalBundleType = Literal["bundle", "pick-and-mix"]

# Fanatical's per-currency price dicts, e.g. `{"GBP": 5.99, "USD": 5.99, "JPY": 1040}`.
FanaticalPrices = dict[NonEmptyString, float]


class FanaticalItem(StrictModel):
    """One product advertised within a Fanatical bundle.

    `product_type` is Fanatical's own label (`game`, `bundle` for a nested edition/collection, `software`,
    `book`, `comic`, `audio`). `ids` always includes `fanatical:<slug>` as a stable anchor, plus a
    `steam:<appid>` when known, or `unresolved:source:fanatical:<bundle>:<slug>` for a Steam product
    whose id could not be determined (see `resolver.py`).
    """

    slug: NonEmptyString
    title: NonEmptyString
    product_type: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)

# end class FanaticalItem


class FanaticalTier(StrictModel):
    """One purchase tier of a Fanatical bundle.

    `display_total` is Fanatical's own "number of products" for the tier: the total unlocked so far for a
    regular `bundle`, the number of products which may be picked for a `pick-and-mix`. `items` is the
    tier's full, cumulative unlock list (regular) or the shared pool (pick-and-mix).
    """

    identifier: NonEmptyString
    price: FanaticalPrices
    display_total: int = Field(ge=0)
    items: list[FanaticalItem]

# end class FanaticalTier


class FanaticalDates(StrictModel):
    """Offer availability and observation timestamps.

    `start`/`end` are Fanatical's own `available_valid_from`/`available_valid_until` unix timestamps, hence
    a confidence of 1.0. `first_seen` is set once, the first time this bundle is ever archived,
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
                raise ValueError("Fanatical timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class FanaticalDates


class FanaticalArchive(StrictModel):
    """Normalized metadata for one Fanatical bundle offer."""

    machine_name: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    bundle_type: FanaticalBundleType
    pay_what_you_want: bool
    discount_percent: int = Field(ge=0, le=100)
    full_price: FanaticalPrices
    dates: FanaticalDates
    tiers: list[FanaticalTier] = Field(min_length=1)

# end class FanaticalArchive


VersionedFanaticalArchive = Versioned[FanaticalCurrentVersion, FanaticalArchive]
