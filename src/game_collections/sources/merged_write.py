from __future__ import annotations

from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.models import GameList
from game_collections.sources.common import atomic_write, merge_game_list, render_game_list_yaml


def write_merged_game_list(game_list: GameList, path: Path, lists_root: Path, repository_root: Path) -> None:
    """Merge with any already-committed list at `path` (see `merge_game_list`) before writing.

    A source is authoritative for its own bundles: a game no longer present in
    the fresh crawl is quarantined into `invalid` (never hard-deleted, and
    restored if a later crawl lists it again), while a game still present
    keeps its existing `ids:`/`group` state rather than being replaced. The
    `references` and `crawlers` another source (isthereanydeal, dekudeals, ...)
    backfilled into the list are kept too, so a direct re-crawl never resets
    them. An existing file that fails to load is a real problem (hand-edited
    into an invalid state, or a stale schema) and should fail loudly rather
    than being silently discarded and overwritten.
    """
    existing = load_game_list(path, lists_root).data if path.exists() else None
    merged = merge_game_list(existing, game_list, authoritative=True)
    atomic_write(path, render_game_list_yaml(merged, path, repository_root))
# end def write_merged_game_list
