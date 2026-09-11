"""Persisted DekuDeals item-slug -> storefront-id lookup, reused across crawl runs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import Field, model_validator

from game_collections.models import QualifiedGameId, StrictModel
from game_collections.sources.common import atomic_write


class DekuResolutionMap(StrictModel):
    """Reviewed/cached mappings from a stable DekuDeals item slug to storefront IDs.

    Populated as bundles are crawled: once an item's `/items/<slug>` page has
    been resolved once, later crawls (any bundle featuring the same item)
    reuse the cached ids instead of re-fetching that page.
    """

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    games: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        for item_slug, ids in self.games.items():
            if not ids:
                raise ValueError(f"resolution map entry has no IDs: {item_slug}")
            # end if
            compact = [QualifiedGameId.parse(value).compact() for value in ids]
            if len(compact) != len(set(compact)):
                raise ValueError(f"resolution map entry has duplicate IDs: {item_slug}")
            # end if
            self.games[item_slug] = compact
        # end for
        return self
    # end def validate_ids

# end class DekuResolutionMap


def load_resolution_map(path: Path) -> DekuResolutionMap:
    """Load a strict cached mapping or return an empty map when absent."""
    if not path.exists():
        return DekuResolutionMap(schema=1, games={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DekuResolutionMap.model_validate(raw)
# end def load_resolution_map


def render_resolution_map(mapping: DekuResolutionMap) -> str:
    """Render the cached mapping deterministically."""
    value = mapping.model_dump(by_alias=True, mode="json")
    value["games"] = dict(sorted(value["games"].items()))
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
# end def render_resolution_map


def write_resolution_map(path: Path, mapping: DekuResolutionMap) -> None:
    """Atomically persist the cached mapping."""
    atomic_write(path, render_resolution_map(mapping))
# end def write_resolution_map
