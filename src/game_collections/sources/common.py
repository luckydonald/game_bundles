"""Source-agnostic atomic file writing shared by every scraped source."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from game_collections.models import GameList


ArchiveT = TypeVar("ArchiveT", bound=BaseModel)


def atomic_write(path: Path, content: str) -> None:
    """Write a file via a same-directory temp file, fsync, and atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # end with
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    # end try
# end def atomic_write


def dump_json(value: object) -> str:
    """Render a value as deterministic, sorted, two-space JSON."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
# end def dump_json


def load_cached_archive(
    model_cls: type[ArchiveT],
    metadata_path: Path,
    source_path: Path,
) -> tuple[ArchiveT, dict[str, object]] | None:
    """Read back a previously written archive, or None if absent/stale/corrupt.

    Used to resume a crawl without re-fetching: any failure here (missing
    file, invalid JSON, or a `model_cls` validation error - notably including
    a `schema_version` mismatch after a schema bump) is treated as a cache
    miss rather than an error, so callers can silently fall back to a real
    fetch.
    """
    if not metadata_path.exists() or not source_path.exists():
        return None
    # end if
    try:
        # model_validate_json (not model_validate on a json.loads'd dict)
        # because StrictModel's strict=True otherwise rejects datetimes
        # round-tripped as ISO strings - JSON-mode validation accepts them.
        archive = model_cls.model_validate_json(metadata_path.read_text(encoding="utf-8"))
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, ValidationError):
        return None
    # end try
    return archive, source
# end def load_cached_archive


def render_game_list_yaml(game_list: GameList, path: Path, repository_root: Path) -> str:
    """Render one game list with a relative IDE schema reference comment."""
    schema_path = os.path.relpath(repository_root / "schemas/game-list.schema.json", path.parent)
    value = game_list.model_dump(by_alias=True, mode="json", exclude_none=True)
    return (
        f"# yaml-language-server: $schema={schema_path}\n"
        + yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    )
# end def render_game_list_yaml
