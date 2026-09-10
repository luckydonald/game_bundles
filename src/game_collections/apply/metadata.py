"""Derive display metadata for the `apply` picker from already-loaded lists.

Deliberately does not open any archive JSON: source, bundle kind, item count,
date, and tier are all recoverable from ``list_id`` (a path-derived string,
see :mod:`game_collections.lists`) and the already-validated :class:`GameList`
itself, so the picker never needs a second, heavier data source.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from game_collections.lists import LoadedGameList, split_tier_suffix


DATE_SEGMENT_PATTERN = re.compile(r"^(?P<date>\d{4}-\d{2}(?:-\d{2})?)(?:_.+)?$")


@dataclass(frozen=True, slots=True)
class BundleMetadata:
    """Display-only facts about one loaded list, for filtering/rendering in the picker."""

    list_id: str
    source: str
    bundle_kind: str | None
    item_count: int
    date: str | None
    tier: int | None
    name: str

# end class BundleMetadata


def _extract_date(list_id: str) -> str | None:
    segments = list_id.split("/")
    for segment in segments[1:]:
        match = DATE_SEGMENT_PATTERN.match(segment)
        if match is not None:
            return match.group("date")
        # end if
    # end for
    return None
# end def _extract_date


def load_bundle_metadata(game_lists: list[LoadedGameList]) -> list[BundleMetadata]:
    """Build one :class:`BundleMetadata` per loaded list, in input order."""
    results: list[BundleMetadata] = []
    for game_list in game_lists:
        segments = game_list.id.split("/")
        source = segments[0]
        bundle_kind = segments[1] if len(segments) > 2 else None
        results.append(
            BundleMetadata(
                list_id=game_list.id,
                source=source,
                bundle_kind=bundle_kind,
                item_count=len(game_list.data.games),
                date=_extract_date(game_list.id),
                tier=split_tier_suffix(game_list.id)[1],
                name=game_list.data.name,
            )
        )
    # end for
    return results
# end def load_bundle_metadata
