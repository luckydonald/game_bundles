from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.sources.dekudeals.crawler import crawl_deku_offers, write_deku_offer
from game_collections.sources.dekudeals.provider_config import DekuProviderConfig
from game_collections.sources.dekudeals.resolver import DekuResolutionMap


CRAWLED = datetime(2026, 7, 12, tzinfo=UTC)


def _inertia_page(props: dict[str, object]) -> str:
    payload = {"component": "BundleShow", "props": props, "url": "/x", "version": "1", "onceProps": {}}
    encoded = html.escape(json.dumps(payload), quote=True)
    return f'<html><body><div id="inertia-app" data-page="{encoded}"><div>rendered</div></div></body></html>'
# end def _inertia_page


def _item_page(steam_app_id: int) -> str:
    return (
        "<html><body><tr><td>"
        f"<a data-out-analytics-id='steam:{steam_app_id}' "
        f"href='https://store.steampowered.com/app/{steam_app_id}/Foo'>Steam</a>"
        "</td></tr></body></html>"
    )
# end def _item_page


def _bundle_props(slug: str = "crawling-through-the-dungeons") -> dict[str, object]:
    return {
        "bundle": {
            "slug": slug,
            "name": "Crawling Through the Dungeons",
            "state": "published",
            "tiering_style": "price_per_tier",
            "store_name": "Humble",
            "ends_at": None,
            "url": "https://humblebundleinc.sjv.io/c/x?u=https%3A%2F%2Fwww.humblebundle.com%2Fgames%2Fcrawling",
        },
        "tiers": [{"id": 1, "price": 1023, "price_formatted": "€10,23"}],
        "items": [
            {"name": "Crawl", "slug": "crawl", "platform": "steam", "tiers": [1]},
            {"name": "Dungeon Drafters", "slug": "dungeon-drafters", "platform": "steam", "tiers": [1]},
        ],
    }
# end def _bundle_props


BUNDLE_URL = "https://www.dekudeals.com/bundles/crawling-through-the-dungeons"


