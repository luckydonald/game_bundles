from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from digiphile_data import listing_page, page, product, raw_bundle, tier
from game_collections.lists import load_game_list
from game_collections.models import Game, GameList, Reference
from game_collections.sources.common import render_game_list_yaml
from game_collections.sources.digiphile.crawler import (
    CrawledDigiphileOffer,
    crawl_digiphile_offers,
    find_covering_list,
    title_slug,
    write_digiphile_offer,
)
from game_collections.sources.digiphile.parser import COLLECTIONS_URL, page_url


CRAWLED = datetime(2026, 10, 28, tzinfo=UTC)


def crawl(pages: dict[str, str], urls: list[str] | None = None, archive_root: Path | None = None):
    def fetch(url: str) -> str:
        return pages[url]
    # end def fetch

    return crawl_digiphile_offers(fetch, urls, crawled=CRAWLED, archive_root=archive_root)
# end def crawl


def write(offer: CrawledDigiphileOffer, root: Path) -> tuple[Path, ...]:
    return write_digiphile_offer(offer, root / "lists", root / "archives", root)
# end def write


def single_offer(raw: dict[str, object] | None = None) -> CrawledDigiphileOffer:
    bundle = raw or raw_bundle()
    report = crawl({page_url(str(bundle["slug"])): page(bundle)}, [page_url(str(bundle["slug"]))])
    assert report.errors == ()
    return report.offers[0]
# end def single_offer


def test_crawl_lists_every_bundle_then_fetches_each_detail_page() -> None:
    pages = {
        COLLECTIONS_URL: listing_page("one-bundle", "two-bundle"),
        page_url("one-bundle"): page(raw_bundle("one-bundle")),
        page_url("two-bundle"): page(raw_bundle("two-bundle")),
    }

    report = crawl(pages)

    assert report.errors == ()
    assert [offer.archive.machine_name for offer in report.offers] == ["one-bundle", "two-bundle"]
    assert report.offers[0].source == raw_bundle("one-bundle")
# end def test_crawl_lists_every_bundle_then_fetches_each_detail_page


def test_crawl_isolates_a_missing_bundle_and_a_bad_url() -> None:
    pages = {page_url("ok"): page(raw_bundle("ok")), page_url("gone"): "<html>404: This page could not be found.</html>"}

    report = crawl(pages, [page_url("ok"), page_url("gone"), "https://example.com/collections/x"])

    assert [offer.archive.machine_name for offer in report.offers] == ["ok"]
    assert len(report.errors) == 2
    assert any(error.startswith("gone: no bundle found") for error in report.errors)
# end def test_crawl_isolates_a_missing_bundle_and_a_bad_url


def test_crawl_rejects_a_page_describing_another_bundle() -> None:
    report = crawl({page_url("a"): page(raw_bundle("b"))}, [page_url("a")])

    assert report.offers == ()
    assert "describes bundle 'b'" in report.errors[0]
# end def test_crawl_rejects_a_page_describing_another_bundle


def test_crawl_resumes_from_the_archive_without_fetching(tmp_path: Path) -> None:
    offer = single_offer()
    write(offer, tmp_path)

    def failing_fetch(url: str) -> str:
        raise AssertionError(f"unexpected fetch of {url}")
    # end def failing_fetch

    report = crawl_digiphile_offers(
        failing_fetch, [page_url("tiny-bundle")], crawled=CRAWLED, archive_root=tmp_path / "archives"
    )

    assert report.errors == ()
    assert report.offers[0].archive == offer.archive
# end def test_crawl_resumes_from_the_archive_without_fetching


def test_write_stores_add_ons_as_dependent_kinded_tiers(tmp_path: Path) -> None:
    paths = write(single_offer(), tmp_path)

    list_path = tmp_path / "lists/digiphile/bundle/2026-10-20_tiny-bundle.yml"
    assert list_path in paths
    loaded = load_game_list(list_path, tmp_path / "lists")
    assert [(t.rank, t.name, t.kind, t.requires) for t in loaded.data.tiers] == [
        (1, "4.00 USD", "base", []),
        (2, "16.00 USD", "base", []),
        (3, "Relief Fund", "charity", [1]),
        (4, "Map DLC", "upsell", [1]),
    ]
    assert [(g.name, g.ids, g.tiers) for g in loaded.data.games] == [
        ("One", ["steam:1", "digiphile:p-one"], [1, 2]),
        ("Three", ["steam:3", "digiphile:p-three"], [2]),
        ("Two", ["steam:2", "digiphile:p-two"], [2]),
        ("Soundtrack", ["steam:4", "digiphile:p-ost"], [3]),
        ("Map Pack", ["steam:5", "digiphile:p-dlc"], [4]),
    ]
    assert [r.name for r in loaded.data.references] == ["Digiphile bundle", "Crawl metadata", "Crawl source"]
    assert loaded.data.crawlers == ["digiphile"]
    rendered = yaml.safe_load(list_path.read_text(encoding="utf-8"))
    assert "kind" not in rendered["tiers"][0] and "requires" not in rendered["tiers"][0]
