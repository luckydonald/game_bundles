"""Discovery and validation for the repository's YAML game lists."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from game_collections.models import GameList, validate_list_id


class ListLoadError(ValueError):
    """A YAML list could not be safely loaded."""

# end class ListLoadError


@dataclass(frozen=True, slots=True)
class LoadedGameList:
    """A validated list paired with its path-derived identity."""

    id: str
    path: Path
    data: GameList

# end class LoadedGameList


def derive_list_id(path: Path, lists_root: Path) -> str:
    """Derive ``vendor/name`` from ``lists/vendor/name.yml``."""
    root = lists_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if path.suffix != ".yml":
        raise ListLoadError(f"list files must use .yml: {path}")
    # end if
    if path.is_symlink():
        raise ListLoadError(f"list files must not be symlinks: {path}")
    # end if
    try:
        relative = resolved.relative_to(root)
    except ValueError as error:
        raise ListLoadError(f"list escapes lists root: {path}") from error
    # end try
    return validate_list_id(relative.with_suffix("").as_posix())
# end def derive_list_id


def load_game_list(path: Path, lists_root: Path) -> LoadedGameList:
    """Load one YAML file and validate it through Pydantic."""
    list_id = derive_list_id(path, lists_root)
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ListLoadError(f"could not read YAML list {path}: {error}") from error
    # end try
    if not isinstance(raw, dict):
        raise ListLoadError(f"YAML list must contain an object: {path}")
    # end if
    try:
        data = GameList.model_validate(raw)
    except ValidationError as error:
        raise ListLoadError(f"invalid game list {path}:\n{error}") from error
    # end try
    return LoadedGameList(id=list_id, path=path, data=data)
# end def load_game_list


def discover_game_lists(
    lists_root: Path,
    on_progress: Callable[[int, int, Path], None] | None = None,
) -> list[LoadedGameList]:
    """Discover all lists and reject logical or case-insensitive collisions.

    ``on_progress``, if given, is called after each file loads with
    ``(index, total, path)`` so callers can report progress on large trees.
    """
    paths = sorted(lists_root.rglob("*.yml"))
    total = len(paths)
    loaded: list[LoadedGameList] = []
    for index, path in enumerate(paths, start=1):
        loaded.append(load_game_list(path, lists_root))
        if on_progress is not None:
            on_progress(index, total, path)
        # end if
    # end for
    seen: dict[str, Path] = {}
    for game_list in loaded:
        folded = game_list.id.casefold()
        if folded in seen:
            raise ListLoadError(
                f"duplicate or case-colliding list IDs: {seen[folded]} and {game_list.path}"
            )
        # end if
        seen[folded] = game_list.path
    # end for
    return loaded
# end def discover_game_lists

