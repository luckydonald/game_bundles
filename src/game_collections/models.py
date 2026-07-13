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


class Game(StrictModel):
    """A named game with one or more storefront identities."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        parsed = [QualifiedGameId.parse(raw) for raw in self.ids]
        compact = [identifier.compact() for identifier in parsed]
        if len(compact) != len(set(compact)):
            raise ValueError("game contains duplicate qualified IDs")
        # end if
        self.ids = compact
        return self
    # end def validate_ids

    @property
    def qualified_ids(self) -> tuple[QualifiedGameId, ...]:
        """Return parsed identities without storing a second representation."""
        return tuple(QualifiedGameId.parse(raw) for raw in self.ids)
    # end def qualified_ids

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
    references: list[Reference] = Field(default_factory=list)
    games: list[Game] = Field(min_length=1)

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
