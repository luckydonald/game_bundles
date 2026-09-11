"""Versioned migration for `lists/**/*.yml` bundle files: the `bundle` `--type`.

`tiers.py`/`bundle_variations.py`'s detection/fallback logic (filename-pattern ranking,
the linked-archive-metadata fallback, the legacy `tier`-scalar/stable-sort fallback, the
`f"{bundle} — {tier}"` name-recovery convention) is reused here verbatim - this module
only re-homes it under the versioned wavefront engine (`versioning.trajectory`), turning
what used to be two separate one-shot migrations into one step-by-step trajectory per
bundle/choice directory:

1. `V1 -> V2`: rename every file in the directory onto its canonical tier-rank name
   (`bundle/` parents only - `choice/` is never touched here, matching `tiers.py`);
   picks the highest-ranked file as the trajectory's `primary_path`/`content`, every
   other file becomes a `pending_sibling` in descending rank order.
2. `V2 -> V3`: tag the primary file's own games with its own tier rank.
3. One step per remaining sibling, descending: fold it into `content` via
   `sources.common.merge_tiered_games` (recomputed from scratch each step off the
   accumulated `GameList`'s own `tiers`/`Game.tiers` - simple and exactly as correct as
   a true incremental accumulator for the handful of tiers a real bundle has). The last
   such step also renames `primary_path` onto the final flattened `<key>.yml`.

A flat, non-directory list file (no variation directory at all) only ever needs its
`schema:` bumped - a single no-op step.

See `sources/README.md`'s "Confidence-scored dates and the version envelope" section
and the `models.py` `GAMELIST_V1`/`GAMELIST_V2` constants.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from game_collections.migrations import tiers
from game_collections.migrations.bundle_variations import _bundle_name, _tier_name, discover_variation_directories
from game_collections.models import GAMELIST_V1, GameList, GameListV1
from game_collections.sources.common import (
    atomic_write,
    merge_crawlers,
    merge_references,
    merge_tiered_games,
    render_game_list_yaml,
)
from game_collections.versioning import SchemaIntVersion, Versioned, trajectory


_MIGRATION_ONLY_KEYS = ("schema", "tier")


def _clean_content(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip migration-only keys (`schema`/legacy `tier`) never part of `GameList`/`GameListV1`."""
    return {key: value for key, value in raw.items() if key not in _MIGRATION_ONLY_KEYS}
# end def _clean_content


def _read_content(path: Path) -> dict[str, Any]:
    return _clean_content(yaml.safe_load(path.read_text(encoding="utf-8")))
# end def _read_content


@dataclass(frozen=True, slots=True)
class BundleUnitState:
    """One bundle/choice directory's in-progress migration - see the module docstring."""

    primary_path: Path
    content: dict[str, Any]
    pending_siblings: tuple[tuple[int, Path, dict[str, Any]], ...]
    consumed: tuple[Path, ...]

# end class BundleUnitState


def discover_list_units(lists_root: Path) -> list[Path]:
    """One entry per bundle/choice variation directory, plus one per flat list file.

    Mirrors `bundle_variations.discover_variation_directories` for the directory case
    (already covers both `bundle/` and `choice/`); a flat file with no variation
    directory (e.g. `dailyindiegame/bundle/<key>.yml`, `choice/YYYY-MM.yml`) still needs
    its `schema:` bumped even though nothing structural changes, so it's its own unit.
    """
    directories = discover_variation_directories(lists_root)
    directory_files = {path for directory in directories for path in directory.glob("*.yml")}
    flat_files = [path for path in sorted(lists_root.rglob("*.yml")) if path not in directory_files]
    return [*directories, *flat_files]
# end def discover_list_units


def _rank_key(rank: int | None) -> int:
    return rank if rank is not None else 1
# end def _rank_key


def _ranked_unit_files(unit_dir: Path, lists_root: Path) -> list[tuple[int, Path, Path, dict[str, Any]]]:
    """`(rank, old_path, renamed_path, cleaned_content)` ascending by rank for one directory.

    `bundle/` directories get real renames via `tiers.plan_bundle_directory` (filename-
    pattern or archive-metadata-derived ranking, `tiers.py`'s own logic, reused
    verbatim); `choice/` directories are never renamed by that migration (it only ever
    looks under `<provider>/bundle/`), so rank instead comes straight from each file's
    legacy `tier` scalar, falling back to the files' own already-alphabetical order -
    the same fallback `bundle_variations.py` has always implicitly relied on.
    """
    if unit_dir.parent.name == "bundle":
        steps = tiers.plan_bundle_directory(unit_dir, lists_root)
        entries = [(_rank_key(step.tier), step.old_path, step.new_path, _read_content(step.old_path)) for step in steps]
    else:
        paths = sorted(unit_dir.glob("*.yml"))
        raw_contents = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in paths]
        entries = [
            (_rank_key(raw.get("tier")), path, path, _clean_content(raw))
            for path, raw in zip(paths, raw_contents, strict=True)
        ]
    # end if
    return sorted(entries, key=lambda entry: entry[0])
