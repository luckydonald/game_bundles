"""Strict normalized models for archived digiphile.co bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.timestamps import ScrapedTimestamp
from game_collections.versioning import SchemaDateVersion, Versioned


DIGIPHILE_V1 = SchemaDateVersion(2026, 10, 28)
DigiphileVersions = Literal[DIGIPHILE_V1]
DigiphileCurrentVersion = Literal[DIGIPHILE_V1]
CURRENT_VERSION: DigiphileCurrentVersion = DIGIPHILE_V1

# Digiphile's own bundle `type`: `SteamGame` bundles deliver Steam keys, `EBook` bundles (comics) deliver files.
DigiphileBundleType = Literal["steam-game", "ebook"]

# Digiphile's tier `type`. `base` tiers are the cumulative price breakpoints; `charity` and `upsell` tiers are
# optional add-ons sold next to them, each holding only its own products.
DigiphileTierType = Literal["base", "charity", "upsell"]


class DigiphileItem(StrictModel):
    """One product of a Digiphile bundle.

    `product_type` is Digiphile's own label (`SteamGame`, `EBook`). `ids` always ends with the stable anchor
    `digiphile:<product ULID>` (products have no slug, and a game and its soundtrack can share a title prefix) and
    starts with `steam:<appid>` for Steam products, whose app id Digiphile always states itself.
    """

    title: NonEmptyString
    product_type: NonEmptyString
    price: float = Field(ge=0)
    ids: list[NonEmptyString] = Field(min_length=1)

# end class DigiphileItem


class DigiphileTier(StrictModel):
    """One purchase tier of a Digiphile bundle.

    `items` is the cumulative unlock list for a `base` tier (everything up to this price) and only the tier's own
    products for a `charity` or `upsell` add-on.
    """

    identifier: NonEmptyString
    name: NonEmptyString
    tier_type: DigiphileTierType
    price: float = Field(ge=0)
    order: int
    items: list[DigiphileItem]

# end class DigiphileTier


class DigiphileDates(StrictModel):
    """Offer availability and observation timestamps.

    `start`/`end` are Digiphile's own `startsAt`/`endsAt`, hence a confidence of 1.0. `first_seen` is the time this
    bundle was archived.
    """

    start: ScrapedTimestamp | None = None
    end: ScrapedTimestamp | None = None
    first_seen: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.first_seen, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("Digiphile timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class DigiphileDates


class DigiphileArchive(StrictModel):
    """Normalized metadata for one Digiphile bundle offer."""

    machine_name: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    subtitle: str | None = None
    bundle_type: DigiphileBundleType
    curator_series: str | None = None
    charities: list[NonEmptyString] = Field(default_factory=list)
    min_price: float = Field(ge=0)
    suggested_price: float = Field(ge=0)
    dates: DigiphileDates
    tiers: list[DigiphileTier] = Field(min_length=1)

# end class DigiphileArchive


VersionedDigiphileArchive = Versioned[DigiphileCurrentVersion, DigiphileArchive]