# end def test_write_stores_add_ons_as_dependent_kinded_tiers


def test_write_a_single_base_tier_without_add_ons_is_a_plain_list(tmp_path: Path) -> None:
    raw = raw_bundle(
        tiers=[tier("t-5", "Tier $5.00", 5)],
        products=[product("p-a", "A", "t-5", 1), product("p-b", "B", "t-5", 2)],
    )

    write(single_offer(raw), tmp_path)

    loaded = load_game_list(tmp_path / "lists/digiphile/bundle/2026-10-20_tiny-bundle.yml", tmp_path / "lists")
    assert loaded.data.tiers == []
    assert [g.name for g in loaded.data.games] == ["A", "B"]
# end def test_write_a_single_base_tier_without_add_ons_is_a_plain_list


def test_write_ebook_bundles_are_archive_only(tmp_path: Path) -> None:
    raw = raw_bundle(
        type="EBook", tiers=[tier("t-5", "Tier $5.00", 5)], products=[product("c", "Comic", "t-5", kind="EBook")]
    )

    paths = write(single_offer(raw), tmp_path)

    assert {path.name for path in paths} == {"metadata.json", "source.json"}
    assert not (tmp_path / "lists").exists()
# end def test_write_ebook_bundles_are_archive_only


def existing_list(root: Path, file_name: str, crawlers: list[str] | None = None) -> Path:
    game_list = GameList(
        name="Tiny Bundle",
        references=[Reference(name="Elsewhere", url="https://example.com/x")],
        crawlers=crawlers or ["dekudeals"],
        games=[Game(name="One", ids=["steam:1", "dekudeals:one"]), Game(name="Two", ids=["steam:2"])],
    )
    path = root / "lists/digiphile/bundle" / file_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_game_list_yaml(game_list, path, root), encoding="utf-8")
    return path
# end def existing_list


def test_write_backfills_an_aggregator_list_named_after_the_title(tmp_path: Path) -> None:
    raw = raw_bundle("tiny-bundle-games-collection")
    existing = existing_list(tmp_path, "2026-10-20_tiny-bundle.yml")

    paths = write(single_offer(raw), tmp_path)

    assert not any(path.suffix == ".yml" for path in paths)
    assert sorted(path.name for path in (tmp_path / "lists/digiphile/bundle").iterdir()) == [existing.name]
    loaded = load_game_list(existing, tmp_path / "lists")
    assert loaded.data.games[0].ids == ["steam:1", "dekudeals:one", "digiphile:p-one"]
    assert loaded.data.games[1].ids == ["steam:2", "digiphile:p-two"]
    assert loaded.data.crawlers == ["dekudeals", "digiphile"]
    assert [r.name for r in loaded.data.references][:2] == ["Elsewhere", "Digiphile bundle"]
# end def test_write_backfills_an_aggregator_list_named_after_the_title


def test_write_does_not_backfill_a_differently_named_bundle(tmp_path: Path) -> None:
    existing = existing_list(tmp_path, "2025-01-01_tiny-bundle-2.yml")
    before = existing.read_text(encoding="utf-8")

    paths = write(single_offer(), tmp_path)

    assert tmp_path / "lists/digiphile/bundle/2026-10-20_tiny-bundle.yml" in paths
    assert existing.read_text(encoding="utf-8") == before
# end def test_write_does_not_backfill_a_differently_named_bundle


def test_find_covering_list_matches_exact_names_ignoring_the_date_prefix(tmp_path: Path) -> None:
    existing = existing_list(tmp_path, "2026-10-20_social-multiplayer.yml")

    assert find_covering_list(tmp_path / "lists", {"social-multiplayer"}) == existing
    assert find_covering_list(tmp_path / "lists", {"social"}) is None
    assert find_covering_list(tmp_path / "lists-missing", {"social-multiplayer"}) is None
    assert title_slug("Landfall x Aggro Crab Showcase!") == "landfall-x-aggro-crab-showcase"
# end def test_find_covering_list_matches_exact_names_ignoring_the_date_prefix