# end def _ranked_unit_files


def _tier_tuple(rank: int, name: str, content: dict[str, Any]) -> tuple[int, str, list[Any], int | None]:
    """One `merge_tiered_games` input tuple from one file's already-cleaned `GameListV1` content."""
    data = GameListV1.model_validate(content)
    return rank, name, data.games, None
# end def _tier_tuple


def _build_directory_steps(unit_dir: Path, lists_root: Path) -> list[tuple[SchemaIntVersion, Any]]:
    """Build one directory's own step sequence - length depends on how many tiers it has."""
    ranked = _ranked_unit_files(unit_dir, lists_root)
    final_path = unit_dir.parent / f"{unit_dir.name}.yml"
    bundle_name = _bundle_name([GameListV1.model_validate(content).name for _rank, _old, _new, content in ranked])
    tier_names = {rank: _tier_name(GameListV1.model_validate(content).name, bundle_name) for rank, _old, _new, content in ranked}

    def rename_step(_state: BundleUnitState) -> BundleUnitState:
        highest_rank, highest_old_path, highest_path, highest_content = ranked[-1]
        siblings = tuple((rank, new_path, content) for rank, _old, new_path, content in reversed(ranked[:-1]))
        superseded = (highest_old_path,) if highest_old_path != highest_path else ()
        return BundleUnitState(primary_path=highest_path, content=highest_content, pending_siblings=siblings, consumed=superseded)
    # end def rename_step

    def tag_own_step(state: BundleUnitState) -> BundleUnitState:
        highest_rank = ranked[-1][0]
        data = GameListV1.model_validate(state.content)
        if len(ranked) == 1:
            merged = GameList(name=data.name, references=data.references, crawlers=data.crawlers, games=data.games)
            superseded = (*state.consumed, state.primary_path) if state.primary_path != final_path else state.consumed
            return BundleUnitState(
                primary_path=final_path,
                content=merged.model_dump(by_alias=True, mode="json", exclude_none=True),
                pending_siblings=(),
                consumed=superseded,
            )
        else:
            _rank, name, games, _quota = _tier_tuple(highest_rank, tier_names[highest_rank], state.content)
            tier_definitions, merged_games = merge_tiered_games([(highest_rank, name, games, None)])
            merged = GameList(
                name=bundle_name,
                tiers=tier_definitions,
                references=data.references,
                crawlers=data.crawlers,
                games=merged_games,
            )
        # end if
        return replace(state, content=merged.model_dump(by_alias=True, mode="json", exclude_none=True))
    # end def tag_own_step

    def merge_next_step(state: BundleUnitState) -> BundleUnitState:
        rank, sibling_path, sibling_content = state.pending_siblings[0]
        remaining = state.pending_siblings[1:]
        current = GameList.model_validate(state.content)
        sibling_data = GameListV1.model_validate(sibling_content)
        existing_tuples = [
            (
                tier_definition.rank,
                tier_definition.name,
                [game for game in current.games if tier_definition.rank in game.tiers],
                tier_definition.pick_quota,
            )
            for tier_definition in current.tiers
        ]
        new_tuple = _tier_tuple(rank, tier_names[rank], sibling_content)
        tier_definitions, merged_games = merge_tiered_games(sorted([*existing_tuples, new_tuple], key=lambda item: item[0]))
        stub = GameList(
            name=bundle_name,
            tiers=tier_definitions,
            references=sibling_data.references,
            crawlers=sibling_data.crawlers,
            games=merged_games,
        )
        merged = GameList(
            name=bundle_name,
            tiers=tier_definitions,
            references=merge_references(current, stub),
            crawlers=merge_crawlers(current, stub),
            games=merged_games,
        )
        is_last = not remaining
        new_primary = final_path if is_last else state.primary_path
        consumed = (*state.consumed, sibling_path)
        if is_last and state.primary_path != new_primary:
            consumed = (*consumed, state.primary_path)
        # end if
        return BundleUnitState(
            primary_path=new_primary,
            content=merged.model_dump(by_alias=True, mode="json", exclude_none=True),
            pending_siblings=remaining,
            consumed=consumed,
        )
    # end def merge_next_step

    version: SchemaIntVersion = GAMELIST_V1
    steps: list[tuple[SchemaIntVersion, Any]] = []
    version += 1
    steps.append((version, rename_step))
    version += 1
    steps.append((version, tag_own_step))
    for _ in range(len(ranked) - 1):
        version += 1
        steps.append((version, merge_next_step))
    # end for
    return steps
# end def _build_directory_steps


def _current_version(unit: Path) -> SchemaIntVersion:
    """Peek one unit's actual on-disk `schema:` value (any one file, for a directory)."""
    sample = sorted(unit.glob("*.yml"))[0] if unit.is_dir() else unit
    raw = yaml.safe_load(sample.read_text(encoding="utf-8"))
    version = raw.get("schema") if isinstance(raw, dict) else None
    return version if isinstance(version, int) else GAMELIST_V1
