"""Strict normalized models for archived DailyIndieGame bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.timestamps import ScrapedTimestamp
from game_collections.versioning import LEGACY_VERSION, SchemaDateVersion, Versioned


DIG_V1 = SchemaDateVersion(2026, 6, 15)
DIG_V2 = SchemaDateVersion(2026, 9, 11, 14, 30)
DigVersions = Literal[LEGACY_VERSION, DIG_V1, DIG_V2]
DigCurrentVersion = Literal[DIG_V2]
CURRENT_VERSION: DigCurrentVersion = DIG_V2


class DigPrice(StrictModel):
    """A USD price as displayed on the site."""

    raw: NonEmptyString
    value: float = Field(ge=0)
    currency: NonEmptyString
    currency_code: NonEmptyString

# end class DigPrice


class DigItem(StrictModel):
    """One Steam game advertised within a DIG bundle."""

    title: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)
    url: HttpUrl
    cover_art_url: HttpUrl | None = None
    description: str = ""
    individual_price: DigPrice | None = None
    region: NonEmptyString | None = None

# end class DigItem


class DigDates(StrictModel):
    """Offer observation timestamp and its estimated expiry.

    `start`: no known source on DIG's pages - left `None`, never fabricated. `end` is
    *computed* (`crawled + parsed "ends in Xd:Xh:Xm:Xs"` countdown) - real countdown
    text, but a derived, second-precision-drifting estimate, hence a confidence well
    below 1.0. `first_seen` is set once, the first time this bundle is ever archived,
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
                raise ValueError("DailyIndieGame timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class DigDates


class DigArchive(StrictModel):
    """Normalized metadata for one DailyIndieGame weekly bundle."""

    kind: Literal["bundle"] = "bundle"
    machine_name: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    is_adult: bool
    dates: DigDates
    game_count: int = Field(ge=0)
    total_value: DigPrice
    bundle_price: DigPrice
    savings_percent: int = Field(ge=0, le=100)
    savings_amount: DigPrice
    items: list[DigItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_game_count(self) -> Self:
        if self.game_count != len(self.items):
            raise ValueError("bundle game count does not match its item list")
        # end if
        return self
    # end def validate_game_count

# end class DigArchive


VersionedDigArchive = Versioned[DigCurrentVersion, DigArchive]
