"""Strict normalized models for archived DailyIndieGame bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel


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
    """Offer observation timestamp and its estimated expiry."""

    end: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.end, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("DailyIndieGame timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class DigDates


class DigArchive(StrictModel):
    """Normalized metadata for one DailyIndieGame weekly bundle."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
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
