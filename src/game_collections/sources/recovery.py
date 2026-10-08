"""Holding area for scraped payloads whose archive build failed, so they need not be re-fetched.

A scrape fetches a page, extracts its embedded JSON, then builds strict pydantic models from
it. When that last step raises, nothing used to survive on disk and the next run had to fetch
the page again. The extracted payload is instead parked here, together with the error, until
a later run builds it successfully and writes it to its real archive location.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import ValidationError

from game_collections.models import StrictModel
from game_collections.sources.common import atomic_write, dump_versioned_json
from game_collections.versioning import SchemaDateVersion, peek_version


class RecoveryError(StrictModel):
    """Why the build failed, detailed enough to fix the cause without re-running the scrape."""

    type: str
    message: str
    # Pydantic's structured `errors()` (loc, msg, type, input) when the failure was a ValidationError.
    details: list[dict[str, Any]]

# end class RecoveryError


class RecoveryRecord(StrictModel):
    """One parked payload plus the failure that parked it."""

    url: str
    observed_at: datetime
    error: RecoveryError
    payload: dict[str, Any]

# end class RecoveryRecord


def recovery_path(root: Path, url: str) -> Path:
    """The holding file for `url`, keyed by its URL slug since the real archive key is unknown on failure."""
    slug = Path(urlparse(url).path).name or "index"
    return root / f"{re.sub(r'[^a-z0-9-]+', '-', slug.casefold()).strip('-') or 'index'}.json"
# end def recovery_path


def describe_error(error: Exception) -> RecoveryError:
    """Capture an exception, with the offending fields and inputs for a pydantic `ValidationError`."""
    details: list[dict[str, Any]] = []
    if isinstance(error, ValidationError):
        details = json.loads(error.json(include_url=False, include_context=False))
    # end if
    return RecoveryError(type=type(error).__name__, message=str(error), details=details)
# end def describe_error


def write_recovery(
    root: Path,
    url: str,
    payload: dict[str, Any],
    error: Exception,
    *,
    version: SchemaDateVersion,
    observed_at: datetime,
) -> Path:
    """Park `payload` and the failure under `root`, replacing any earlier record for the same URL."""
    record = RecoveryRecord(url=url, observed_at=observed_at.astimezone(UTC), error=describe_error(error), payload=payload)
    path = recovery_path(root, url)
    atomic_write(path, dump_versioned_json(version, record.model_dump(mode="json")))
    return path
# end def write_recovery


def load_recovery(root: Path, url: str, *, version: SchemaDateVersion) -> RecoveryRecord | None:
    """Read back the parked record for `url`, or None if absent, corrupt, or from another envelope version."""
    path = recovery_path(root, url)
    if not path.exists():
        return None
    # end if
    try:
        stored_version, data = peek_version(json.loads(path.read_text(encoding="utf-8")))
        if stored_version.sort_key() != version.sort_key():
            return None
        # end if
        # JSON-mode validation because strict models reject the ISO-string datetime otherwise.
        record = RecoveryRecord.model_validate_json(json.dumps(data))
    except (OSError, ValueError, ValidationError):
        return None
    # end try
    return record if record.url == url else None
# end def load_recovery


def clear_recovery(root: Path, url: str) -> None:
    """Remove the parked record for `url` once its archive was written for real."""
    recovery_path(root, url).unlink(missing_ok=True)
# end def clear_recovery
