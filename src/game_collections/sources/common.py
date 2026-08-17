"""Source-agnostic atomic file writing shared by every scraped source."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from game_collections.models import Game, GameList, Reference
from game_collections.sources.storefronts import normalized_title


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


def _merged_references(existing: GameList, fresh: GameList) -> list[Reference]:
    """Append `fresh`'s references onto `existing`'s, never dropping either side.

    A re-crawl (or a different source claiming a file another source already
    wrote to) must not lose a previously recorded reference - e.g. an
    isthereanydeal mirror URL a later Humble crawl doesn't itself produce.
    `Reference` has plain field-wise equality, so `in` is enough to dedupe
    exact repeats without any new equality/hash code.
    """
    merged = list(existing.references)
    merged.extend(reference for reference in fresh.references if reference not in merged)
    return merged
# end def _merged_references


# WRatio score (0-100) above which two differently-worded titles are treated as
# the same game - e.g. "Foo: Deluxe Edition" vs "Foo". Not tuned against a real
# dataset; a starting point, adjustable if a live crawl shows false matches.
FUZZY_MATCH_THRESHOLD = 90.0


def _find_match(fresh_game: Game, candidates: list[Game]) -> Game | None:
    """Find the candidate representing the same game as `fresh_game`, if any.

    Tries progressively looser tiers - id overlap, exact name, normalized name,
    fuzzy similarity - so a game that only changed its title casing/punctuation
    (or gained an edition subtitle) isn't mistaken for a new game, losing its
    existing `ids`/`group` and quarantining its old entry for no reason.
    """
    for candidate in candidates:
        if set(fresh_game.ids) & set(candidate.ids):
            return candidate
        # end if
    # end for
    for candidate in candidates:
        if fresh_game.name.casefold() == candidate.name.casefold():
            return candidate
        # end if
    # end for
    fresh_normalized = normalized_title(fresh_game.name)
    for candidate in candidates:
        if fresh_normalized == normalized_title(candidate.name):
            return candidate
        # end if
    # end for
    best_candidate: Game | None = None
    best_score = FUZZY_MATCH_THRESHOLD
    for candidate in candidates:
        score = fuzz.WRatio(fresh_game.name, candidate.name)
        if score >= best_score:
            best_candidate = candidate
            best_score = score
        # end if
    # end for
    return best_candidate
# end def _find_match


def merge_game_list(existing: GameList | None, fresh: GameList, *, authoritative: bool = False) -> GameList:
    """Combine a freshly-crawled list with any already-committed list at the same path.

    Appends (never overwrites) `references`, and otherwise takes bundle-level
    metadata (`name`/`tier`/`pick_quota`) from `fresh` since that reflects the
    source of truth, not manual curation.

    With `authoritative=False` (the default), games are only ever added, never
    removed: every existing `Game` entry is kept as-is (preserving manual
    `ids:`/`group` edits a re-crawl would otherwise clobber), and only games
    from `fresh` that aren't already present by `name.casefold()` are appended.

    With `authoritative=True`, `fresh` is treated as the complete, current
    roster for this list: each `fresh` game is matched (via `_find_match`'s
    id/name/normalized-name/fuzzy cascade) against existing `games` plus any
    already-`invalid` games, preserving the matched candidate's `ids`/`group`;
    any existing/invalid game left unmatched is quarantined into the returned
    list's `invalid` field instead of being deleted, so it can be recovered if
    it reappears in a later crawl.
    """
    if existing is None:
        return fresh
    # end if
    references = _merged_references(existing, fresh)
    if not authoritative:
        existing_by_name = {game.name.casefold(): game for game in existing.games}
        fresh_names = {game.name.casefold() for game in fresh.games}
        merged_games = [existing_by_name.get(game.name.casefold(), game) for game in fresh.games]
        merged_games.extend(game for game in existing.games if game.name.casefold() not in fresh_names)
        return fresh.model_copy(update={"games": merged_games, "references": references})
    # end if

    candidates = [*existing.games, *existing.invalid]
    merged_games: list[Game] = []
    for fresh_game in fresh.games:
        match = _find_match(fresh_game, candidates)
        if match is None:
            merged_games.append(fresh_game)
        else:
            candidates.remove(match)
            merged_games.append(match)
        # end if
    # end for
    return fresh.model_copy(update={"games": merged_games, "invalid": candidates, "references": references})
# end def merge_game_list


def render_game_list_yaml(game_list: GameList, path: Path, repository_root: Path) -> str:
    """Render one game list with a relative IDE schema reference comment."""
    schema_path = os.path.relpath(repository_root / "schemas/game-list.schema.json", path.parent)
    value = game_list.model_dump(by_alias=True, mode="json", exclude_none=True)
    if not value.get("invalid"):
        value.pop("invalid", None)
    # end if
    return (
        f"# yaml-language-server: $schema={schema_path}\n"
        + yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    )
# end def render_game_list_yaml
