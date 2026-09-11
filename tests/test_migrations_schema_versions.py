from __future__ import annotations

import json
from pathlib import Path

from game_collections.migrations.schema_versions import (
    apply_migration_group,
    classify_path,
    commit_message,
    discover_archive_paths,
    plan_migrations,
)
from game_collections.sources.dekudeals.models import DekuArchive
from game_collections.sources.dekudeals.parser import DEKU_ROOT


def _legacy_deku_metadata() -> dict:
    return {
        "schema": 1,
        "machine_name": "crawling-through-the-dungeons",
        "url": f"{DEKU_ROOT}bundles/crawling-through-the-dungeons",
        "name": "Crawling Through the Dungeons",
        "store_name": "Humble",
        "provider_slug": "humblebundle",
        "tiering_style": "price_per_tier",
        "dates": {"start": None, "end": None, "crawled": "2026-07-12T00:00:00+00:00"},
        "tiers": [
            {
                "identifier": "1",
                "price": None,
                "item_minimum": None,
                "items": [{"slug": "crawl", "title": "Crawl", "ids": ["dekudeals:crawl"]}],
            }
        ],
    }
# end def _legacy_deku_metadata


def _write_legacy_archive(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "dekudeals/bundle" / slug
    directory.mkdir(parents=True)
    metadata_path = directory / "metadata.json"
    source_path = directory / "source.json"
    metadata_path.write_text(json.dumps(_legacy_deku_metadata()), encoding="utf-8")
    source_path.write_text(json.dumps({"schema": 1, "raw": True}), encoding="utf-8")
    return metadata_path, source_path
# end def _write_legacy_archive


def test_classify_path_identifies_source_and_kind(tmp_path: Path) -> None:
    metadata_path = tmp_path / "archives/dekudeals/bundle/x/metadata.json"
    source_path = tmp_path / "archives/humblebundle/bundle/x/source.json"

    from game_collections.sources.names import SourceName

    assert classify_path(metadata_path) == (SourceName.DEKUDEALS, "metadata")
    assert classify_path(source_path) == (SourceName.HUMBLEBUNDLE, "source")
    assert classify_path(tmp_path / "lists/x.yml") is None
# end def test_classify_path_identifies_source_and_kind


def test_discover_archive_paths_finds_both_kinds(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    metadata_path, source_path = _write_legacy_archive(archive_root, "crawling-through-the-dungeons")

    found = discover_archive_paths([archive_root])

    assert set(found) == {metadata_path, source_path}
# end def test_discover_archive_paths_finds_both_kinds


def test_plan_migrations_produces_ordered_groups_and_migrates_a_real_legacy_file(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    metadata_path, source_path = _write_legacy_archive(archive_root, "crawling-through-the-dungeons")

    groups = list(plan_migrations(discover_archive_paths([archive_root])))

    # Legacy envelope-wrap for both files, then a confidence-dates content migration for metadata only.
    assert [(group.file_kind, group.from_version, group.to_version) for group, _snapshots in groups] == [
        (groups[0][0].file_kind, groups[0][0].from_version, groups[0][0].to_version),
        (groups[1][0].file_kind, groups[1][0].from_version, groups[1][0].to_version),
        (groups[2][0].file_kind, groups[2][0].from_version, groups[2][0].to_version),
    ]
    assert {group.file_kind for group, _ in groups[:2]} == {"metadata", "source"}
    assert groups[2][0].file_kind == "metadata"
    assert commit_message(groups[0][0]).startswith("[archives/dekudeals] ")
    assert commit_message(groups[0][0]).endswith(".")

    for group, snapshots in groups:
        apply_migration_group(group, snapshots)
    # end for

    migrated = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "version" in migrated and "data" in migrated
    assert "schema" not in migrated["data"]
    archive = DekuArchive.model_validate_json(json.dumps(migrated["data"]))
    assert archive.dates.start is None
    assert archive.dates.end is None
    assert archive.dates.first_seen is not None
    assert archive.dates.crawled == archive.dates.first_seen

    migrated_source = json.loads(source_path.read_text(encoding="utf-8"))
    assert migrated_source["data"] == {"raw": True}
# end def test_plan_migrations_produces_ordered_groups_and_migrates_a_real_legacy_file


def test_plan_migrations_skips_already_current_files(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    metadata_path, _source_path = _write_legacy_archive(archive_root, "crawling-through-the-dungeons")

    groups = list(plan_migrations(discover_archive_paths([archive_root])))
    for group, snapshots in groups:
        apply_migration_group(group, snapshots)
    # end for

    assert list(plan_migrations([metadata_path])) == []
# end def test_plan_migrations_skips_already_current_files
