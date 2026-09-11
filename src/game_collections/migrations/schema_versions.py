"""Generic version-envelope migration engine: peek -> migrate -> group -> commit, for any
archived `metadata.json`/`source.json`, across every source. See `sources/README.md`'s
"Confidence-scored dates and the version envelope" section for the design rationale.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from game_collections.sources.common import atomic_write, dump_json
from game_collections.sources.names import SourceName
from game_collections.versioning import MigrationStep, SchemaDateVersion, Versioned, peek_version, trajectory


FileKind = Literal["metadata", "source"]


@dataclass(frozen=True, slots=True)
class _SourceRegistration:
    current_version: SchemaDateVersion
    metadata_steps: tuple[MigrationStep, ...]
    source_steps: tuple[MigrationStep, ...]

# end class _SourceRegistration


def _registry() -> dict[SourceName, _SourceRegistration]:
    """Import every source's models/migrations lazily, avoiding a hard import-time cycle."""
    from game_collections.sources.dailyindiegame import migrations as dig_migrations
    from game_collections.sources.dailyindiegame import models as dig_models
    from game_collections.sources.dekudeals import migrations as deku_migrations
    from game_collections.sources.dekudeals import models as deku_models
    from game_collections.sources.greenmangaming import migrations as gmg_migrations
    from game_collections.sources.greenmangaming import models as gmg_models
    from game_collections.sources.humblebundle import migrations as humble_migrations
    from game_collections.sources.humblebundle import models as humble_models
    from game_collections.sources.isthereanydeal import migrations as itad_migrations
    from game_collections.sources.isthereanydeal import models as itad_models

    return {
        SourceName.HUMBLEBUNDLE: _SourceRegistration(
            humble_models.CURRENT_VERSION,
            tuple(humble_migrations.METADATA_MIGRATIONS),
            tuple(humble_migrations.SOURCE_MIGRATIONS),
        ),
        SourceName.GREENMANGAMING: _SourceRegistration(
            gmg_models.CURRENT_VERSION,
            tuple(gmg_migrations.METADATA_MIGRATIONS),
            tuple(gmg_migrations.SOURCE_MIGRATIONS),
        ),
        SourceName.DAILYINDIEGAME: _SourceRegistration(
            dig_models.CURRENT_VERSION,
            tuple(dig_migrations.METADATA_MIGRATIONS),
            tuple(dig_migrations.SOURCE_MIGRATIONS),
        ),
        SourceName.ISTHEREANYDEAL: _SourceRegistration(
            itad_models.CURRENT_VERSION,
            tuple(itad_migrations.METADATA_MIGRATIONS),
            tuple(itad_migrations.SOURCE_MIGRATIONS),
        ),
        SourceName.DEKUDEALS: _SourceRegistration(
            deku_models.CURRENT_VERSION,
            tuple(deku_migrations.METADATA_MIGRATIONS),
            tuple(deku_migrations.SOURCE_MIGRATIONS),
        ),
    }
# end def _registry


def classify_path(path: Path) -> tuple[SourceName, FileKind] | None:
    """Identify which source/file-kind an `archives/<source>/.../{metadata,source}.json` path is."""
    parts = path.parts
    if "archives" not in parts:
        return None
    # end if
    index = parts.index("archives")
    if index + 1 >= len(parts):
        return None
    # end if
    try:
        source = SourceName(parts[index + 1])
    except ValueError:
        return None
    # end try
    if path.name == "metadata.json":
        return source, "metadata"
    # end if
    if path.name == "source.json":
        return source, "source"
    # end if
    return None
# end def classify_path


def discover_archive_paths(roots: Iterable[Path], file_kinds: Iterable[FileKind] | None = None) -> list[Path]:
    """Recursively find every `metadata.json`/`source.json` under `roots`, optionally filtered by kind."""
    wanted = set(file_kinds) if file_kinds is not None else {"metadata", "source"}
    names = {"metadata.json" if kind == "metadata" else "source.json" for kind in wanted}
    found: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.name in names:
                found.append(root)
            # end if
            continue
        # end if
        for name in sorted(names):
            found.extend(sorted(root.rglob(name)))
        # end for
    # end for
    return sorted(set(found))
# end def discover_archive_paths


@dataclass(frozen=True, slots=True)
class MigrationGroup:
    """One batch of files that all just advanced to the same `(source, file_kind, version)`."""

    source: SourceName
    file_kind: FileKind
    from_version: SchemaDateVersion
    to_version: SchemaDateVersion
    paths: tuple[Path, ...]

# end class MigrationGroup


def plan_migrations(paths: Iterable[Path]) -> Iterator[tuple[MigrationGroup, dict[Path, Versioned]]]:
    """Wavefront driver: yield one `(MigrationGroup, {path: Versioned snapshot})` at a time.

    Every candidate file's migration only ever advances one step ahead of the current
    wavefront - never its whole end-to-end trajectory in one shot - so grouping many
    files by "which step they're on" stays memory-bounded to the current frontier, not
    every file's full history. See `versioning.trajectory` for the per-file generator
    this drives, and `sources/README.md` for why grouping must key on
    `(source, file_kind, version)`, not bare version alone.
    """
    registry = _registry()
    generators: dict[Path, Iterator[Versioned]] = {}
    kinds: dict[Path, tuple[SourceName, FileKind]] = {}
    pending: dict[Path, Versioned] = {}
    previous_version: dict[Path, SchemaDateVersion] = {}

    for path in paths:
        classified = classify_path(path)
        if classified is None or not path.exists():
            continue
        # end if
        source, kind = classified
        registration = registry[source]
        steps = registration.metadata_steps if kind == "metadata" else registration.source_steps
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        # end try
        version, data = peek_version(raw)
        generator = trajectory(version, data, list(steps))
        snapshot = next(generator, None)
        if snapshot is None:
            continue
        # end if
        generators[path] = generator
        kinds[path] = (source, kind)
        pending[path] = snapshot
        previous_version[path] = version
    # end for

    while pending:
        groups: dict[tuple[SourceName, FileKind, SchemaDateVersion], list[Path]] = defaultdict(list)
        for path, snapshot in pending.items():
            source, kind = kinds[path]
            groups[(source, kind, snapshot.version)].append(path)
        # end for
        key = min(groups, key=lambda candidate: candidate[2].sort_key())
        group_paths = tuple(sorted(groups[key]))
        from_version = min((previous_version[path] for path in group_paths), key=lambda value: value.sort_key())
        group = MigrationGroup(source=key[0], file_kind=key[1], from_version=from_version, to_version=key[2], paths=group_paths)
        yield group, {path: pending[path] for path in group_paths}

        for path in group_paths:
            previous_version[path] = pending[path].version
            next_snapshot = next(generators[path], None)
            if next_snapshot is None:
                del pending[path]
            else:
                pending[path] = next_snapshot
            # end if
        # end for
    # end while
# end def plan_migrations


def apply_migration_group(group: MigrationGroup, snapshots: dict[Path, Versioned]) -> None:
    """Write every file in `group` to its migrated `{version, data}` shape."""
    for path in group.paths:
        atomic_write(path, dump_json(snapshots[path].model_dump(mode="json")))
    # end for
# end def apply_migration_group


def commit_message(group: MigrationGroup) -> str:
    """`[archives] <source> <file_kind>: Migrating Model `<from>` -> `<to>`.` per the commit-shape rules."""
    scope = f"archives/{group.source.value}"
    return f"[{scope}] {group.file_kind}: Migrating Model `{group.from_version.render()}` → `{group.to_version.render()}`."
# end def commit_message