# end def _current_version


def _initial_state(unit: Path) -> BundleUnitState:
    """The starting `BundleUnitState` for one unit, before any step has run - content unused
    for a directory unit (`rename_step` ignores it and rebuilds from `ranked` instead)."""
    if unit.is_dir():
        first_path = sorted(unit.glob("*.yml"))[0]
        return BundleUnitState(primary_path=first_path, content={}, pending_siblings=(), consumed=())
    # end if
    return BundleUnitState(primary_path=unit, content=_read_content(unit), pending_siblings=(), consumed=())
# end def _initial_state


def _flat_file_steps() -> list[tuple[SchemaIntVersion, Any]]:
    """A flat, non-directory list file only ever needs its `schema:` bumped - one no-op step."""

    def noop(state: BundleUnitState) -> BundleUnitState:
        return state
    # end def noop

    return [(GAMELIST_V1 + 1, noop)]
# end def _flat_file_steps


def build_unit_trajectory(unit: Path, lists_root: Path) -> Iterator[Versioned[SchemaIntVersion, BundleUnitState]]:
    """`versioning.trajectory` for one discovered unit (see `discover_list_units`)."""
    steps = _build_directory_steps(unit, lists_root) if unit.is_dir() else _flat_file_steps()
    return trajectory(_current_version(unit), _initial_state(unit), steps)
# end def build_unit_trajectory


def apply_unit_state(state: BundleUnitState, repository_root: Path) -> None:
    """Write `state.content` to `state.primary_path`, deleting any newly-`consumed` files.

    `consumed` is cumulative across steps (see `BundleUnitState`), so re-applying an
    earlier step's already-deleted entries here is a harmless, idempotent no-op.
    """
    game_list = GameList.model_validate(state.content)
    atomic_write(state.primary_path, render_game_list_yaml(game_list, state.primary_path, repository_root))
    parents: set[Path] = set()
    for path in state.consumed:
        parents.add(path.parent)
        if path != state.primary_path and path.exists():
            path.unlink()
        # end if
    # end for
    for parent in parents:
        if parent != state.primary_path and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        # end if
    # end for
# end def apply_unit_state


@dataclass(frozen=True, slots=True)
class BundleMigrationGroup:
    """One batch of units that all just advanced to the same `version` - see `plan_bundle_migrations`."""

    version: SchemaIntVersion
    units: tuple[Path, ...]

# end class BundleMigrationGroup


def plan_bundle_migrations(
    units: Iterable[Path], lists_root: Path
) -> Iterator[tuple[BundleMigrationGroup, dict[Path, Versioned[SchemaIntVersion, BundleUnitState]]]]:
    """Wavefront driver for `bundle`-kind units: group-by-version, advance, repeat.

    Deliberately a separate, simpler loop from `migrations.schema_versions.plan_migrations`
    rather than sharing one generic implementation: that engine's grouping key is
    `(source, file_kind, version)` over single-file JSON units, whereas a `bundle` unit
    has no source/file-kind axis and is often a whole directory of files - forcing both
    into one abstraction would cost more clarity than the duplication does.
    """
    generators: dict[Path, Iterator[Versioned[SchemaIntVersion, BundleUnitState]]] = {}
    pending: dict[Path, Versioned[SchemaIntVersion, BundleUnitState]] = {}
    for unit in units:
        generator = build_unit_trajectory(unit, lists_root)
        snapshot = next(generator, None)
        if snapshot is None:
            continue
        # end if
        generators[unit] = generator
        pending[unit] = snapshot
    # end for

    while pending:
        by_version: dict[SchemaIntVersion, list[Path]] = {}
        for unit, snapshot in pending.items():
            by_version.setdefault(snapshot.version, []).append(unit)
        # end for
        version = min(by_version)
        group_units = tuple(sorted(by_version[version]))
        yield BundleMigrationGroup(version=version, units=group_units), {unit: pending[unit] for unit in group_units}

        for unit in group_units:
            next_snapshot = next(generators[unit], None)
            if next_snapshot is None:
                del pending[unit]
            else:
                pending[unit] = next_snapshot
            # end if
        # end for
    # end while
# end def plan_bundle_migrations


def apply_bundle_migration_group(
    group: BundleMigrationGroup,
    snapshots: dict[Path, Versioned[SchemaIntVersion, BundleUnitState]],
    repository_root: Path,
) -> None:
    """Write every unit in `group` to its migrated state."""
    for unit in group.units:
        apply_unit_state(snapshots[unit].data, repository_root)
    # end for
# end def apply_bundle_migration_group


def bundle_commit_message(group: BundleMigrationGroup) -> str:
    """`[lists] bundle: Migrated N bundle list unit(s) from schema <v-1> to <v>.` per the commit-shape rules."""
    return f"[lists] bundle: Migrated {len(group.units)} bundle list unit(s) to schema {group.version}."
# end def bundle_commit_message
