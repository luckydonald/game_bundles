from __future__ import annotations

from pathlib import Path

from game_collections.sources.common import dump_json, load_cached_archive
from game_collections.sources.dailyindiegame.models import DigArchive, DigDates, DigItem, DigPrice
from datetime import UTC, datetime


def _archive() -> DigArchive:
    price = DigPrice(raw="$0.99", value=0.99, currency="$", currency_code="USD")
    return DigArchive(
        schema=1,
        machine_name="2351",
        url="https://www.dailyindiegame.com/site_weeklybundle_2351.html",
        name="DIG Bundle 2351",
        is_adult=False,
        dates=DigDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
        game_count=1,
        total_value=price,
        bundle_price=price,
        savings_percent=0,
        savings_amount=price,
        items=[
            DigItem(
                title="Sample Game",
                ids=["steam:42"],
                url="https://store.steampowered.com/app/42",
            )
        ],
    )
# end def _archive


def _write(tmp_path: Path, archive: DigArchive, source: dict) -> tuple[Path, Path]:
    metadata_path = tmp_path / "metadata.json"
    source_path = tmp_path / "source.json"
    metadata_path.write_text(dump_json(archive.model_dump(by_alias=True, mode="json")), encoding="utf-8")
    source_path.write_text(dump_json(source), encoding="utf-8")
    return metadata_path, source_path
# end def _write


def test_load_cached_archive_round_trips(tmp_path: Path) -> None:
    archive = _archive()
    metadata_path, source_path = _write(tmp_path, archive, {"alpha": 1})

    result = load_cached_archive(DigArchive, metadata_path, source_path)

    assert result is not None
    loaded_archive, loaded_source = result
    assert loaded_archive == archive
    assert loaded_source == {"alpha": 1}
# end def test_load_cached_archive_round_trips


def test_load_cached_archive_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_cached_archive(DigArchive, tmp_path / "metadata.json", tmp_path / "source.json") is None
# end def test_load_cached_archive_returns_none_when_missing


def test_load_cached_archive_returns_none_on_schema_mismatch(tmp_path: Path) -> None:
    archive = _archive()
    metadata_path, source_path = _write(tmp_path, archive, {})
    corrupted = metadata_path.read_text(encoding="utf-8").replace('"schema": 1', '"schema": 2')
    metadata_path.write_text(corrupted, encoding="utf-8")

    assert load_cached_archive(DigArchive, metadata_path, source_path) is None
# end def test_load_cached_archive_returns_none_on_schema_mismatch


def test_load_cached_archive_returns_none_on_invalid_json(tmp_path: Path) -> None:
    metadata_path = tmp_path / "metadata.json"
    source_path = tmp_path / "source.json"
    metadata_path.write_text("not json", encoding="utf-8")
    source_path.write_text("{}", encoding="utf-8")

    assert load_cached_archive(DigArchive, metadata_path, source_path) is None
# end def test_load_cached_archive_returns_none_on_invalid_json
