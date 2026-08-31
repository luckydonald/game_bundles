"""Pydantic models for the public game-list format."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, model_validator


LIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/%&'()+/-]*[A-Za-z0-9]$")
PROVIDER_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ReferencePath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
    Field(json_schema_extra={"format": "file-path"}),
]


class StrictModel(BaseModel):
    """Base model which treats format drift as an error."""

    model_config = ConfigDict(extra="forbid", strict=True)

# end class StrictModel


class QualifiedGameId(StrictModel):
    """A storefront-qualified game identifier such as ``steam:440``."""

    provider: NonEmptyString
    value: NonEmptyString

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Parse the public compact identifier form."""
        provider, separator, value = raw.partition(":")
        if not separator or not PROVIDER_PATTERN.fullmatch(provider) or not value:
            raise ValueError(f"invalid qualified game ID: {raw!r}")
        # end if
        return cls(provider=provider, value=value)
    # end def parse

    def compact(self) -> str:
        """Return the public compact identifier form."""
        return f"{self.provider}:{self.value}"
    # end def compact

# end class QualifiedGameId


class GameGroup(StrictModel):
    """Provenance link for Games split out of one compound source offer."""

    id: NonEmptyString
    name: NonEmptyString

# end class GameGroup


class Game(StrictModel):
    """A named game with one or more storefront identities."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)
    group: GameGroup | None = None
    # Qualified IDs of other games that must be owned/present for this entry to make sense,
    # e.g. the free base game a DLC entry needs. Purely data, no launcher-specific behavior.
    requires: list[NonEmptyString] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        parsed = [QualifiedGameId.parse(raw) for raw in self.ids]
        compact = [identifier.compact() for identifier in parsed]
        if len(compact) != len(set(compact)):
            raise ValueError("game contains duplicate qualified IDs")
        # end if
        self.ids = compact

        if self.requires:
            required_parsed = [QualifiedGameId.parse(raw) for raw in self.requires]
            required_compact = [identifier.compact() for identifier in required_parsed]
            if len(required_compact) != len(set(required_compact)):
                raise ValueError("game contains duplicate qualified required IDs")
            # end if
            self.requires = required_compact
        # end if
        return self
    # end def validate_ids

    @property
    def qualified_ids(self) -> tuple[QualifiedGameId, ...]:
        """Return parsed identities without storing a second representation."""
        return tuple(QualifiedGameId.parse(raw) for raw in self.ids)
    # end def qualified_ids

    @property
    def qualified_ids_required(self) -> tuple[QualifiedGameId, ...]:
        """Return parsed required-game identities without storing a second representation."""
        return tuple(QualifiedGameId.parse(raw) for raw in self.requires)
    # end def qualified_ids_required

# end class Game


class Reference(StrictModel):
    """A local/repository file or web source supporting a game list."""

    name: NonEmptyString
    path: ReferencePath | None = None
    url: AnyHttpUrl | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        if self.path is None and self.url is None:
            raise ValueError("reference requires a path or URL")
        # end if
        if self.path is not None and "://" in self.path:
            raise ValueError("reference path must be a local or repository path")
        # end if
        return self
    # end def validate_target

# end class Reference


class GameList(StrictModel):
    """The complete contents of one ``lists/**/*.yml`` file."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    name: NonEmptyString
    tier: Annotated[int, Field(ge=1)] | None = None
    pick_quota: Annotated[int, Field(ge=1)] | None = None
    references: list[Reference] = Field(default_factory=list)
    games: list[Game] = Field(min_length=1)
    # Games an authoritative re-crawl no longer lists, quarantined here instead of
    # deleted so they can be recovered if they reappear. Excluded from ownership,
    # eligibility, and sync consideration wherever `games` is read for that purpose.
    invalid: list[Game] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_games(self) -> Self:
        names = [game.name.casefold() for game in self.games]
        if len(names) != len(set(names)):
            raise ValueError("list contains duplicate game names")
        # end if

        identities = [identifier.compact() for game in self.games for identifier in game.qualified_ids]
        if len(identities) != len(set(identities)):
            raise ValueError("list contains duplicate qualified game IDs")
        # end if

        group_names: dict[str, str] = {}
        for game in self.games:
            if game.group is None:
                continue
            # end if
            existing_name = group_names.get(game.group.id)
            if existing_name is None:
                group_names[game.group.id] = game.group.name
            elif existing_name != game.group.name:
                raise ValueError(f"games in group {game.group.id!r} have inconsistent group names")
            # end if
        # end for

        if self.pick_quota is not None and self.pick_quota > len(self.games):
            raise ValueError(f"pick_quota {self.pick_quota} exceeds the list's {len(self.games)} game(s)")
        # end if
        return self
    # end def validate_games

# end class GameList


def validate_list_id(value: str) -> str:
    """Validate a path-derived logical list identifier."""
    if not LIST_ID_PATTERN.fullmatch(value) or "//" in value or "/../" in f"/{value}/":
        raise ValueError(f"invalid path-derived list ID: {value!r}")
    # end if
    return value
# end def validate_list_id
