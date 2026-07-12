"""Source-agnostic atomic file writing shared by every scraped source."""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml

from game_collections.models import GameList


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


def render_game_list_yaml(game_list: GameList, path: Path, repository_root: Path) -> str:
    """Render one game list with a relative IDE schema reference comment."""
    schema_path = os.path.relpath(repository_root / "schemas/game-list.schema.json", path.parent)
    value = game_list.model_dump(by_alias=True, mode="json", exclude_none=True)
    return (
        f"# yaml-language-server: $schema={schema_path}\n"
        + yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    )
# end def render_game_list_yaml
