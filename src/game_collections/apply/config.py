"""Committed selection state for `game-collections apply`/`sync`/`eligible`."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, ValidationError

from game_collections.completion import MissingHandling
from game_collections.models import StrictModel
from game_collections.sources.common import atomic_write


DEFAULT_SELECTION_CONFIG_PATH = Path("config/apply-selection.yml")


class SelectionLoadError(ValueError):
    """A selection config file could not be safely loaded."""

# end class SelectionLoadError


class ApplySelection(StrictModel):
    """Which bundles the user has explicitly opted in/out of syncing."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    selected: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    updated_at: datetime
    min_items: int | None = None
    max_items: int | None = None
    date_after: str | None = None
    date_before: str | None = None
    min_missing: int | None = None
    max_missing: int | None = 0
    min_missing_pct: float | None = None
    max_missing_pct: float | None = None
    unresolved_handling: MissingHandling = "ignore"
    unsupported_store_handling: MissingHandling = "ignore"
    tier_mode: Literal["all", "highest"] = "highest"
    show_filtered: bool = False

# end class ApplySelection


def load_selection(path: Path) -> ApplySelection | None:
    """Load a selection config, or ``None`` if it doesn't exist (no filtering)."""
    if not path.exists():
        return None
    # end if
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise SelectionLoadError(f"could not read selection config {path}: {error}") from error
    # end try
    if not isinstance(raw, dict):
        raise SelectionLoadError(f"selection config must contain an object: {path}")
    # end if
    try:
        # model_validate_json (not model_validate on the yaml.safe_load'd dict) because
        # StrictModel's strict=True otherwise rejects a datetime round-tripped as an ISO
        # string - JSON-mode validation accepts it (mirrors sources/common.py's archive loader).
        return ApplySelection.model_validate_json(json.dumps(raw))
    except ValidationError as error:
        raise SelectionLoadError(f"invalid selection config {path}:\n{error}") from error
    # end try
# end def load_selection


def save_selection(selection: ApplySelection, path: Path) -> None:
    """Atomically persist a selection config."""
    value = selection.model_dump(by_alias=True, mode="json")
    content = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    atomic_write(path, content)
# end def save_selection


def excluded_list_ids(selection: ApplySelection | None) -> set[str]:
    """List IDs a saved selection excludes; a ``None`` selection excludes nothing."""
    if selection is None:
        return set()
    # end if
    return set(selection.excluded)
# end def excluded_list_ids
