"""Strict normalized models for archived Humble offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel


class HumblePrice(StrictModel):
    """A localized price with its unambiguous ISO currency code."""

    raw: NonEmptyString
    value: float = Field(ge=0)
    currency: NonEmptyString
    currency_code: NonEmptyString

# end class HumblePrice


class HumbleLink(StrictModel):
    """A named external party such as a developer or publisher."""

    name: NonEmptyString
    url: HttpUrl | None = None

# end class HumbleLink


class HumbleResolution(StrictModel):
    """Storefront identity resolution for one archived item."""

    ids: list[NonEmptyString] = Field(default_factory=list)
    unresolved_stores: list[NonEmptyString] = Field(default_factory=list)

# end class HumbleResolution


class HumbleItem(StrictModel):
    """One product advertised within a Humble tier."""

    machine_name: NonEmptyString
    title: NonEmptyString
    item_type: NonEmptyString | None = None
    is_game: bool
    retail_price: HumblePrice | None = None
    youtube_urls: list[HttpUrl] = Field(default_factory=list)
    cover_art_url: HttpUrl | None = None
    developers: list[HumbleLink] = Field(default_factory=list)
    publishers: list[HumbleLink] = Field(default_factory=list)
    redeem_on: list[NonEmptyString] = Field(default_factory=list)
    platforms: list[NonEmptyString] = Field(default_factory=list)
    description: str = ""
    key_expiration_text: NonEmptyString | None = None
    tags: list[NonEmptyString] = Field(default_factory=list)
    genres: list[NonEmptyString] = Field(default_factory=list)
    rating: dict[str, object] = Field(default_factory=dict)
    region_locked: bool | None = None
    excluded_countries: list[NonEmptyString] = Field(default_factory=list)
    resolution: HumbleResolution = Field(default_factory=HumbleResolution)

# end class HumbleItem


class HumbleTier(StrictModel):
    """A cumulative Humble purchase tier."""

    identifier: NonEmptyString
    name: NonEmptyString
    item_count: int = Field(ge=0)
    minimum_price: HumblePrice | None = None
    items: list[HumbleItem]

    @model_validator(mode="after")
    def validate_item_count(self) -> Self:
        if self.item_count != len(self.items):
            raise ValueError("tier item count does not match its item list")
        # end if
        return self
    # end def validate_item_count

# end class HumbleTier


class HumbleCharity(StrictModel):
    """A charity supported by an offer."""

    name: NonEmptyString
    url: HttpUrl | None = None
    description: str = ""
    logo_url: HttpUrl | None = None

# end class HumbleCharity


class HumbleDates(StrictModel):
    """Offer availability and observation timestamps."""

    start: datetime | None = None
    end: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.start, self.end, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("Humble timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class HumbleDates


class HumbleArchive(StrictModel):
    """Normalized metadata for one Choice month or game bundle."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    kind: Literal["choice", "bundle"]
    machine_name: NonEmptyString
    url: HttpUrl
    name: NonEmptyString
    headline: NonEmptyString
    description: str
    category: Literal["Games"] = "Games"
    dates: HumbleDates
    charities: list[HumbleCharity] = Field(default_factory=list)
    key_expiration_text: NonEmptyString | None = None
    tiers: list[HumbleTier] = Field(min_length=1)

# end class HumbleArchive
