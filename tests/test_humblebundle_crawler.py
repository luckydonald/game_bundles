from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.sources.humblebundle.crawler import (
    CrawledHumbleOffer,
    crawl_humble_offers,
    write_humble_offer,
)
from game_collections.sources.humblebundle.models import (
    HumbleArchive,
    HumbleDates,
    HumbleItem,
    HumbleResolution,
    HumbleTier,
)
from game_collections.sources.humblebundle.resolver import HumbleResolutionMap, StorefrontResolver


def _offer(kind: str = "bundle") -> CrawledHumbleOffer:
    game = HumbleItem(
        machine_name="samplegame",
        title="Sample Game",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(ids=["steam:42"]),
    )
    coupon = HumbleItem(
        machine_name="coupon",
        title="Sample Coupon",
        item_type="game",
        is_game=False,
        tags=["Coupon"],
    )
    if kind == "choice":
        archive = HumbleArchive(
            schema=1,
            kind="choice",
            machine_name="july_2026_choice",
            url="https://www.humblebundle.com/membership",
            name="July 2026 Humble Choice",
            headline="July 2026 Humble Choice",
            description="Choice.",
            dates=HumbleDates(crawled=datetime(2026, 7, 12, tzinfo=UTC)),
            tiers=[
                HumbleTier(
                    identifier="choice",
                    name="July 2026 Humble Choice",
                    item_count=2,
                    items=[game, coupon],
                )
            ],
        )
    else:
        archive = HumbleArchive(
            schema=1,
            kind="bundle",
            machine_name="sample_bundle",
            url="https://www.humblebundle.com/games/sample-bundle",
            name="Sample Bundle",
            headline="Play games.",
            description="Bundle.",
            dates=HumbleDates(
                start=datetime(2026, 7, 1, 18, tzinfo=UTC),
                end=datetime(2026, 7, 22, 18, tzinfo=UTC),
                crawled=datetime(2026, 7, 12, tzinfo=UTC),
            ),
            tiers=[
                HumbleTier(
                    identifier="all",
                    name="Entire 2 Item Bundle",
                    item_count=2,
                    items=[game, coupon],
                )
            ],
        )
    # end if
    return CrawledHumbleOffer(archive=archive, source={"zeta": 2, "alpha": 1})
# end def _offer


