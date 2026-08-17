"""Strict models for every Steam format read or replaced by this project."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

from pydantic import AliasChoices, Field, RootModel, StrictBool, StrictInt, StrictStr, StringConstraints, model_validator

from game_collections.models import StrictModel


SteamId64 = Annotated[str, StringConstraints(pattern=r"^[0-9]{17}$")]
NonEmptyStrictString = Annotated[StrictStr, StringConstraints(min_length=1)]
VdfBoolean = Literal["0", "1"]


class LoginUserRecord(StrictModel):
    """One exact record from Steam's ``loginusers.vdf``."""

    AccountName: NonEmptyStrictString
    PersonaName: NonEmptyStrictString
    RememberPassword: VdfBoolean
    WantsOfflineMode: VdfBoolean
    SkipOfflineModeWarning: VdfBoolean
    # Steam renamed this key from "AllowAutoLogin" to "AutoLogin" in a client update; accept either on read.
    AutoLogin: Annotated[VdfBoolean, Field(validation_alias=AliasChoices("AutoLogin", "AllowAutoLogin"))]
    # Steam stopped writing "MostRecent" in the same update; treat it as absent rather than a format error.
    MostRecent: VdfBoolean | None = None
    Timestamp: Annotated[str, StringConstraints(pattern=r"^[0-9]+$")]

# end class LoginUserRecord


class LoginUsersFile(RootModel[dict[SteamId64, LoginUserRecord]]):
    """The dynamic SteamID64 mapping nested below the VDF ``users`` root."""

    @model_validator(mode="after")
    def validate_recent_account(self) -> Self:
        if not self.root:
            raise ValueError("expected at least one Steam account, found none")
        # end if
        if any(user.MostRecent is not None for user in self.root.values()):
            recent = [steam_id for steam_id, user in self.root.items() if user.MostRecent == "1"]
            if len(recent) != 1:
                raise ValueError(f"expected exactly one MostRecent Steam account, found {len(recent)}")
            # end if
        # end if
        return self
    # end def validate_recent_account

    @property
    def most_recent_steam_id(self) -> str:
        # Prefer the explicit "MostRecent" flag when present (older Steam clients); Steam's newer
        # loginusers.vdf omits it entirely, so fall back to whichever account logged in last.
        explicit = [steam_id for steam_id, user in self.root.items() if user.MostRecent == "1"]
        if explicit:
            return explicit[0]
        # end if
        return max(self.root.items(), key=lambda item: int(item[1].Timestamp))[0]
    # end def most_recent_steam_id

# end class LoginUsersFile


class SteamPidFile(RootModel[StrictInt]):
    """The numeric contents of ``.steam/steam.pid``."""

    @model_validator(mode="after")
    def validate_pid(self) -> Self:
        if self.root <= 0:
            raise ValueError("Steam PID must be positive")
        # end if
        return self
    # end def validate_pid

# end class SteamPidFile


class CloudStorageNamespacesFile(RootModel[list[tuple[StrictInt, StrictStr]]]):
    """Namespace/version pairs from ``cloud-storage-namespaces.json``."""

    @model_validator(mode="after")
    def validate_namespaces(self) -> Self:
        namespaces = [namespace for namespace, _version in self.root]
        if len(namespaces) != len(set(namespaces)):
            raise ValueError("cloud storage contains duplicate namespaces")
        # end if
        if 1 not in namespaces:
            raise ValueError("cloud storage namespace 1 is not initialized")
        # end if
        return self
    # end def validate_namespaces

    def version_for(self, namespace: int) -> str:
        return next(version for current, version in self.root if current == namespace)
    # end def version_for

# end class CloudStorageNamespacesFile


ConflictResolutionMethod = Literal["last-write", "custom", "initial"]


class CloudStorageEntry(StrictModel):
    """One complete cloud-config cache entry."""

    key: NonEmptyStrictString
    timestamp: StrictInt = Field(gt=0)
    value: StrictStr | None = None
    is_deleted: StrictBool | None = None
    version: StrictStr | None = None
    conflictResolutionMethod: ConflictResolutionMethod | None = None
    strMethodId: StrictStr | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        has_value = self.value is not None
        is_deleted = self.is_deleted is True
        if has_value == is_deleted:
            raise ValueError("entry must contain exactly one of value or is_deleted=true")
        # end if
        if self.is_deleted is False:
            raise ValueError("is_deleted may only be present when true")
        # end if
        if self.strMethodId is not None and self.conflictResolutionMethod != "custom":
            raise ValueError("strMethodId requires conflictResolutionMethod=custom")
        # end if
        if self.conflictResolutionMethod == "custom" and not self.strMethodId:
            raise ValueError("custom conflict resolution requires strMethodId")
        # end if
        return self
    # end def validate_state

# end class CloudStorageEntry


