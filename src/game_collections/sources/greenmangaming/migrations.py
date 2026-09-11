"""Version-step list migrating archived GreenManGaming `metadata.json`/`source.json` to the current shape."""

from __future__ import annotations

from typing import Any

from game_collections.sources.common import migrate_dates_to_confidence
from game_collections.sources.greenmangaming.models import GMG_V1, GMG_V2
from game_collections.sources.names import SourceName
from game_collections.versioning import MigrationStep


def _wrap_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """`LEGACY_VERSION -> GMG_V1`: drop the old embedded `schema` field; the envelope now carries it."""
    data = dict(data)
    data.pop("schema", None)
    return data
# end def _wrap_legacy


def _add_confidence_dates(data: dict[str, Any]) -> dict[str, Any]:
    """`GMG_V1 -> GMG_V2`: `dates.end` becomes confidence-scored (was always `None` before this plan), add `first_seen`."""
    data = dict(data)
    data["dates"] = migrate_dates_to_confidence(data.get("dates") or {}, SourceName.GREENMANGAMING)
    return data
# end def _add_confidence_dates


METADATA_MIGRATIONS: list[MigrationStep] = [
    (GMG_V1, _wrap_legacy),
    (GMG_V2, _add_confidence_dates),
]

SOURCE_MIGRATIONS: list[MigrationStep] = [
    (GMG_V1, _wrap_legacy),
]
