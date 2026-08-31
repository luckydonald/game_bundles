"""Strict normalized models for archived Green Man Gaming bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel


class GmgPrice(StrictModel):
    """A localized price with its unambiguous ISO currency code."""

    raw: NonEmptyString
    value: float = Field(ge=0)
    currency: NonEmptyString
    currency_code: NonEmptyString

# end class GmgPrice


class GmgResolvedGame(StrictModel):
    """One game split out of a compound item via the "Multiple…" resolution prompt."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(default_factory=list)

# end class GmgResolvedGame


class GmgResolution(StrictModel):
    """Storefront identity resolution for one archived item.

    `ids` describes the item as a single game (the common case). When the
    user declares via "Multiple…" that one item is actually several separate
    games, `splits` holds one resolved entry per game instead, and `ids` is
    left empty.
    """

    ids: list[NonEmptyString] = Field(default_factory=list)
    unresolved_stores: list[NonEmptyString] = Field(default_factory=list)
    splits: list[GmgResolvedGame] = Field(default_factory=list)

# end class GmgResolution


class GmgItem(StrictModel):
    """One product advertised within a Green Man Gaming bundle tier."""

    product_id: NonEmptyString
    title: NonEmptyString
    drm: NonEmptyString | None = None
    platform: NonEmptyString | None = None
    developer: NonEmptyString | None = None
    publisher: NonEmptyString | None = None
    description: str = ""
    cover_art_url: HttpUrl | None = None
    redeem_on: list[NonEmptyString] = Field(default_factory=list)
    resolution: GmgResolution = Field(default_factory=GmgResolution)

# end class GmgItem


class GmgTier(StrictModel):
    """A cumulative Green Man Gaming purchase tier."""

    identifier: NonEmptyString
    name: NonEmptyString
    item_count: int = Field(ge=0)
    price: GmgPrice | None = None
    items: list[GmgItem]

    @model_validator(mode="after")
    def validate_item_count(self) -> Self:
        if self.item_count != len(self.items):
            raise ValueError("tier item count does not match its item list")
        # end if
        return self
    # end def validate_item_count

# end class GmgTier


class GmgDates(StrictModel):
    """Offer availability and observation timestamps.

    The bundles index only exposes `data-end-date="YYYY-MM-DDTHH:MM"` with no
    UTC offset. That's assumed to already be UTC (unconfirmed against the
    server) rather than silently guessing a different offset - end is kept
    optional so a future value that doesn't parse this way fails loudly
    instead of being coerced.
    """

    end: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.end, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("Green Man Gaming timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class GmgDates


class GmgArchive(StrictModel):
    """Normalized metadata for one Green Man Gaming bundle offer."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    slug: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    currency_code: NonEmptyString
    dates: GmgDates
    tiers: list[GmgTier] = Field(min_length=1)

# end class GmgArchive
