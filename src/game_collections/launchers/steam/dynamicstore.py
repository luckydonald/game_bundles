"""The manually exported `store.steampowered.com/dynamicstore/userdata` dump.

This is Steam's own authenticated-session store-frontend endpoint (not part of
the public Web API `STEAM_WEB_API_KEY` uses) - it's what renders "in library"
badges, so unlike `GetOwnedGames` its `rgOwnedApps` genuinely includes owned
DLC AppIDs (verified live, see the "bundle-in-bundle DLC packs" plan's
Stage 0). It needs a logged-in browser session cookie this project does not
fetch on its own; the user exports the JSON themselves and this module reads
the resulting local file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Self

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from game_collections.launchers.steam.models import parse_json_strict
from game_collections.models import StrictModel
from game_collections.sources.common import atomic_write


DYNAMICSTORE_URL = "https://store.steampowered.com/dynamicstore/userdata"


class DynamicStoreCurator(StrictModel):
    """One followed curator entry within `rgCurators`."""

    clanid: StrictInt
    avatar: StrictStr
    name: StrictStr

# end class DynamicStoreCurator


class DynamicStoreTag(StrictModel):
    """One entry within `rgRecommendedTags`."""

    tagid: StrictInt
    name: StrictStr

# end class DynamicStoreTag


class SteamDynamicStoreUserData(StrictModel):
    """The complete observed `dynamicstore/userdata` payload shape.

    Every key modeled here as a best-effort type so real format drift is
    still caught (this repo's `StrictModel`/`extra=forbid` convention), even
    though only `rgOwnedApps` is actually consumed.
    """

    rgWishlist: list[StrictInt] = Field(default_factory=list)
    rgOwnedPackages: list[StrictInt] = Field(default_factory=list)
    rgOwnedApps: list[StrictInt] = Field(default_factory=list)
    rgFollowedApps: list[StrictInt] = Field(default_factory=list)
    rgMasterSubApps: list[StrictInt] = Field(default_factory=list)
    rgPackagesInCart: list[StrictInt] = Field(default_factory=list)
    rgAppsInCart: list[StrictInt] = Field(default_factory=list)
    rgRecommendedTags: list[DynamicStoreTag] = Field(default_factory=list)
    rgIgnoredApps: dict[StrictStr, StrictInt] = Field(default_factory=dict)
    rgIgnoredPackages: list[StrictInt] = Field(default_factory=list)
    rgHardwareUsed: list[StrictStr] = Field(default_factory=list)
    rgCurators: dict[StrictStr, DynamicStoreCurator] = Field(default_factory=dict)
    rgCuratorsIgnored: list[StrictInt] = Field(default_factory=list)
    rgCurations: dict[StrictStr, dict[StrictStr, StrictInt]] = Field(default_factory=dict)
    bShowFilteredUserReviewScores: StrictBool
    rgCreatorsFollowed: list[StrictInt] = Field(default_factory=list)
    rgCreatorsIgnored: list[StrictInt] = Field(default_factory=list)
    rgExcludedTags: list[StrictInt] = Field(default_factory=list)
    rgExcludedContentDescriptorIDs: list[StrictInt] = Field(default_factory=list)
    rgAutoGrantApps: list[StrictInt] = Field(default_factory=list)
    rgRecommendedApps: list[StrictInt] = Field(default_factory=list)
    rgPreferredPlatforms: list[StrictStr] = Field(default_factory=list)
    rgPrimaryLanguage: StrictInt
    rgSecondaryLanguages: list[StrictInt] = Field(default_factory=list)
    bAllowAppImpressions: StrictInt
    nCartLineItemCount: StrictInt
    nRemainingCartDiscount: StrictInt
    nTotalCartDiscount: StrictInt

# end class SteamDynamicStoreUserData


class DynamicStoreDumpFile(StrictModel):
    """The locally persisted envelope: the raw payload plus when it was fetched."""

    fetched_at: datetime
    data: SteamDynamicStoreUserData

    @field_validator("fetched_at", mode="before")
    @classmethod
    def parse_fetched_at(cls, value: object) -> object:
        # `StrictModel` (strict=True) otherwise rejects the ISO string this
        # envelope is actually stored as, accepting only a real `datetime`.
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        # end if
        return value
    # end def parse_fetched_at

    @model_validator(mode="after")
    def validate_aware(self) -> Self:
        if self.fetched_at.tzinfo is None:
            raise ValueError("dynamicstore dump fetched_at must include a timezone")
        # end if
        return self
    # end def validate_aware

# end class DynamicStoreDumpFile


def load_dynamicstore_dump(path: Path) -> DynamicStoreDumpFile:
    """Load and strictly validate a locally exported dynamicstore dump."""
    return parse_json_strict(path.read_bytes(), DynamicStoreDumpFile)
# end def load_dynamicstore_dump


def save_dynamicstore_dump(path: Path, raw_json: str, fetched_at: datetime) -> DynamicStoreDumpFile:
    """Validate a freshly pasted dump and atomically persist it with `fetched_at`."""
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid dynamicstore dump JSON: {error}") from error
    # end try
    envelope = DynamicStoreDumpFile(
        fetched_at=fetched_at,
        data=SteamDynamicStoreUserData.model_validate(payload),
    )
    atomic_write(path, envelope.model_dump_json(indent=2) + "\n")
    return envelope
# end def save_dynamicstore_dump


def should_prompt_for_refresh(*, force: bool | None, interactive: bool) -> bool:
    """Decide whether to prompt for a fresh dump paste.

    `force=True` always prompts (even outside a detected interactive
    session); `force=False` never prompts (silent skip, for CI/automation);
    `force=None` (the default) prompts only when `interactive` is true.
    """
    if force is not None:
        return force
    # end if
    return interactive
# end def should_prompt_for_refresh


def describe_dump_age(dump: DynamicStoreDumpFile | None, now: datetime) -> str:
    """Render a human "Last updated: ..." line, or a not-yet-exported notice."""
    if dump is None:
        return "No dynamicstore dump has been exported yet."
    # end if
    age = now.astimezone(dump.fetched_at.tzinfo) - dump.fetched_at
    days = age.days
    if days <= 0:
        relative = "today"
    elif days == 1:
        relative = "1 day ago"
    else:
        relative = f"{days} days ago"
    # end if
    timestamp = dump.fetched_at.strftime("%Y-%m-%d %H:%M %Z")
    return f"Last updated: {timestamp} ({relative})"
# end def describe_dump_age
