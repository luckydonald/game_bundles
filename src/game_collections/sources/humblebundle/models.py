"""Strict normalized models for archived Humble offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel
from game_collections.sources.timestamps import ScrapedTimestamp
from game_collections.versioning import LEGACY_VERSION, SchemaDateVersion, Versioned


HUMBLE_V1 = SchemaDateVersion(2026, 6, 1)
HUMBLE_V2 = SchemaDateVersion(2026, 9, 11, 14, 30)
HumbleVersions = Literal[LEGACY_VERSION, HUMBLE_V1, HUMBLE_V2]
HumbleCurrentVersion = Literal[HUMBLE_V2]
CURRENT_VERSION: HumbleCurrentVersion = HUMBLE_V2


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


class HumbleResolvedGame(StrictModel):
    """One game split out of a compound "DLC pack" item."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(default_factory=list)

# end class HumbleResolvedGame


class HumbleResolution(StrictModel):
    """Storefront identity resolution for one archived item.

    `ids`/`requires` describe the item as a single game (the common case).
    When an item is a "DLC pack" bundling several separate DLCs, `splits`
    holds one resolved entry per DLC instead, and `ids` is left empty;
    `requires` (the shared base game) still applies to every split.
    """

    ids: list[NonEmptyString] = Field(default_factory=list)
    unresolved_stores: list[NonEmptyString] = Field(default_factory=list)
    requires: list[NonEmptyString] = Field(default_factory=list)
    splits: list[HumbleResolvedGame] = Field(default_factory=list)

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
    # Populated for "DLC pack" items (see `cta_badge`/`tags` == "dlc") whose description
    # links a free base game and lists the individual DLCs bundled together.
    base_game_url: HttpUrl | None = None
    bundled_dlc_names: list[NonEmptyString] = Field(default_factory=list)
    # Populated for "Edition" items whose title ends "- <Edition> Edition" and whose description
    # states "Includes: Base game + <DLC> + <DLC>." (no `cta_badge`, unlike a "DLC pack" - Steam
    # only sells the base game + DLCs together via this edition, with no single matching app page).
    # Each component (including the base game itself) is resolved independently, with no `requires`.
    edition_component_titles: list[NonEmptyString] = Field(default_factory=list)

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
    """Offer availability and observation timestamps.

    `start`/`end` carry a confidence + provenance alongside the value itself (see
    `ScrapedTimestamp`) - both come straight from the bundle/Choice detail page's own
    fields, confidence 1.0, whenever present. `first_seen` is set once, the first time
    this bundle is ever archived, and never overwritten afterward.
    """

    start: ScrapedTimestamp | None = None
    end: ScrapedTimestamp | None = None
    first_seen: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.first_seen, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("Humble timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class HumbleDates


class HumbleChoicePickOption(StrictModel):
    """One subscription tier's pick quota for a Humble Choice month.

    Verified live against a real Choice page's `webpack-choice-marketing-data`
    embedded JSON: `tierInfo.<tier_key> = {"uses_choices": bool, "choices": int, ...}`
    (e.g. `basic.choices=3`, `premium.choices=12`). A tier's raw `choices` count can
    exceed the month's actual pool size (observed live: Premium advertised 12 picks
    in a month with only 9 games) - `quota` here is already clamped to the pool size,
    so it never exceeds it and a tier whose raw count meets/exceeds the pool just
    means "every game," same as owning the whole thing. Tiers with `uses_choices`
    false or a non-positive `choices` count (also observed live) aren't real pick
    options and are excluded entirely.
    """

    tier_key: NonEmptyString
    quota: int = Field(ge=1)

# end class HumbleChoicePickOption


class HumbleArchive(StrictModel):
    """Normalized metadata for one Choice month or game bundle."""

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
    choice_pick_options: list[HumbleChoicePickOption] = Field(default_factory=list)

# end class HumbleArchive


VersionedHumbleArchive = Versioned[HumbleCurrentVersion, HumbleArchive]