def test_crawl_resolves_item_ids_and_dedupes_platform_marker() -> None:
    pages = {
        BUNDLE_URL: _inertia_page(_bundle_props()),
        "https://www.dekudeals.com/items/crawl?platform=all": _item_page(3157),
        "https://www.dekudeals.com/items/dungeon-drafters?platform=all": _item_page(1824580),
    }
    mapping = DekuResolutionMap(schema=1, games={})
    provider_config = DekuProviderConfig(schema=1, providers={"Humble": "humblebundle"})

    report = crawl_deku_offers(
        lambda url: pages[url], provider_config, mapping, urls=[BUNDLE_URL], crawled=CRAWLED
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    archive = report.offers[0].archive
    assert archive.provider_slug == "humblebundle"
    ids_by_slug = {item.slug: item.ids for tier in archive.tiers for item in tier.items}
    assert ids_by_slug["crawl"] == ["steam:3157", "dekudeals:crawl"]
    assert ids_by_slug["dungeon-drafters"] == ["steam:1824580", "dekudeals:dungeon-drafters"]
    assert mapping.games["crawl"] == ["steam:3157", "dekudeals:crawl"]
# end def test_crawl_resolves_item_ids_and_dedupes_platform_marker


def test_crawl_reuses_resolution_map_without_refetching_item_page() -> None:
    pages = {BUNDLE_URL: _inertia_page(_bundle_props())}

    def fetch(url: str) -> str:
        if url in pages:
            return pages[url]
        raise AssertionError(f"unexpected fetch for already-cached item: {url}")
    # end def fetch

    mapping = DekuResolutionMap(
        schema=1,
        games={
            "crawl": ["steam:3157", "dekudeals:crawl"],
            "dungeon-drafters": ["steam:1824580", "dekudeals:dungeon-drafters"],
        },
    )
    provider_config = DekuProviderConfig(schema=1, providers={"Humble": "humblebundle"})

    report = crawl_deku_offers(fetch, provider_config, mapping, urls=[BUNDLE_URL], crawled=CRAWLED)

    assert report.errors == ()
    assert len(report.offers) == 1
# end def test_crawl_reuses_resolution_map_without_refetching_item_page


def test_write_deku_offer_creates_list_and_archive(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    pages = {
        BUNDLE_URL: _inertia_page(_bundle_props()),
        "https://www.dekudeals.com/items/crawl?platform=all": _item_page(3157),
        "https://www.dekudeals.com/items/dungeon-drafters?platform=all": _item_page(1824580),
    }
    mapping = DekuResolutionMap(schema=1, games={})
    provider_config = DekuProviderConfig(schema=1, providers={"Humble": "humblebundle"})
    report = crawl_deku_offers(
        lambda url: pages[url], provider_config, mapping, urls=[BUNDLE_URL], crawled=CRAWLED
    )

    paths = write_deku_offer(report.offers[0], lists_root, archive_root, tmp_path)

    list_path = lists_root / "humblebundle/bundle/crawling-through-the-dungeons.yml"
    assert list_path in paths
    loaded = load_game_list(list_path, lists_root)
    assert loaded.data.name == "Crawling Through the Dungeons"
    assert {game.name for game in loaded.data.games} == {"Crawl", "Dungeon Drafters"}
    assert "dekudeals" in loaded.data.crawlers
# end def test_write_deku_offer_creates_list_and_archive


def test_write_deku_offer_backfills_existing_covered_list(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    existing = lists_root / "humblebundle/bundle/crawling-through-the-dungeons.yml"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "schema: 1\nname: existing\ngames:\n  - name: Crawl\n    ids: [humble:crawl]\n",
        encoding="utf-8",
    )

    pages = {
        BUNDLE_URL: _inertia_page(_bundle_props()),
        "https://www.dekudeals.com/items/crawl?platform=all": _item_page(3157),
        "https://www.dekudeals.com/items/dungeon-drafters?platform=all": _item_page(1824580),
    }
    mapping = DekuResolutionMap(schema=1, games={})
    provider_config = DekuProviderConfig(schema=1, providers={"Humble": "humblebundle"})
    report = crawl_deku_offers(
        lambda url: pages[url], provider_config, mapping, urls=[BUNDLE_URL], crawled=CRAWLED
    )

    messages: list[str] = []
    paths = write_deku_offer(report.offers[0], lists_root, archive_root, tmp_path, log=messages.append)

    assert existing not in paths
    loaded = load_game_list(existing, lists_root)
    assert loaded.data.name == "existing"
    crawl_game = next(game for game in loaded.data.games if game.name == "Crawl")
    assert crawl_game.ids == ["humble:crawl", "steam:3157", "dekudeals:crawl"]
    assert any("Backfilled" in message for message in messages)
# end def test_write_deku_offer_backfills_existing_covered_list


def test_write_deku_offer_skips_second_backfill_pass_once_marked(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    existing = lists_root / "humblebundle/bundle/crawling-through-the-dungeons.yml"
    existing.parent.mkdir(parents=True)
    existing.write_text(
        "schema: 1\nname: existing\ngames:\n  - name: Crawl\n    ids: [humble:crawl]\n",
        encoding="utf-8",
    )

    pages = {
        BUNDLE_URL: _inertia_page(_bundle_props()),
        "https://www.dekudeals.com/items/crawl?platform=all": _item_page(3157),
        "https://www.dekudeals.com/items/dungeon-drafters?platform=all": _item_page(1824580),
    }
    mapping = DekuResolutionMap(schema=1, games={})
    provider_config = DekuProviderConfig(schema=1, providers={"Humble": "humblebundle"})
    report = crawl_deku_offers(
        lambda url: pages[url], provider_config, mapping, urls=[BUNDLE_URL], crawled=CRAWLED
    )

    write_deku_offer(report.offers[0], lists_root, archive_root, tmp_path)
    before = existing.read_text(encoding="utf-8")

    messages: list[str] = []
    write_deku_offer(report.offers[0], lists_root, archive_root, tmp_path, log=messages.append)

    assert existing.read_text(encoding="utf-8") == before
    assert any("Skipped" in message for message in messages)
# end def test_write_deku_offer_skips_second_backfill_pass_once_marked
