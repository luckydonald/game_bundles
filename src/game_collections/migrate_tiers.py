"""One-time migration: rename tier-shaped bundle lists and populate ``tier``.

Renames every already-generated ``lists/<provider>/bundle/<key>/*.yml`` bundle
directory to the current writer convention (a lone tier becomes ``bundle.yml``
with no ``tier`` field; sibling tiers become ``tier-<rank>.yml`` with an
explicit ``tier: <rank>`` field), so on-disk lists match what the crawlers in
``sources/*/crawler.py`` write going forward and the Steam adapter's tier
selection no longer depends on any file predating that convention.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.sources.common import atomic_write, render_game_list_yaml


TIER_STEM_PATTERN = re.compile(r"^tier-(?P<rank>[0-9]+)$")
ITEM_BUNDLE_STEM_PATTERN = re.compile(r"^(?:entire-)?(?P<rank>[0-9]+)-item-bundle$")


class TierMigrationError(ValueError):
    """A bundle directory could not be unambiguously migrated."""

# end class TierMigrationError


@dataclass(frozen=True, slots=True)
class TierMigrationStep:
    """One file's planned rename and/or ``tier`` field assignment."""

    old_path: Path
    new_path: Path
    tier: int | None

# end class TierMigrationStep


def step_would_change(step: TierMigrationStep, lists_root: Path) -> bool:
    """Whether applying ``step`` would actually rewrite or rename anything."""
    if step.new_path != step.old_path:
        return True
    # end if
    return load_game_list(step.old_path, lists_root).data.tier != step.tier
# end def step_would_change


def discover_bundle_directories(lists_root: Path) -> list[Path]:
    """Find every ``<provider>/bundle/<key>/`` directory holding list files.

    Flat per-offer sources (e.g. ``dailyindiegame/bundle/<machine_name>.yml``,
    with no per-bundle subdirectory) have nothing matching here and are left
    untouched, since they never had a tier concept to begin with.
    """
    directories: list[Path] = []
    for provider_dir in sorted(p for p in lists_root.iterdir() if p.is_dir()):
        bundle_root = provider_dir / "bundle"
        if not bundle_root.is_dir():
            continue
        # end if
        for bundle_dir in sorted(p for p in bundle_root.iterdir() if p.is_dir()):
            if any(bundle_dir.glob("*.yml")):
                directories.append(bundle_dir)
            # end if
        # end for
    # end for
    return directories
# end def discover_bundle_directories


def _identifier_order_from_metadata(sample_path: Path, lists_root: Path) -> dict[str, int]:
    """Read the linked archive's ``tiers`` order for filenames not otherwise rankable.

    Only reached for pre-numbering-convention files (arbitrary scraped tier
    names, e.g. GreenManGaming's ``bronze.yml``/``gold.yml``), so it's fine to
    resolve the sole sample file's own ``Crawl metadata`` reference.
    """
    loaded = load_game_list(sample_path, lists_root)
    metadata_reference = next(
        (reference for reference in loaded.data.references if reference.name == "Crawl metadata"),
        None,
    )
    if metadata_reference is None or metadata_reference.path is None:
        raise TierMigrationError(f"{sample_path} has no 'Crawl metadata' reference to resolve tier order")
    # end if
    metadata_path = (sample_path.parent / metadata_reference.path).resolve()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    tiers = metadata.get("tiers")
    if not isinstance(tiers, list):
        raise TierMigrationError(f"{metadata_path} has no 'tiers' array to resolve order from")
    # end if
    order: dict[str, int] = {}
    for index, tier in enumerate(tiers, start=1):
        identifier = tier.get("identifier") if isinstance(tier, dict) else None
        if isinstance(identifier, str):
            order[identifier] = index
        # end if
    # end for
    return order
# end def _identifier_order_from_metadata


def plan_bundle_directory(bundle_dir: Path, lists_root: Path) -> list[TierMigrationStep]:
    """Decide the target filename/``tier`` value for every list in one bundle directory."""
    paths = sorted(bundle_dir.glob("*.yml"))
    if len(paths) == 1:
        path = paths[0]
        new_path = path.with_name("bundle.yml")
        return [TierMigrationStep(old_path=path, new_path=new_path, tier=None)]
    # end if

    stems = [path.stem for path in paths]
    if all(TIER_STEM_PATTERN.fullmatch(stem) for stem in stems):
        return [
            TierMigrationStep(old_path=path, new_path=path, tier=int(TIER_STEM_PATTERN.fullmatch(stem).group("rank")))
            for path, stem in zip(paths, stems, strict=True)
        ]
    # end if

    if all(ITEM_BUNDLE_STEM_PATTERN.fullmatch(stem) for stem in stems):
        ranked = sorted(
            paths, key=lambda path: int(ITEM_BUNDLE_STEM_PATTERN.fullmatch(path.stem).group("rank"))
        )
        return [
            TierMigrationStep(old_path=path, new_path=path.with_name(f"tier-{rank}.yml"), tier=rank)
            for rank, path in enumerate(ranked, start=1)
        ]
    # end if

    order = _identifier_order_from_metadata(paths[0], lists_root)
    missing = [path.stem for path in paths if path.stem not in order]
    if missing:
        raise TierMigrationError(f"{bundle_dir} has tier files not present in its archive's tier order: {missing}")
    # end if
    ranked = sorted(paths, key=lambda path: order[path.stem])
    return [
        TierMigrationStep(old_path=path, new_path=path.with_name(f"tier-{order[path.stem]}.yml"), tier=order[path.stem])
        for path in ranked
    ]
# end def plan_bundle_directory


def plan_migration(lists_root: Path) -> list[TierMigrationStep]:
    """Plan every rename/field change across the whole ``lists_root`` tree."""
    steps: list[TierMigrationStep] = []
    for bundle_dir in discover_bundle_directories(lists_root):
        steps.extend(plan_bundle_directory(bundle_dir, lists_root))
    # end for
    return steps
# end def plan_migration


def apply_migration_step(step: TierMigrationStep, lists_root: Path, repository_root: Path) -> None:
    """Rewrite (and rename, if needed) one list file, validating the result."""
    loaded = load_game_list(step.old_path, lists_root)
    if step.new_path == step.old_path and loaded.data.tier == step.tier:
        return
    # end if
    updated = loaded.data.model_copy(update={"tier": step.tier})
    content = render_game_list_yaml(updated, step.new_path, repository_root)
    atomic_write(step.new_path, content)
    load_game_list(step.new_path, lists_root)
    if step.new_path != step.old_path:
        step.old_path.unlink()
    # end if
# end def apply_migration_step
