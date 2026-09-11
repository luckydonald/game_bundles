"""Version-step list migrating archived ITAD `metadata.json`/`source.json` to the current shape.

One file, in ascending-version order, per the shared `versioning.trajectory` design -
see `sources/README.md` and the confidence-scored-dates plan for why this shape was chosen.
"""

from __future__ import annotations

from typing import Any

from game_collections.sources.common import migrate_dates_to_confidence
from game_collections.sources.isthereanydeal.models import ITAD_V1, ITAD_V2
from game_collections.sources.names import SourceName
from game_collections.versioning import MigrationStep


def _wrap_legacy(data: dict[str, Any]) -> dict[str, Any]:
    """`LEGACY_VERSION -> ITAD_V1`: drop the old embedded `schema` field; the envelope now carries it."""
    data = dict(data)
    data.pop("schema", None)
    return data
# end def _wrap_legacy


def _add_confidence_dates(data: dict[str, Any]) -> dict[str, Any]:
    """`ITAD_V1 -> ITAD_V2`: `dates.start`/`dates.expiry` become confidence-scored, add `first_seen`."""
    data = dict(data)
    data["dates"] = migrate_dates_to_confidence(data.get("dates") or {}, SourceName.ISTHEREANYDEAL, ("start", "expiry"))
    return data
# end def _add_confidence_dates


METADATA_MIGRATIONS: list[MigrationStep] = [
    (ITAD_V1, _wrap_legacy),
    (ITAD_V2, _add_confidence_dates),
]

SOURCE_MIGRATIONS: list[MigrationStep] = [
    (ITAD_V1, _wrap_legacy),
]
