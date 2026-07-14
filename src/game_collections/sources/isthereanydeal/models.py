"""Strict normalized models for archived isthereanydeal.com (ITAD) bundle offers."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from game_collections.models import NonEmptyString, StrictModel


class ItadPrice(StrictModel):
    """A localized tier price as shown on the ITAD bundle detail page."""

    raw: NonEmptyString
    value: float = Field(ge=0)
    currency: NonEmptyString

# end class ItadPrice


class ItadItem(StrictModel):
    """One game advertised within an ITAD bundle tier.

    Unlike Humble/GreenManGaming, ITAD's own detail page usually links
    straight to a storefront (most often Steam) per game, so `ids` is
    resolved directly while parsing - there is no durable resolution map or
    interactive title-search step here. `ids` holds every qualified ID found
    (rarely more than one store), or a single `unresolved:source:...` entry
    when the detail page has no recognized storefront link for this game.
    """

    slug: NonEmptyString
    title: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)

# end class ItadItem


class ItadTier(StrictModel):
    """A cumulative ITAD bundle tier.

    Covers three real shapes seen on the live site: named cumulative tiers
    (Bronze/Silver/Gold, e.g. GreenManGaming-hosted bundles), a single flat
    tier covering every game at one price (e.g. most Humble/IndieGala-hosted
    bundles), and a single synthetic tier covering every game in a
    "Build Your Own"/mix-and-match bundle with no fixed price (`price` is
    `None` there - the per-game marginal pricing table isn't modeled).
    """

    identifier: NonEmptyString
    name: NonEmptyString
    item_count: int = Field(ge=0)
    price: ItadPrice | None = None
    items: list[ItadItem]

    @model_validator(mode="after")
    def validate_item_count(self) -> Self:
        if self.item_count != len(self.items):
            raise ValueError("tier item count does not match its item list")
        # end if
        return self
    # end def validate_item_count

# end class ItadTier


class ItadByobTier(StrictModel):
    """One purchasable "pick N of the pool" option on a Build Your Own bundle.

    Verified live against `liveData.byob` on real ITAD BYOB bundle detail
    pages (e.g. bundle 16385, "Build Your Own Best of Killer Bundle"):
    `[{"count": 5, "price": [120, "EUR"]}, {"count": 10, "price": [100, "EUR"]}, ...]`,
    always ascending by `count`. Distinct from `ItadTier`, which for a BYOB
    bundle only ever holds one synthetic tier covering the whole pool.
    """

    count: int = Field(ge=1)
    price: ItadPrice | None = None

# end class ItadByobTier


class ItadDates(StrictModel):
    """Offer availability and observation timestamps."""

    start: datetime | None = None
    expiry: datetime | None = None
    crawled: datetime

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        for value in (self.start, self.expiry, self.crawled):
            if value is not None and value.tzinfo is None:
                raise ValueError("ITAD timestamps must include a timezone")
            # end if
        # end for
        return self
    # end def validate_aware

# end class ItadDates


class ItadArchive(StrictModel):
    """Normalized metadata for one ITAD bundle offer."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    id: int = Field(gt=0)
    title: NonEmptyString
    provider_name: NonEmptyString
    provider_slug: NonEmptyString
    real_slug: NonEmptyString
    url: HttpUrl
    dates: ItadDates
    tiers: list[ItadTier] = Field(min_length=1)
    byob_tiers: list[ItadByobTier] = Field(default_factory=list)

# end class ItadArchive


class ItadGameArchive(StrictModel):
    """Normalized metadata for one ITAD per-game detail page (`/game/<slug>/info/`).

    `appid` is the Steam AppID read directly off the page's own embedded
    `detail.appid` field when present - `None` for games with no Steam
    release. `ids` is every qualified ID resolved for this game (Steam via
    `appid`, plus any other storefront resolved from its `deals`), always
    including `isthereanydeal:<slug>` itself.
    """

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    slug: NonEmptyString
    title: NonEmptyString
    appid: int | None = Field(default=None, gt=0)
    ids: list[NonEmptyString] = Field(min_length=1)
    url: HttpUrl
    dates: ItadDates

# end class ItadGameArchive


class ItadPageInfo(StrictModel):
    """The aggregator's label for a bundle's origin selling platform."""

    id: int
    name: NonEmptyString
    shop_id: int | None = Field(alias="shopId", default=None)

# end class ItadPageInfo


class ItadCounts(StrictModel):
    """Per-bundle engagement counters reported by the list API."""

    games: int = Field(ge=0)
    media: int = Field(ge=0)
    waitlist: int = Field(ge=0)
    collection: int = Field(ge=0)
    comments: int = Field(ge=0)

# end class ItadCounts


class ItadListSummary(StrictModel):
    """The verbatim shape of one `POST /bundles/api/list/` entry, validated.

    "Store verbatim" means validated through this strict model - unknown or
    changed fields fail loudly like every other archived source here - not
    an unchecked passthrough of the raw JSON.
    """

    id: int = Field(gt=0)
    title: NonEmptyString
    page: ItadPageInfo
    url: NonEmptyString
    is_mature: bool = Field(alias="isMature")
    is_pending: bool = Field(alias="isPending")
    start: int | None = None
    expiry: int | None = None
    counts: ItadCounts
    byob: bool

# end class ItadListSummary
