from __future__ import annotations

from pathlib import Path

from game_collections.models import Game, GameList, Reference
from game_collections.sources.common import dump_json, load_cached_archive, merge_game_list
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


def _list(*games: Game, name: str = "Bundle", invalid: list[Game] | None = None) -> GameList:
    return GameList(
        schema=1,
        name=name,
        references=[Reference(name="ref", url="https://example.com")],
        games=list(games),
        invalid=invalid or [],
    )
# end def _list


def test_merge_game_list_with_no_existing_file_returns_fresh_unchanged() -> None:
    fresh = _list(Game(name="One", ids=["steam:1"]))
    assert merge_game_list(None, fresh) is fresh
# end def test_merge_game_list_with_no_existing_file_returns_fresh_unchanged


def test_merge_game_list_preserves_manually_edited_ids() -> None:
    existing = _list(Game(name="One", ids=["steam:1", "gog:one"]))
    fresh = _list(Game(name="One", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh)

    assert [game.ids for game in merged.games] == [["steam:1", "gog:one"]]
# end def test_merge_game_list_preserves_manually_edited_ids


def test_merge_game_list_appends_new_games_without_disturbing_existing() -> None:
    existing = _list(Game(name="One", ids=["steam:1", "gog:one"]))
    fresh = _list(Game(name="One", ids=["steam:1"]), Game(name="Two", ids=["steam:2"]))

    merged = merge_game_list(existing, fresh)

    assert [game.name for game in merged.games] == ["One", "Two"]
    assert merged.games[0].ids == ["steam:1", "gog:one"]
    assert merged.games[1].ids == ["steam:2"]
# end def test_merge_game_list_appends_new_games_without_disturbing_existing


def test_merge_game_list_never_removes_a_game_absent_from_the_fresh_crawl() -> None:
    existing = _list(Game(name="One", ids=["steam:1"]), Game(name="Two", ids=["steam:2"]))
    fresh = _list(Game(name="One", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh)

    assert {game.name for game in merged.games} == {"One", "Two"}
# end def test_merge_game_list_never_removes_a_game_absent_from_the_fresh_crawl


def test_merge_game_list_takes_bundle_metadata_from_fresh() -> None:
    existing = _list(Game(name="One", ids=["steam:1"]), name="Old Name")
    fresh = _list(Game(name="One", ids=["steam:1"]), name="New Name")

    merged = merge_game_list(existing, fresh)

    assert merged.name == "New Name"
# end def test_merge_game_list_takes_bundle_metadata_from_fresh


def test_merge_game_list_appends_references_instead_of_overwriting() -> None:
    itad_reference = Reference(name="isthereanydeal.com bundle", url="https://isthereanydeal.com/bundle/x/")
    humble_reference = Reference(name="Humble Bundle offer", url="https://www.humblebundle.com/games/x")
    existing = GameList(
        schema=1,
        name="Bundle",
        references=[itad_reference],
        games=[Game(name="One", ids=["steam:1"])],
    )
    fresh = GameList(
        schema=1,
        name="Bundle",
        references=[humble_reference],
        games=[Game(name="One", ids=["steam:1"])],
    )

    merged = merge_game_list(existing, fresh)

    assert merged.references == [itad_reference, humble_reference]
# end def test_merge_game_list_appends_references_instead_of_overwriting


def test_merge_game_list_authoritative_quarantines_games_absent_from_fresh() -> None:
    existing = _list(Game(name="One", ids=["steam:1"]), Game(name="Two", ids=["steam:2"]))
    fresh = _list(Game(name="One", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [game.name for game in merged.games] == ["One"]
    assert [game.name for game in merged.invalid] == ["Two"]
# end def test_merge_game_list_authoritative_quarantines_games_absent_from_fresh


def test_merge_game_list_authoritative_matches_by_id_despite_renamed_title() -> None:
    existing = _list(Game(name="Old Title", ids=["steam:1", "gog:old-title"]))
    fresh = _list(Game(name="New Title", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [(game.name, game.ids) for game in merged.games] == [("Old Title", ["steam:1", "gog:old-title"])]
    assert merged.invalid == []
# end def test_merge_game_list_authoritative_matches_by_id_despite_renamed_title


def test_merge_game_list_authoritative_matches_by_exact_name_without_shared_ids() -> None:
    existing = _list(Game(name="Same Name", ids=["gog:same-name"]))
    fresh = _list(Game(name="Same Name", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [(game.name, game.ids) for game in merged.games] == [("Same Name", ["gog:same-name"])]
    assert merged.invalid == []
# end def test_merge_game_list_authoritative_matches_by_exact_name_without_shared_ids


def test_merge_game_list_authoritative_matches_by_normalized_name() -> None:
    existing = _list(Game(name="Foo: The Game", ids=["gog:foo"]))
    fresh = _list(Game(name="foo the game", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [(game.name, game.ids) for game in merged.games] == [("Foo: The Game", ["gog:foo"])]
    assert merged.invalid == []
# end def test_merge_game_list_authoritative_matches_by_normalized_name


def test_merge_game_list_authoritative_matches_by_fuzzy_similarity() -> None:
    existing = _list(Game(name="Foo", ids=["gog:foo"]))
    fresh = _list(Game(name="Foo: Deluxe Edition", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [(game.name, game.ids) for game in merged.games] == [("Foo", ["gog:foo"])]
    assert merged.invalid == []
# end def test_merge_game_list_authoritative_matches_by_fuzzy_similarity


def test_merge_game_list_authoritative_never_fuzzy_matches_different_numbered_installments() -> None:
    """A live crawl found `fuzz.WRatio("...Collection One", "...Collection Three")` scoring
    ~94 - above the fuzzy threshold - which wrongly merged two different entries in a
    numbered series and produced a duplicate game name in the output."""
    existing = _list(
        Game(name="Forgotten Realms: The Archives - Collection Three", ids=["steam:1904530"])
    )
    fresh = _list(
        Game(
            name="Forgotten Realms: The Archives - Collection One",
            ids=["unresolved:source:humblebundle:collection-one"],
        )
    )

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [(game.name, game.ids) for game in merged.games] == [
        ("Forgotten Realms: The Archives - Collection One", ["unresolved:source:humblebundle:collection-one"])
    ]
    assert [game.name for game in merged.invalid] == ["Forgotten Realms: The Archives - Collection Three"]
# end def test_merge_game_list_authoritative_never_fuzzy_matches_different_numbered_installments


def test_merge_game_list_authoritative_treats_unrelated_titles_as_new_and_quarantines_old() -> None:
    existing = _list(Game(name="Completely Different Game", ids=["gog:cdg"]))
    fresh = _list(Game(name="Totally Unrelated Title", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [game.name for game in merged.games] == ["Totally Unrelated Title"]
    assert [game.name for game in merged.invalid] == ["Completely Different Game"]
# end def test_merge_game_list_authoritative_treats_unrelated_titles_as_new_and_quarantines_old


def test_merge_game_list_authoritative_restores_a_previously_invalid_game_that_reappears() -> None:
    existing = _list(Game(name="One", ids=["steam:1"]), invalid=[Game(name="Two", ids=["steam:2"])])
    fresh = _list(Game(name="One", ids=["steam:1"]), Game(name="Two", ids=["steam:2"]))

    merged = merge_game_list(existing, fresh, authoritative=True)

    assert [game.name for game in merged.games] == ["One", "Two"]
    assert merged.invalid == []
# end def test_merge_game_list_authoritative_restores_a_previously_invalid_game_that_reappears


def test_merge_game_list_non_authoritative_never_removes_or_quarantines() -> None:
    existing = _list(Game(name="One", ids=["steam:1"]), Game(name="Two", ids=["steam:2"]))
    fresh = _list(Game(name="One", ids=["steam:1"]))

    merged = merge_game_list(existing, fresh, authoritative=False)

    assert {game.name for game in merged.games} == {"One", "Two"}
    assert merged.invalid == []
# end def test_merge_game_list_non_authoritative_never_removes_or_quarantines


def test_merge_game_list_does_not_duplicate_identical_references() -> None:
    reference = Reference(name="Humble Bundle offer", url="https://www.humblebundle.com/games/x")
    existing = GameList(
        schema=1,
        name="Bundle",
        references=[reference],
        games=[Game(name="One", ids=["steam:1"])],
    )
    fresh = GameList(
        schema=1,
        name="Bundle",
        references=[reference],
        games=[Game(name="One", ids=["steam:1"])],
    )

    merged = merge_game_list(existing, fresh)

    assert merged.references == [reference]
# end def test_merge_game_list_does_not_duplicate_identical_references
