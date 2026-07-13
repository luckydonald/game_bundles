"""Reviewed groups of ITAD game slugs known to be the same real-world game."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from game_collections.models import NonEmptyString, StrictModel


class ItadGameAliasConfig(StrictModel):
    """Reviewed groups of ITAD slugs that are the same real game across platforms.

    ITAD sometimes lists the same real product as separate games with their
    own gid/slug/deals per platform-specific listing - confirmed real for
    `pinball-fx-my-little-pony-pinball` (Steam DLC) vs `my-little-pony-pinball`
    (Epic DLC), neither of which references the other. Left unresolved, the
    Epic-only entry would never pick up the Steam id it should have. Each
    group lists every slug considered the same game; groups don't share
    slugs.
    """

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    aliases: list[list[NonEmptyString]] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_groups(self) -> Self:
        seen: set[str] = set()
        for group in self.aliases:
            if len(set(group)) < 2:
                raise ValueError(f"alias group must list at least 2 distinct slugs: {group!r}")
            # end if
            duplicates = seen.intersection(group)
            if duplicates:
                raise ValueError(f"slug(s) appear in more than one alias group: {sorted(duplicates)!r}")
            # end if
            seen.update(group)
        # end for
        return self
    # end def validate_groups

# end class ItadGameAliasConfig


def load_game_alias_config(path: Path) -> dict[str, frozenset[str]]:
    """Load the reviewed alias groups, keyed by every member slug, or empty if absent."""
    if not path.exists():
        return {}
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = ItadGameAliasConfig.model_validate(raw)
    groups = [frozenset(group) for group in config.aliases]
    return {slug: group for group in groups for slug in group}
# end def load_game_alias_config
