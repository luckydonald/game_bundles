"""Version-step list migrating archived Humble `metadata.json`/`source.json` to the current shape."""

from __future__ import annotations

from typing import Any

from game_collections.sources.common import migrate_dates_to_confidence
from game_collections.sources.humblebundle.models import HUMBLE_V1, HUMBLE_V2
from game_collections.sources.names import SourceName
from game_collections.versioning import MigrationStep


def _wrap_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """`LEGACY_VERSION -> HUMBLE_V1`: drop the old embedded `schema` field; the envelope now carries it."""
    data = dict(data)
    data.pop("schema", None)
    return data
# end def _wrap_legacy


def _add_confidence_dates(data: dict[str, Any]) -> dict[str, Any]:
    """`HUMBLE_V1 -> HUMBLE_V2`: `dates.start`/`dates.end` become confidence-scored, add `first_seen`."""
    data = dict(data)
    data["dates"] = migrate_dates_to_confidence(data.get("dates") or {}, SourceName.HUMBLEBUNDLE)
    return data
# end def _add_confidence_dates


METADATA_MIGRATIONS: list[MigrationStep] = [
    (HUMBLE_V1, _wrap_legacy),
    (HUMBLE_V2, _add_confidence_dates),
]

SOURCE_MIGRATIONS: list[MigrationStep] = [
    (HUMBLE_V1, _wrap_legacy),
]