def test_writer_creates_archive_and_games_only_bundle_list(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    archive_root = tmp_path / "archives"
    schema = tmp_path / "schemas/game-list.schema.json"
    schema.parent.mkdir()
    schema.write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(_offer(), lists_root, archive_root, tmp_path)

    bundle_root = "humblebundle/bundle/2026-07-01_sample-bundle"
    list_path = lists_root / bundle_root / "entire-2-item-bundle.yml"
    metadata_path = archive_root / bundle_root / "metadata.json"
    source_path = archive_root / bundle_root / "source.json"
    assert set(paths) == {list_path, metadata_path, source_path}
    loaded = load_game_list(list_path, lists_root)
    assert loaded.id == f"{bundle_root}/entire-2-item-bundle"
    assert loaded.data.name == "Sample Bundle — Entire 2 Item Bundle"
    assert [reference.name for reference in loaded.data.references] == [
        "Humble Bundle offer",
        "Crawl metadata",
        "Crawl source",
    ]
    assert str(loaded.data.references[0].url) == "https://www.humblebundle.com/games/sample-bundle"
    assert loaded.data.references[1].path == "../../../../archives/" + bundle_root + "/metadata.json"
    assert loaded.data.references[2].path == "../../../../archives/" + bundle_root + "/source.json"
    assert [(game.name, game.ids) for game in loaded.data.games] == [("Sample Game", ["steam:42"])]
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert [item["title"] for item in metadata["tiers"][0]["items"]] == [
        "Sample Game",
        "Sample Coupon",
    ]
    assert source_path.read_text(encoding="utf-8").startswith('{\n  "alpha": 1,')
# end def test_writer_creates_archive_and_games_only_bundle_list


def test_writer_deduplicates_products_with_the_same_storefront_identity(tmp_path: Path) -> None:
    offer = _offer()
    duplicate = offer.archive.tiers[0].items[0].model_copy(
        update={"machine_name": "samplegame-deluxe", "title": "Sample Game Deluxe"}
    )
    tier = offer.archive.tiers[0].model_copy(
        update={
            "item_count": 3,
            "items": [*offer.archive.tiers[0].items, duplicate],
        }
    )
    archive = offer.archive.model_copy(update={"tiers": [tier]})
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(
        CrawledHumbleOffer(archive=archive, source={}),
        tmp_path / "lists",
        tmp_path / "archives",
        tmp_path,
    )

    list_path = next(path for path in paths if path.suffix == ".yml")
    loaded = load_game_list(list_path, tmp_path / "lists")
    assert [(game.name, game.ids) for game in loaded.data.games] == [("Sample Game", ["steam:42"])]
# end def test_writer_deduplicates_products_with_the_same_storefront_identity


def test_writer_uses_choice_month_path_and_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")
    first = write_humble_offer(_offer("choice"), tmp_path / "lists", tmp_path / "archives", tmp_path)
    first_contents = {path: path.read_bytes() for path in first}

    second = write_humble_offer(_offer("choice"), tmp_path / "lists", tmp_path / "archives", tmp_path)

    assert first == second
    assert {path: path.read_bytes() for path in second} == first_contents
    assert (tmp_path / "lists/humblebundle/choice/2026-07.yml").exists()
# end def test_writer_uses_choice_month_path_and_is_idempotent


def test_writer_falls_back_to_bundle_end_date(tmp_path: Path) -> None:
    offer = _offer()
    archive = offer.archive.model_copy(
        update={
            "dates": HumbleDates(
                end=datetime(2026, 7, 22, 18, tzinfo=UTC),
                crawled=datetime(2026, 7, 12, tzinfo=UTC),
            )
        }
    )
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(
        CrawledHumbleOffer(archive=archive, source={}),
        tmp_path / "lists",
        tmp_path / "archives",
        tmp_path,
    )

    assert any("2026-07-22_sample-bundle" in str(path) for path in paths)
# end def test_writer_falls_back_to_bundle_end_date


def test_crawl_explicit_choice_is_resolved_without_listing() -> None:
    product = {
        "@type": "Product",
        "name": "July 2026 Humble Choice",
        "sku": "july_2026_choice",
        "url": "https://www.humblebundle.com/membership",
        "description": "Choice.",
        "offers": {
            "validFrom": "2026-07-07T17:00:00Z",
            "validThrough": "2026-08-04T17:00:00Z",
        },
    }
    marketing = {
        "activeContentMachineName": "july_2026_choice",
        "baseSubscriptionPrice|money": {"currency": "EUR", "amount": 12.99},
    }
    content = {
        "samplegame": {
            "title": "Sample Game",
            "delivery_methods": ["steam"],
            "platforms": ["windows"],
            "msrp": {"currency": "EUR", "amount": 10.0},
            "youtube_links": [],
            "genres": [],
            "user_rating": {},
            "recommendation_copy_dict": {"copy": "Game."},
        }
    }
    page = (
        f'<script type="application/ld+json">{json.dumps(product)}</script>'
        f'<script id="webpack-choice-marketing-data">{json.dumps(marketing)}</script>'
        f"<div data-content-choice-data='{json.dumps(content)}' data-machine-name='samplegame'></div>"
    )
    store = '<a href="https://store.steampowered.com/app/42/sample/">Sample Game</a>'

    def fetch(url: str) -> str:
        return page if "humblebundle.com" in url else store
    # end def fetch

    resolver = StorefrontResolver(fetch, lambda _item, _provider, _candidates: None)
    report = crawl_humble_offers(
        fetch,
        resolver,
        HumbleResolutionMap(schema=1, games={}),
        urls=["https://www.humblebundle.com/membership"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
    )

    assert report.errors == ()
    assert report.offers[0].archive.tiers[0].items[0].resolution.ids == ["steam:42"]
# end def test_crawl_explicit_choice_is_resolved_without_listing
