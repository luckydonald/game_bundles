"""Source-agnostic atomic file writing shared by every scraped source."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TypeVar

import yaml
from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from game_collections.models import Game, GameList, Reference, TierDefinition, duplicate_qualified_ids
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


def merge_references(existing: GameList, fresh: GameList) -> list[Reference]:
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
# end def merge_references


def merge_crawlers(existing: GameList, fresh: GameList) -> list[str]:
    """Union `existing.crawlers` and `fresh.crawlers`, preserving `existing`'s order.

    Mirrors `merge_references`: a dedicated scraper's own re-crawl must not
    drop a `crawlers` entry a different crawler (e.g. isthereanydeal's
    backfill pass) previously recorded on this same list.
    """
    merged = list(existing.crawlers)
    merged.extend(crawler for crawler in fresh.crawlers if crawler not in merged)
    return merged
# end def merge_crawlers


# WRatio score (0-100) above which two differently-worded titles are treated as
# the same game - e.g. "Foo: Deluxe Edition" vs "Foo". Not tuned against a real
# dataset; a starting point, adjustable if a live crawl shows false matches.
FUZZY_MATCH_THRESHOLD = 90.0

_ORDINAL_WORDS = {
    "one": "1", "first": "1", "i": "1",
    "two": "2", "second": "2", "ii": "2",
    "three": "3", "third": "3", "iii": "3",
    "four": "4", "fourth": "4", "iv": "4",
    "five": "5", "fifth": "5", "v": "5",
    "six": "6", "sixth": "6", "vi": "6",
    "seven": "7", "seventh": "7", "vii": "7",
    "eight": "8", "eighth": "8", "viii": "8",
    "nine": "9", "ninth": "9", "ix": "9",
    "ten": "10", "tenth": "10", "x": "10",
}


def _number_tokens(value: str) -> set[str]:
    """Extract digit/cardinal-word/ordinal-word/roman-numeral tokens, normalized to a bare digit.

    A live crawl found `fuzz.WRatio` scoring "...Collection One" vs
    "...Collection Three" at ~94 - well above `FUZZY_MATCH_THRESHOLD` - since
    they differ by only one word out of many. Two titles whose only
    difference is which numbered installment/collection they name must never
    fuzzy-match, however similar the rest of the text is.
    """
    tokens: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", value.lower()):
        if word.isdigit():
            tokens.add(word)
        elif word in _ORDINAL_WORDS:
            tokens.add(_ORDINAL_WORDS[word])
        # end if
    # end for
    return tokens
# end def _number_tokens


def find_matching_game(fresh_game: Game, candidates: list[Game]) -> Game | None:
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
    fresh_numbers = _number_tokens(fresh_game.name)
    best_candidate: Game | None = None
    best_score = FUZZY_MATCH_THRESHOLD
    for candidate in candidates:
        if fresh_numbers != _number_tokens(candidate.name):
            continue
        # end if
        score = fuzz.WRatio(fresh_game.name, candidate.name)
        if score >= best_score:
            best_candidate = candidate
            best_score = score
        # end if
    # end for
    return best_candidate
# end def find_matching_game


def _carry_tiers(existing_game: Game, fresh_game: Game) -> Game:
    """Keep `existing_game`'s manually-preserved identity but `fresh_game`'s tier membership.

    Tier membership reflects the bundle's current, source-of-truth shape, not
    manual curation, so a re-crawl must still update it even when the rest of
    the game entry (`ids`/`group`) is preserved from `existing`.
    """
    if existing_game.tiers == fresh_game.tiers:
        return existing_game
    # end if
    return existing_game.model_copy(update={"tiers": fresh_game.tiers})
# end def _carry_tiers


def merge_game_list(existing: GameList | None, fresh: GameList, *, authoritative: bool = False) -> GameList:
    """Combine a freshly-crawled list with any already-committed list at the same path.

    Appends (never overwrites) `references`, and otherwise takes bundle-level
    metadata (`name`/`tiers`/`pick_quota`) from `fresh` since that reflects the
    source of truth, not manual curation. Each matched game's tier membership
    is likewise refreshed from `fresh` (see `_carry_tiers`) even though its
    `ids`/`group` are preserved from `existing`.

    With `authoritative=False` (the default), games are only ever added, never
    removed: every existing `Game` entry is kept as-is (preserving manual
    `ids:`/`group` edits a re-crawl would otherwise clobber), and only games
    from `fresh` that aren't already present by `name.casefold()` are appended.

    With `authoritative=True`, `fresh` is treated as the complete, current
    roster for this list: each `fresh` game is matched (via `find_matching_game`'s
    id/name/normalized-name/fuzzy cascade) against existing `games` plus any
    already-`invalid` games, preserving the matched candidate's `ids`/`group`;
    any existing/invalid game left unmatched is quarantined into the returned
    list's `invalid` field instead of being deleted, so it can be recovered if
    it reappears in a later crawl. If accepting a matched candidate would
    reintroduce a qualified ID that belongs to a *different* fresh game in this
    same pass (e.g. a stale, pre-split candidate whose IDs cover several games
    that a split-aware resolver now reports as separate fresh entries), the
    match is rejected instead: the fresh game keeps its own IDs, and the stale
    candidate remains in the pool to be quarantined into `invalid` like any
    other unmatched game.
    """
    if existing is None:
        return fresh
    # end if
    references = merge_references(existing, fresh)
    crawlers = merge_crawlers(existing, fresh)
    if not authoritative:
        existing_by_name = {game.name.casefold(): game for game in existing.games}
        fresh_names = {game.name.casefold() for game in fresh.games}
        merged_games = [
            _carry_tiers(existing_by_name[game.name.casefold()], game)
            if game.name.casefold() in existing_by_name
            else game
            for game in fresh.games
        ]
        merged_games.extend(game for game in existing.games if game.name.casefold() not in fresh_names)
        return fresh.model_copy(update={"games": merged_games, "references": references, "crawlers": crawlers})
    # end if

    candidates = [*existing.games, *existing.invalid]
    # `fresh` is already a validated GameList, so no id appears on two of its own
    # games - every id belongs to exactly one fresh game.
    total_fresh_ids = {identifier for game in fresh.games for identifier in game.ids}
    merged_games: list[Game] = []
    for fresh_game in fresh.games:
        match = find_matching_game(fresh_game, candidates)
        # A stale candidate's ids can cover several games that a split-aware resolver
        # now reports as separate fresh entries (e.g. one pre-split "Edition"/"Bundle"
        # candidate whose ids are now split across multiple fresh games - the real bug
        # this guards against). Preserving such a match would reintroduce one of those
        # ids on two different merged games, so reject it whenever the candidate's ids
        # overlap any *other* fresh game's own ids.
        other_fresh_ids = total_fresh_ids - set(fresh_game.ids)
        if match is not None and other_fresh_ids.isdisjoint(match.ids):
            candidates.remove(match)
            merged_games.append(_carry_tiers(match, fresh_game))
        else:
            merged_games.append(fresh_game)
        # end if
    # end for
    assert not duplicate_qualified_ids(merged_games), "merge_game_list produced duplicate qualified game IDs"
    return fresh.model_copy(
        update={"games": merged_games, "invalid": candidates, "references": references, "crawlers": crawlers}
    )
# end def merge_game_list


def merge_tiered_games(
    tiers: list[tuple[int, str, list[Game], int | None]],
) -> tuple[list[TierDefinition], list[Game]]:
    """Combine one bundle's per-tier game lists into one deduped roster.

    Each element is `(rank, tier_name, games, pick_quota)` for one purchase
    variation, ordered ascending by rank. A game is matched across tiers by
    its qualified IDs (deterministic per source item, so the same item always
    produces the same ID set on every tier it appears in); the first
    occurrence's `name`/`group`/`requires` win, and every rank it's found on
    is recorded on its `tiers` field. Works for both cumulative tiers (a
    higher rank's list is a superset of lower ones) and non-cumulative ones
    (e.g. a build-your-own-bundle tier sharing one identical pool across every
    rank) since membership is read directly off each rank's own list rather
    than assumed contiguous.
    """
    tier_definitions = [
        TierDefinition(rank=rank, name=name, pick_quota=quota) for rank, name, _games, quota in tiers
    ]
    merged: dict[tuple[str, ...], Game] = {}
    order: list[tuple[str, ...]] = []
    for rank, _name, games, _quota in tiers:
        for game in games:
            key = tuple(sorted(game.ids))
            existing_game = merged.get(key)
            if existing_game is None:
                merged[key] = game.model_copy(update={"tiers": [rank]})
                order.append(key)
            elif rank not in existing_game.tiers:
                merged[key] = existing_game.model_copy(update={"tiers": [*existing_game.tiers, rank]})
            # end if
        # end for
    # end for
    return tier_definitions, [merged[key] for key in order]
# end def merge_tiered_games


def render_game_list_yaml(game_list: GameList, path: Path, repository_root: Path) -> str:
    """Render one game list with a relative IDE schema reference comment."""
    schema_path = os.path.relpath(repository_root / "schemas/game-list.schema.json", path.parent)
    value = game_list.model_dump(by_alias=True, mode="json", exclude_none=True)
    if not value.get("invalid"):
        value.pop("invalid", None)
    # end if
    if not value.get("crawlers"):
        value.pop("crawlers", None)
    # end if
    if not value.get("tiers"):
        value.pop("tiers", None)
    # end if
    for game in [*value.get("games", []), *value.get("invalid", [])]:
        if not game.get("tiers"):
            game.pop("tiers", None)
        # end if
    # end for
    return (
        f"# yaml-language-server: $schema={schema_path}\n"
        + yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    )
# end def render_game_list_yaml
