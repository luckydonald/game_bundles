"""Pydantic models for the public game-list format."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, model_validator


# The trailing character class matches the middle one minus "/" (never end a path
# segment in a separator) rather than being alnum-only, since flattening a bundle
# directory into `<key>.yml` can leave any of its other allowed punctuation
# (e.g. a scraped key ending in ")") as the new final character.
LIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/%&'()+/-]*[A-Za-z0-9._%&'()+-]$")
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
    # Ranks (from the enclosing GameList's `tiers`) this game is included in. Empty when
    # the list has no `tiers` (not a multi-variation bundle). Stored as a full membership
    # list rather than just the lowest rank so a non-cumulative bundle (e.g. a
    # build-your-own-bundle tier that shares one game pool across every rank) is
    # representable, not just cumulative tiers where membership is contiguous.
    tiers: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list)

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


class TierDefinition(StrictModel):
    """One purchase variation ("tier") of a bundle list."""

    rank: Annotated[int, Field(ge=1)]
    name: NonEmptyString
    pick_quota: Annotated[int, Field(ge=1)] | None = None

# end class TierDefinition


def duplicate_qualified_ids(games: list[Game]) -> list[str]:
    """Return compact qualified IDs that appear on more than one game, if any."""
    identities = [identifier.compact() for game in games for identifier in game.qualified_ids]
    seen: set[str] = set()
    duplicates: list[str] = []
    for identity in identities:
        if identity in seen and identity not in duplicates:
            duplicates.append(identity)
        # end if
        seen.add(identity)
    # end for
    return duplicates
# end def duplicate_qualified_ids


class GameList(StrictModel):
    """The complete contents of one ``lists/**/*.yml`` file."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    name: NonEmptyString
    # Purchase variations ("tiers") this bundle offers, ordered by rank. Empty for lists
    # that aren't a multi-variation bundle. When present, every Game.tiers value must
    # reference one of these ranks (see validate_games below).
    tiers: list[TierDefinition] = Field(default_factory=list)
    pick_quota: Annotated[int, Field(ge=1)] | None = None
    references: list[Reference] = Field(default_factory=list)
    # Crawler module slugs (e.g. "humblebundle", "isthereanydeal") that have
    # contributed to or verified this list. Lets a later crawler tell an
    # already-covered bundle from one it has actually cross-checked.
    crawlers: list[NonEmptyString] = Field(default_factory=list)
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

        if duplicate_qualified_ids(self.games):
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

        ranks = [tier.rank for tier in self.tiers]
        if len(ranks) != len(set(ranks)):
            raise ValueError("list contains duplicate tier ranks")
        # end if

        known_ranks = set(ranks)
        for game in self.games:
            if not self.tiers and game.tiers:
                raise ValueError(f"game {game.name!r} has tiers but the list defines none")
            # end if
            unknown = [rank for rank in game.tiers if rank not in known_ranks]
            if unknown:
                raise ValueError(f"game {game.name!r} references unknown tier rank(s) {unknown}")
            # end if
        # end for
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
