"""One-time migration: merge per-tier bundle files into one, flattened list.

Bundle/pick directories (``<provider>/bundle/<key>/`` and Humble's
``humblebundle/choice/<key>/``) currently hold one YAML file per purchase
variation - a lone ``bundle.yml``, or sibling ``tier-1.yml``..``tier-N.yml``
files sharing the same ``references``/``crawlers`` and, for cumulative
bundles, duplicating every lower tier's ``games`` into every higher tier's
file. This migration merges every such directory into one ``<key>.yml`` file
one level up, recording each game's tier membership on the game itself
(``Game.tiers``) instead of splitting it across files, so on-disk lists match
what ``sources/*/crawler.py`` writes going forward.

Pre-migration files still carry the legacy scalar ``tier: <rank>`` field the
current ``GameList`` model no longer accepts (superseded by ``tiers``), so
this module reads them as raw YAML rather than through ``load_game_list``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from game_collections.lists import load_game_list
from game_collections.models import Game, GameList
from game_collections.sources.common import (
    atomic_write,
    merge_crawlers,
    merge_references,
    merge_tiered_games,
    render_game_list_yaml,
)


class BundleVariationMigrationError(ValueError):
    """A variation directory could not be unambiguously merged."""

# end class BundleVariationMigrationError


@dataclass(frozen=True, slots=True)
class BundleVariationMigrationStep:
    """One directory's planned merge into a single flattened file."""

    old_paths: tuple[Path, ...]
    new_path: Path
    merged: GameList

# end class BundleVariationMigrationStep


def discover_variation_directories(lists_root: Path) -> list[Path]:
    """Find every ``<provider>/{bundle,choice}/<key>/`` directory holding list files.

    Mirrors ``migrations.tiers.discover_bundle_directories`` but also covers
    Humble's ``choice/<key>/`` pick-option directories (e.g.
    ``choice/2026-08/tier-1.yml``), which are a second real on-disk instance
    of the same per-variation-file shape. Flat per-offer sources (e.g.
    ``dailyindiegame/bundle/<machine_name>.yml``) and flat Choice pool files
    (``choice/YYYY-MM.yml``) have nothing matching here.
    """
    directories: list[Path] = []
    for provider_dir in sorted(p for p in lists_root.iterdir() if p.is_dir()):
        for parent_name in ("bundle", "choice"):
            parent_dir = provider_dir / parent_name
            if not parent_dir.is_dir():
                continue
            # end if
            for variation_dir in sorted(p for p in parent_dir.iterdir() if p.is_dir()):
                if any(variation_dir.glob("*.yml")):
                    directories.append(variation_dir)
                # end if
            # end for
        # end for
    # end for
    return directories
# end def discover_variation_directories


def _load_legacy_list(path: Path) -> tuple[GameList, int | None]:
    """Load one pre-migration file, returning its validated content plus its legacy ``tier``.

    The legacy scalar ``tier`` field is popped before validation since the
    current strict `GameList` model no longer declares it.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tier = raw.pop("tier", None)
    return GameList.model_validate(raw), tier
# end def _load_legacy_list


def _tier_name(list_name: str, bundle_name: str) -> str:
    """Recover a variation's own display name from its file's ``name`` field.

    Writers name each tier file ``f"{bundle_name} — {tier_name}"``; strip that
    shared prefix back off so the merged file doesn't repeat the bundle name
    once per `TierDefinition`.
    """
    prefix = f"{bundle_name} — "
    if list_name.startswith(prefix):
        return list_name[len(prefix):]
    # end if
    return list_name
# end def _tier_name


def _bundle_name(list_names: list[str]) -> str:
    """Recover the shared bundle name from a set of ``f"{name} — {tier}"`` list names."""
    prefixes = {base for base, separator, _tier in (name.partition(" — ") for name in list_names) if separator}
    if len(prefixes) == 1:
        return prefixes.pop()
    # end if
    # No shared " — " convention (or an ambiguous one): fall back to the
    # highest-ranked file's own full name, matching single-tier behavior.
    return list_names[-1]
# end def _bundle_name


def plan_variation_directory(variation_dir: Path) -> BundleVariationMigrationStep:
    """Merge every list file in one variation directory into one flattened file."""
    paths = sorted(variation_dir.glob("*.yml"))
    new_path = variation_dir.parent / f"{variation_dir.name}.yml"
    loaded = [_load_legacy_list(path) for path in paths]

    if len(loaded) == 1:
        data, _tier = loaded[0]
        merged = data.model_copy(
            update={"tiers": [], "games": [game.model_copy(update={"tiers": []}) for game in data.games]}
        )
        return BundleVariationMigrationStep(old_paths=tuple(paths), new_path=new_path, merged=merged)
    # end if

    ranked = sorted(loaded, key=lambda item: item[1] if item[1] is not None else 1)
    bundle_name = _bundle_name([data.name for data, _tier in ranked])

    tier_entries = [
        (rank if rank is not None else 1, _tier_name(data.name, bundle_name), data.games, data.pick_quota)
        for data, rank in ranked
    ]
    tier_definitions, games = merge_tiered_games(tier_entries)

    accumulated = ranked[0][0]
    for data, _rank in ranked[1:]:
        accumulated = accumulated.model_copy(
            update={"references": merge_references(accumulated, data), "crawlers": merge_crawlers(accumulated, data)}
        )
    # end for

    merged = GameList(
        schema=1,
        name=bundle_name,
        tiers=tier_definitions,
        references=accumulated.references,
        crawlers=accumulated.crawlers,
        games=games,
    )
    return BundleVariationMigrationStep(old_paths=tuple(paths), new_path=new_path, merged=merged)
# end def plan_variation_directory


def plan_migration(lists_root: Path) -> list[BundleVariationMigrationStep]:
    """Plan every directory merge across the whole ``lists_root`` tree."""
    return [plan_variation_directory(variation_dir) for variation_dir in discover_variation_directories(lists_root)]
# end def plan_migration


def step_would_change(step: BundleVariationMigrationStep) -> bool:
    """Whether applying `step` would actually write/rename/delete anything."""
    if len(step.old_paths) != 1:
        return True
    # end if
    return step.old_paths[0] != step.new_path
# end def step_would_change


def apply_migration_step(step: BundleVariationMigrationStep, lists_root: Path, repository_root: Path) -> None:
    """Write the merged file, validate it, then remove the old sibling file(s)/directory."""
    content = render_game_list_yaml(step.merged, step.new_path, repository_root)
    atomic_write(step.new_path, content)
    load_game_list(step.new_path, lists_root)
    old_dir = step.old_paths[0].parent
    for old_path in step.old_paths:
        if old_path != step.new_path:
            old_path.unlink()
        # end if
    # end for
    if old_dir != step.new_path and old_dir.is_dir() and not any(old_dir.iterdir()):
        old_dir.rmdir()
    # end if
# end def apply_migration_step