class CloudStorageNamespaceFile(RootModel[list[tuple[StrictStr, CloudStorageEntry]]]):
    """The full namespace file as ordered outer-key/entry pairs."""

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        outer_keys: list[str] = []
        for outer_key, entry in self.root:
            if outer_key != entry.key:
                raise ValueError(f"outer key {outer_key!r} does not match entry key {entry.key!r}")
            # end if
            outer_keys.append(outer_key)
        # end for
        if len(outer_keys) != len(set(outer_keys)):
            raise ValueError("cloud namespace contains duplicate keys")
        # end if
        return self
    # end def validate_entries

    def as_dict(self) -> dict[str, CloudStorageEntry]:
        return dict(self.root)
    # end def as_dict

# end class CloudStorageNamespaceFile


class ModifiedKeysFile(RootModel[list[NonEmptyStrictString]]):
    """Keys Steam must upload for one namespace."""

    @model_validator(mode="after")
    def validate_unique(self) -> Self:
        if len(self.root) != len(set(self.root)):
            raise ValueError("modified-key file contains duplicates")
        # end if
        return self
    # end def validate_unique

# end class ModifiedKeysFile


class SteamFilterGroup(StrictModel):
    """One observed Steam dynamic-collection filter group."""

    rgOptions: list[StrictInt]
    bAcceptUnion: StrictBool

# end class SteamFilterGroup


class SteamFilterSpec(StrictModel):
    """The complete observed dynamic-collection format version 2."""

    nFormatVersion: Literal[2]
    strSearchText: StrictStr
    filterGroups: list[SteamFilterGroup]
    setSuggestions: list[StrictInt] | dict[StrictStr, StrictBool] | None = None

# end class SteamFilterSpec


class SteamCollectionPayload(StrictModel):
    """Decoded JSON stored in a ``user-collections.*`` entry."""

    id: NonEmptyStrictString
    name: NonEmptyStrictString
    added: list[StrictInt]
    removed: list[StrictInt]
    filterSpec: SteamFilterSpec | None = None

    @model_validator(mode="after")
    def validate_apps(self) -> Self:
        if any(app_id <= 0 for app_id in self.added + self.removed):
            raise ValueError("Steam app IDs must be positive")
        # end if
        if len(self.added) != len(set(self.added)) or len(self.removed) != len(set(self.removed)):
            raise ValueError("Steam collection app lists must be unique")
        # end if
        if set(self.added) & set(self.removed):
            raise ValueError("Steam collection cannot add and remove the same app")
        # end if
        return self
    # end def validate_apps

    @classmethod
    def from_entry(cls, entry: CloudStorageEntry) -> Self:
        if entry.value is None:
            raise ValueError(f"collection entry is deleted: {entry.key}")
        # end if
        try:
            raw: Any = json.loads(entry.value, object_pairs_hook=_reject_duplicate_object_keys)
        except (TypeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid collection JSON in {entry.key}: {error}") from error
        # end try
        return cls.model_validate(raw)
    # end def from_entry

# end class SteamCollectionPayload


class OwnedGame(StrictModel):
    """Relevant fields returned by Steam ``GetOwnedGames``."""

    appid: StrictInt = Field(gt=0)
    name: StrictStr | None = None
    playtime_2weeks: StrictInt | None = Field(default=None, ge=0)
    playtime_forever: StrictInt | None = Field(default=None, ge=0)
    img_icon_url: StrictStr | None = None
    has_community_visible_stats: StrictBool | None = None
    playtime_windows_forever: StrictInt | None = Field(default=None, ge=0)
    playtime_mac_forever: StrictInt | None = Field(default=None, ge=0)
    playtime_linux_forever: StrictInt | None = Field(default=None, ge=0)
    playtime_deck_forever: StrictInt | None = Field(default=None, ge=0)
    rtime_last_played: StrictInt | None = Field(default=None, ge=0)
    content_descriptorids: list[StrictInt] | None = None
    playtime_disconnected: StrictInt | None = Field(default=None, ge=0)

# end class OwnedGame


class OwnedGamesPayload(StrictModel):
    """Steam's owned-games response body."""

    game_count: StrictInt = Field(ge=0)
    games: list[OwnedGame] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.game_count != len(self.games):
            raise ValueError("Steam game_count does not match games length")
        # end if
        app_ids = [game.appid for game in self.games]
        if len(app_ids) != len(set(app_ids)):
            raise ValueError("Steam returned duplicate owned app IDs")
        # end if
        return self
    # end def validate_count

# end class OwnedGamesPayload


class GetOwnedGamesResponse(StrictModel):
    """Complete top-level ``GetOwnedGames`` response."""

    response: OwnedGamesPayload

# end class GetOwnedGamesResponse


def _reject_duplicate_object_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        # end if
        result[key] = value
    # end for
    return result
# end def _reject_duplicate_object_keys


def parse_json_strict(data: bytes, model: type[RootModel[Any] | StrictModel]) -> Any:
    """Decode UTF-8 JSON without silently accepting duplicate object keys."""
    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicate_object_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid strict JSON: {error}") from error
    # end try
    return model.model_validate(raw)
# end def parse_json_strict
