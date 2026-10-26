from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fanatical_data import prices, product, raw_bundle
from game_collections.lists import load_game_list
from game_collections.sources.common import render_game_list_yaml
from game_collections.sources.fanatical.crawler import (
    CrawledFanaticalOffer,
    crawl_fanatical_offers,
    write_fanatical_offer,
)
from game_collections.sources.fanatical.parser import BUNDLES_API_URL
from game_collections.sources.fanatical.resolver import FanaticalResolutionMap
from game_collections.sources.storefronts import StoreCandidate
from game_collections.models import Game, GameList


CRAWLED = datetime(2026, 10, 26, tzinfo=UTC)
BUNDLE_URL = "https://www.fanatical.com/en/bundle/tiny-bundle"


def no_search(_title: str) -> list[StoreCandidate]:
    return []
# end def no_search


def listing(*items: dict[str, Any]) -> dict[str, str]:
    return {BUNDLES_API_URL: json.dumps(list(items))}
# end def listing


def crawl(pages: dict[str, str], urls: list[str] | None = None, archive_root: Path | None = None):
    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    return crawl_fanatical_offers(
        fetch,
        FanaticalResolutionMap(schema=1, games={}),
        no_search,
        urls,
        crawled=CRAWLED,
        archive_root=archive_root,
    )
# end def crawl


def pick_and_mix() -> dict[str, Any]:
    return raw_bundle(
        slug="build-your-own",
        name="Build your own",
        type="pick-and-mix",
        bundle_tiers=[
            {"displayTotal": 3, "price": prices(10), "products": [product("a", 1), product("b", 2), product("c", 3)]},
            {"displayTotal": 5, "price": prices(16), "products": None},
        ],
    )
# end def pick_and_mix


def test_crawl_accumulates_regular_tiers_and_shares_the_pick_and_mix_pool() -> None:
    report = crawl(listing(raw_bundle(), pick_and_mix()))

    assert report.errors == ()
    regular, byo = (offer.archive for offer in report.offers)
    assert [[i.slug for i in tier.items] for tier in regular.tiers] == [["one", "two"], ["one", "two", "three"]]
    assert regular.tiers[0].items[0].ids == ["steam:11", "fanatical:one"]
    assert str(regular.url) == BUNDLE_URL
    assert regular.dates.start is not None and regular.dates.start.confidence == 1.0
    assert regular.dates.first_seen == CRAWLED
    assert str(byo.url) == "https://www.fanatical.com/en/pick-and-mix/build-your-own"
    assert [[i.slug for i in tier.items] for tier in byo.tiers] == [["a", "b", "c"], ["a", "b", "c"]]
    assert [tier.display_total for tier in byo.tiers] == [3, 5]
# end def test_crawl_accumulates_regular_tiers_and_shares_the_pick_and_mix_pool


def test_explicit_urls_select_bundles_and_unlisted_ones_are_errors() -> None:
    pages = listing(raw_bundle(), pick_and_mix())

    report = crawl(pages, [BUNDLE_URL, "https://www.fanatical.com/en/bundle/gone", "https://example.com/en/bundle/x"])

    assert [offer.archive.machine_name for offer in report.offers] == ["tiny-bundle"]
    assert len(report.errors) == 2
    assert any("gone" in error and "currently listed" in error for error in report.errors)
    assert any("https://www.fanatical.com" in error for error in report.errors)
# end def test_explicit_urls_select_bundles_and_unlisted_ones_are_errors


def test_one_malformed_bundle_does_not_stop_the_others() -> None:
    broken = raw_bundle(slug="broken", fullPrice={})

    report = crawl(listing(broken, raw_bundle()))

    assert [offer.archive.machine_name for offer in report.offers] == ["tiny-bundle"]
    assert len(report.errors) == 1 and report.errors[0].startswith("broken:")
# end def test_one_malformed_bundle_does_not_stop_the_others


def test_an_unreadable_list_endpoint_is_reported_as_the_only_error() -> None:
    report = crawl({BUNDLES_API_URL: "<html>blocked</html>"})

    assert report.offers == ()
    assert len(report.errors) == 1 and BUNDLES_API_URL in report.errors[0]
# end def test_an_unreadable_list_endpoint_is_reported_as_the_only_error


def write(offer: CrawledFanaticalOffer, tmp_path: Path) -> tuple[Path, ...]:
    return write_fanatical_offer(offer, tmp_path / "lists", tmp_path / "archives", tmp_path)
# end def write


def test_write_creates_archive_and_a_dated_tiered_list_and_resumes_from_the_archive(tmp_path: Path) -> None:
    pages = listing(raw_bundle())
    offer = crawl(pages).offers[0]

    paths = write(offer, tmp_path)

    names = sorted(path.relative_to(tmp_path).as_posix() for path in paths)
    assert names == [
        "archives/fanatical/bundle/tiny-bundle/metadata.json",
        "archives/fanatical/bundle/tiny-bundle/source.json",
        "lists/fanatical/bundle/2026-10-02_tiny-bundle.yml",
    ]
    loaded = load_game_list(tmp_path / "lists/fanatical/bundle/2026-10-02_tiny-bundle.yml", tmp_path / "lists")
    game_list = loaded.data
    assert [(t.rank, t.name, t.pick_quota) for t in game_list.tiers] == [(1, "1.00 USD", None), (2, "5.00 USD", None)]
    assert {game.name: game.tiers for game in game_list.games} == {"One": [1, 2], "Two": [1, 2], "Three": [2]}
    assert game_list.crawlers == ["fanatical"]

    # A second crawl finds the archive and never needs the (here absent) list endpoint's bundle again.
    cached = crawl({BUNDLES_API_URL: "[]"}, [BUNDLE_URL], archive_root=tmp_path / "archives")
    assert cached.errors == () and cached.offers[0].archive == offer.archive
