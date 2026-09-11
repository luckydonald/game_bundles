"""Version-step list migrating archived DailyIndieGame `metadata.json`/`source.json` to the current shape."""

from __future__ import annotations

from typing import Any

from game_collections.sources.common import migrate_dates_to_confidence
from game_collections.sources.dailyindiegame.models import DIG_V1, DIG_V2
from game_collections.sources.names import SourceName
from game_collections.versioning import MigrationStep


def _wrap_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """`LEGACY_VERSION -> DIG_V1`: drop the old embedded `schema` field; the envelope now carries it."""
    data = dict(data)
    data.pop("schema", None)
    return data
# end def _wrap_legacy


def _add_confidence_dates(data: dict[str, Any]) -> dict[str, Any]:
    """`DIG_V1 -> DIG_V2`: `dates.end` becomes confidence-scored, add `first_seen`."""
    data = dict(data)
    data["dates"] = migrate_dates_to_confidence(data.get("dates") or {}, SourceName.DAILYINDIEGAME)
    return data
# end def _add_confidence_dates


METADATA_MIGRATIONS: list[MigrationStep] = [
    (DIG_V1, _wrap_legacy),
    (DIG_V2, _add_confidence_dates),
]

SOURCE_MIGRATIONS: list[MigrationStep] = [
    (DIG_V1, _wrap_legacy),
]
