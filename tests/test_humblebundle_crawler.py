from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.lists import load_game_list
from game_collections.models import Game
from game_collections.sources.humblebundle.crawler import (
    CrawledHumbleOffer,
    crawl_humble_offers,
    write_humble_offer,
)
from game_collections.sources.humblebundle.models import (
    HumbleArchive,
    HumbleChoicePickOption,
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
    list_path = lists_root / bundle_root / "bundle.yml"
    metadata_path = archive_root / bundle_root / "metadata.json"
    source_path = archive_root / bundle_root / "source.json"
    assert set(paths) == {list_path, metadata_path, source_path}
    loaded = load_game_list(list_path, lists_root)
    assert loaded.id == f"{bundle_root}/bundle"
    assert loaded.data.name == "Sample Bundle — Entire 2 Item Bundle"
    assert loaded.data.tier is None
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


def test_writer_numbers_multiple_tiers(tmp_path: Path) -> None:
    offer = _offer()
    game_two = HumbleItem(
        machine_name="samplegame2",
        title="Sample Game Two",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(ids=["steam:43"]),
    )
    second_tier = offer.archive.tiers[0].model_copy(
        update={
            "identifier": "all2",
            "name": "Entire 3 Item Bundle",
            "item_count": 3,
            "items": [*offer.archive.tiers[0].items, game_two],
        }
    )
    archive = offer.archive.model_copy(update={"tiers": [offer.archive.tiers[0], second_tier]})
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(
        CrawledHumbleOffer(archive=archive, source={}),
        tmp_path / "lists",
        tmp_path / "archives",
        tmp_path,
    )

    bundle_root = "humblebundle/bundle/2026-07-01_sample-bundle"
    lists_root = tmp_path / "lists"
    first_path = lists_root / bundle_root / "tier-1.yml"
    second_path = lists_root / bundle_root / "tier-2.yml"
    assert {path for path in paths if path.suffix == ".yml"} == {first_path, second_path}
    assert load_game_list(first_path, lists_root).data.tier == 1
    assert load_game_list(second_path, lists_root).data.tier == 2
# end def test_writer_numbers_multiple_tiers


def test_writer_choice_with_pick_options_writes_one_list_per_option(tmp_path: Path) -> None:
    offer = _offer("choice")

    archive = offer.archive.model_copy(
        update={"choice_pick_options": [HumbleChoicePickOption(tier_key="basic", quota=1)]}
    )
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(
        CrawledHumbleOffer(archive=archive, source={}), tmp_path / "lists", tmp_path / "archives", tmp_path
    )

    path = tmp_path / "lists/humblebundle/choice/2026-07/bundle.yml"
    assert {p for p in paths if p.suffix == ".yml"} == {path}
    loaded = load_game_list(path, tmp_path / "lists")
    assert loaded.data.pick_quota == 1
    assert loaded.data.tier is None
    assert loaded.data.games == [Game(name="Sample Game", ids=["steam:42"])]
# end def test_writer_choice_with_pick_options_writes_one_list_per_option


def test_writer_choice_with_multiple_pick_options_numbers_tiers(tmp_path: Path) -> None:
    offer = _offer("choice")

    game_two = HumbleItem(
        machine_name="samplegame2",
        title="Sample Game Two",
        item_type="game",
        is_game=True,
        redeem_on=["steam"],
        resolution=HumbleResolution(ids=["steam:43"]),
    )
    choice_tier = offer.archive.tiers[0].model_copy(
        update={"item_count": 3, "items": [*offer.archive.tiers[0].items, game_two]}
    )
    archive = offer.archive.model_copy(
        update={
            "tiers": [choice_tier],
            "choice_pick_options": [
                HumbleChoicePickOption(tier_key="basic", quota=1),
                HumbleChoicePickOption(tier_key="premium", quota=2),
            ],
        }
    )
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas/game-list.schema.json").write_text("{}\n", encoding="utf-8")

    paths = write_humble_offer(
        CrawledHumbleOffer(archive=archive, source={}), tmp_path / "lists", tmp_path / "archives", tmp_path
    )

    lists_root = tmp_path / "lists"
    bundle_root = "humblebundle/choice/2026-07"
    first_path = lists_root / bundle_root / "tier-1.yml"
    second_path = lists_root / bundle_root / "tier-2.yml"
    assert {p for p in paths if p.suffix == ".yml"} == {first_path, second_path}
    first = load_game_list(first_path, lists_root)
    second = load_game_list(second_path, lists_root)
    assert first.data.pick_quota == 1
    assert first.data.tier == 1
    assert second.data.pick_quota == 2
    assert second.data.tier == 2
# end def test_writer_choice_with_multiple_pick_options_numbers_tiers


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


def _bundle_page_payload(machine_name: str = "sample_bundle") -> str:
    game = {
        "machine_name": "samplegame",
        "human_name": "Sample Game",
        "item_content_type": "game",
        "availability_icons": {"delivery_icons": ["hb-steam"]},
    }
    payload = {
        "bundleData": {
            "machine_name": machine_name,
            "page_url": "games/sample-bundle",
            "basic_data": {
                "human_name": "Sample Bundle",
                "short_marketing_blurb": "Play games.",
                "end_time|datetime": "2026-07-22T18:00:00",
            },
            "tier_order": ["all"],
            "tier_display_data": {"all": {"header": "", "tier_item_machine_names": ["samplegame"]}},
            "tier_pricing_data": {"all": {"price|money": None}},
            "tier_item_data": {"samplegame": game},
        }
    }
    return f'<script id="webpack-bundle-page-data">{json.dumps(payload)}</script>'
# end def _bundle_page_payload


def test_crawl_skips_resolution_for_a_cached_offer(tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    offer = _offer()
    cached_archive = offer.archive.model_copy(
        update={
            "dates": HumbleDates(
                end=datetime(2026, 7, 22, 18, tzinfo=UTC),
                crawled=datetime(2026, 7, 12, tzinfo=UTC),
            )
        }
    )
    write_humble_offer(
        CrawledHumbleOffer(archive=cached_archive, source={}),
        tmp_path / "lists",
        archive_root,
        tmp_path,
    )

    def fetch(url: str) -> str:
        return _bundle_page_payload()
    # end def fetch

    def unreachable_fetch(url: str) -> str:
        raise AssertionError(f"storefront search should be skipped for a cached offer: {url}")
    # end def unreachable_fetch

    resolver = StorefrontResolver(unreachable_fetch, lambda _item, _provider, _candidates: None)
    report = crawl_humble_offers(
        fetch,
        resolver,
        HumbleResolutionMap(schema=1, games={}),
        urls=["https://www.humblebundle.com/games/sample-bundle"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        archive_root=archive_root,
    )

    assert report.errors == ()
    assert len(report.offers) == 1
    assert report.offers[0].archive.tiers[0].items[0].resolution.ids == ["steam:42"]
# end def test_crawl_skips_resolution_for_a_cached_offer


def test_crawl_logs_progress_and_invokes_on_offer_per_offer() -> None:
    def fetch(url: str) -> str:
        return _bundle_page_payload()
    # end def fetch

    resolver = StorefrontResolver(fetch, lambda _item, _provider, _candidates: None)
    messages: list[str] = []
    offers: list[CrawledHumbleOffer] = []
    report = crawl_humble_offers(
        fetch,
        resolver,
        HumbleResolutionMap(schema=1, games={}),
        urls=["https://www.humblebundle.com/games/sample-bundle"],
        crawled=datetime(2026, 7, 12, tzinfo=UTC),
        log=messages.append,
        on_offer=offers.append,
    )

    assert any("Offer 1/1" in message for message in messages)
    assert any("Game 1/1" in message for message in messages)
    assert offers == list(report.offers)
# end def test_crawl_logs_progress_and_invokes_on_offer_per_offer