# end def test_write_creates_archive_and_a_dated_tiered_list_and_resumes_from_the_archive


def test_write_uses_pick_quota_tiers_for_pick_and_mix(tmp_path: Path) -> None:
    offer = crawl(listing(pick_and_mix())).offers[0]

    paths = write(offer, tmp_path)

    list_path = next(path for path in paths if path.suffix == ".yml")
    game_list = load_game_list(list_path, tmp_path / "lists").data
    assert [(t.name, t.pick_quota) for t in game_list.tiers] == [("pick 3", 3), ("pick 5", 5)]
    assert len(game_list.games) == 3
# end def test_write_uses_pick_quota_tiers_for_pick_and_mix


def test_a_single_pick_count_becomes_a_plain_pick_quota(tmp_path: Path) -> None:
    item = pick_and_mix()
    item["bundle_tiers"] = item["bundle_tiers"][:1]
    offer = crawl(listing(item)).offers[0]

    list_path = next(path for path in write(offer, tmp_path) if path.suffix == ".yml")

    game_list = load_game_list(list_path, tmp_path / "lists").data
    assert game_list.tiers == [] and game_list.pick_quota == 3
# end def test_a_single_pick_count_becomes_a_plain_pick_quota


def test_books_only_bundles_are_archived_without_a_list(tmp_path: Path) -> None:
    item = raw_bundle(
        slug="comics",
        bundle_tiers=[{"displayTotal": 1, "price": prices(1), "products": [product("c1", kind="comic")]}],
    )

    paths = write(crawl(listing(item)).offers[0], tmp_path)

    assert [path.name for path in paths] == ["metadata.json", "source.json"]
    assert not (tmp_path / "lists").exists()
# end def test_books_only_bundles_are_archived_without_a_list


def test_software_without_a_steam_id_is_not_listed_but_resolved_software_is(tmp_path: Path) -> None:
    item = raw_bundle(
        slug="mixed",
        bundle_tiers=[
            {
                "displayTotal": 2,
                "price": prices(1),
                "products": [product("course", None, kind="software", drm=["fanatical"]), product("tool", 77, kind="software")],
            }
        ],
    )

    list_path = next(path for path in write(crawl(listing(item)).offers[0], tmp_path) if path.suffix == ".yml")

    names = [game.name for game in load_game_list(list_path, tmp_path / "lists").data.games]
    assert names == ["Tool"]
# end def test_software_without_a_steam_id_is_not_listed_but_resolved_software_is


def test_an_existing_aggregator_list_is_backfilled_instead_of_duplicated(tmp_path: Path) -> None:
    existing = tmp_path / "lists/fanatical/bundle/2026-10-01_tiny-bundle.yml"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        render_game_list_yaml(
            GameList(name="Tiny Bundle", crawlers=["isthereanydeal"], games=[Game(name="One", ids=["itad:one"])]),
            existing,
            tmp_path,
        ),
        encoding="utf-8",
    )

    paths = write(crawl(listing(raw_bundle())).offers[0], tmp_path)

    assert [path.name for path in paths] == ["metadata.json", "source.json"]
    assert sorted(path.name for path in existing.parent.glob("*.yml")) == [existing.name]
    backfilled = load_game_list(existing, tmp_path / "lists").data
    assert backfilled.crawlers == ["isthereanydeal", "fanatical"]
    assert backfilled.games[0].ids == ["itad:one", "steam:11", "fanatical:one"]
# end def test_an_existing_aggregator_list_is_backfilled_instead_of_duplicated


def test_a_different_bundle_whose_name_contains_the_slug_is_not_mistaken_for_a_cover(tmp_path: Path) -> None:
    long_slug = raw_bundle(
        slug="online-tutor-tiny-bundle",
        bundle_tiers=[{"displayTotal": 1, "price": prices(1), "products": [product("other", 5)]}],
    )
    first = crawl(listing(long_slug)).offers[0]
    write(first, tmp_path)

    paths = write(crawl(listing(raw_bundle())).offers[0], tmp_path)

    assert any(path.name == "2026-10-02_tiny-bundle.yml" for path in paths)
# end def test_a_sibling_bundle_whose_name_contains_the_slug_is_not_mistaken_for_a_cover


def test_an_older_edition_list_is_neither_matched_nor_backfilled(tmp_path: Path) -> None:
    older = tmp_path / "lists/fanatical/bundle/2021-05-30_tiny-bundle-2.yml"
    older.parent.mkdir(parents=True)
    older.write_text(
        render_game_list_yaml(
            GameList(name="Tiny Bundle 2", crawlers=["isthereanydeal"], games=[Game(name="One", ids=["steam:11"])]),
            older,
            tmp_path,
        ),
        encoding="utf-8",
    )
    before = older.read_text(encoding="utf-8")

    paths = write(crawl(listing(raw_bundle())).offers[0], tmp_path)

    assert any(path.name == "2026-10-02_tiny-bundle.yml" for path in paths)
    assert older.read_text(encoding="utf-8") == before
# end def test_an_older_edition_list_is_neither_matched_nor_backfilled
