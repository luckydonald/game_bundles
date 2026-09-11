"""Fetch dekudeals.com bundle offers and write deterministic list and archive output."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from game_collections.models import Game, GameList, Reference, TierDefinition
from game_collections.sources.common import (
    atomic_write,
    backfill_existing_lists,
    dump_json,
    existing_list_match,
    load_cached_archive,
    merge_tiered_games,
    render_game_list_yaml,
)
from game_collections.sources.dekudeals.models import DekuArchive, DekuDates, DekuItem, DekuTier
from game_collections.sources.dekudeals.parser import (
    DEKU_ROOT,
    DekuParseError,
    bundle_slug,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_item_page,
)
from game_collections.sources.dekudeals.provider_config import DekuProviderConfig, resolve_provider_slug
from game_collections.sources.dekudeals.resolver import DekuResolutionMap
from game_collections.sources.storefronts import qualified_ids_from_urls


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731

BUNDLES_INDEX_URL = f"{DEKU_ROOT}bundles"


class DekuCrawlError(RuntimeError):
    """Fetching or writing a DekuDeals offer failed."""

# end class DekuCrawlError


class DekuHttpClient:
    """Small retrying HTTP client for dekudeals.com's public pages."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self._attempts = attempts
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "game-collections/0.1 dekudeals metadata archiver"},
        )
    # end def __init__

    def close(self) -> None:
        """Close pooled network resources."""
        self._client.close()
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one UTF-8 HTML page with bounded transient retries."""
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}", request=response.request, response=response
                    )
                # end if
                response.raise_for_status()
                return response.text
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                if attempt == self._attempts:
                    break
                # end if
                time.sleep(0.25 * (2 ** (attempt - 1)))
            # end try
        # end for
        raise DekuCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class DekuHttpClient


@dataclass(frozen=True, slots=True)
class CrawledDekuOffer:
    """One normalized bundle offer paired with its source payload."""

    archive: DekuArchive
    source: dict[str, Any]

# end class CrawledDekuOffer


@dataclass(frozen=True, slots=True)
class DekuCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledDekuOffer, ...]
    errors: tuple[str, ...]

# end class DekuCrawlReport


def _archive_paths(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "dekudeals/bundle" / slug
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def _resolve_item_ids(
    slug: str,
    title: str,
    fetch: Callable[[str], str],
    mapping: DekuResolutionMap,
    log: LogFn,
    index: int,
    total: int,
) -> list[str]:
    """Resolve one item's storefront ids, reusing `mapping` when already cached.

    Always includes `dekudeals:<slug>` itself, plus every storefront
    `qualified_ids_from_urls` recognizes on the item's own page - a store
    with no verified URL-parsing rule is silently skipped there, never
    guessed. `mapping.games` is updated in place so the caller can persist
    it once the whole crawl finishes.
    """
    cached = mapping.games.get(slug)
    if cached is not None:
        return cached
    # end if
    log(f"  Game {index}/{total}: {title}")
    item_url = f"{DEKU_ROOT}items/{slug}?platform=all"
    store_urls = parse_item_page(fetch(item_url), item_url)
    ids = qualified_ids_from_urls(store_urls)
    ids = [value for value in ids if value != f"dekudeals:{slug}"]
    ids.append(f"dekudeals:{slug}")
    mapping.games[slug] = ids
    return ids
# end def _resolve_item_ids


def crawl_deku_offers(
    fetch: Callable[[str], str],
    provider_config: DekuProviderConfig,
    mapping: DekuResolutionMap,
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledDekuOffer], None] | None = None,
) -> DekuCrawlReport:
    """Crawl explicit bundle pages or discover every currently listed bundle.

    When `archive_root` is given, a bundle already written there (and still
    valid against the current schema) is reused as-is - no bundle-page or
    per-item page fetch at all - instead of being re-crawled. Item storefront
    ids are otherwise resolved immediately, one bundle-detail-page fetch
    at a time, reusing `mapping` for any item slug already resolved by an
    earlier bundle or crawl run. Pass `on_offer` to write each offer to disk
    as soon as it's ready, rather than waiting for the whole crawl to finish.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    explicit = list(urls or [])
    if explicit:
        slugs = [bundle_slug(url) for url in explicit]
    else:
        slugs = []
        try:
            slugs = parse_bundle_index_page(fetch(BUNDLES_INDEX_URL))
        except (OSError, ValueError, DekuCrawlError) as error:
            errors.append(f"{BUNDLES_INDEX_URL}: {error}")
        # end try
    # end if

    offers: list[CrawledDekuOffer] = []
    total = len(slugs)
    for index, slug in enumerate(slugs, start=1):
        log(f"Bundle {index}/{total}: {slug}")
        try:
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, slug)
                cached = load_cached_archive(DekuArchive, metadata_path, source_path)
                if cached is not None:
                    log(f"Bundle {index}/{total}: {slug} (cached)")
                    archive, source = cached
                    offer = CrawledDekuOffer(archive=archive, source=source)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            url = f"{DEKU_ROOT}bundles/{slug}"
            page = fetch(url)
            draft, source = parse_bundle_page(page, url)

            distinct_items = {item.slug: item.title for item in draft.items}
            item_total = len(distinct_items)
            ids_by_slug = {
                item_slug: _resolve_item_ids(item_slug, item_title, fetch, mapping, log, item_index, item_total)
                for item_index, (item_slug, item_title) in enumerate(distinct_items.items(), start=1)
            }

            provider_slug = resolve_provider_slug(draft.store_name, provider_config, log)
            tiers = [
                DekuTier(
                    identifier=tier.identifier,
                    price=tier.price,
                    item_minimum=tier.item_minimum,
                    items=[
                        DekuItem(slug=item.slug, title=item.title, ids=ids_by_slug[item.slug])
                        for item in draft.items
                        if draft.tiering_style == "price_per_item" or int(tier.identifier) in item.tier_ids
                    ],
                )
                for tier in draft.tiers
            ]
            archive = DekuArchive(
                schema=1,
                machine_name=draft.machine_name,
                url=draft.url,
                name=draft.name,
                store_name=draft.store_name,
                provider_slug=provider_slug,
                tiering_style=draft.tiering_style,
                real_url=draft.real_url,
                dates=DekuDates(end=draft.end, crawled=observed),
                tiers=tiers,
            )
            offer = CrawledDekuOffer(archive=archive, source=source)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, DekuParseError, DekuCrawlError) as error:
            errors.append(f"{slug}: {error}")
        # end try
    # end for
    return DekuCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_deku_offers


def _flatten_deku_games(archive: DekuArchive) -> list[Game]:
    """Flatten every tier's items into one game pool for the whole bundle, deduped by id."""
    games: list[Game] = []
    seen_ids: set[str] = set()
    for tier in archive.tiers:
        for item in tier.items:
            if any(value in seen_ids for value in item.ids):
                continue
            # end if
            games.append(Game(name=item.title, ids=item.ids))
            seen_ids.update(item.ids)
        # end for
    # end for
    return games
# end def _flatten_deku_games


def write_deku_offer(
    offer: CrawledDekuOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
    log: LogFn = _NO_LOG,
) -> tuple[Path, ...]:
    """Atomically write the archive record, plus one list unless already covered elsewhere."""
    archive = offer.archive
    metadata_path, source_path = _archive_paths(archive_root, archive.machine_name)
    atomic_write(metadata_path, dump_json(archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(offer.source))
    written: list[Path] = [metadata_path, source_path]

    existing = existing_list_match(lists_root, archive.provider_slug, archive.machine_name)
    if existing is not None:
        backfill_existing_lists(
            _flatten_deku_games(archive),
            existing,
            "dekudeals",
            archive.machine_name,
            Reference(name="DekuDeals bundle", url=archive.url),
            metadata_path,
            source_path,
            repository_root,
            log,
        )
        return tuple(written)
    # end if

    list_directory = lists_root / archive.provider_slug / "bundle"
    path = list_directory / f"{archive.machine_name}.yml"

    pool_games = _flatten_deku_games(archive)
    if archive.tiering_style == "price_per_item":
        tier_definitions: list[TierDefinition] = []
        pick_quota: int | None = None
        games = pool_games
        if len(archive.tiers) == 1 and archive.tiers[0].item_minimum is not None:
            pick_quota = archive.tiers[0].item_minimum
        elif len(archive.tiers) > 1:
            tier_definitions, games = merge_tiered_games(
                [
                    (rank, f"pick {tier.item_minimum}", pool_games, tier.item_minimum)
                    for rank, tier in enumerate(archive.tiers, start=1)
                ]
            )
        # end if
    else:
        tier_definitions, games = merge_tiered_games(
            [
                (rank, tier.price.raw if tier.price else tier.identifier, [
                    Game(name=item.title, ids=item.ids) for item in tier.items
                ], None)
                for rank, tier in enumerate(archive.tiers, start=1)
            ]
        )
    # end if

    game_list = GameList(
        schema=1,
        name=archive.name,
        tiers=tier_definitions,
        pick_quota=pick_quota if archive.tiering_style == "price_per_item" else None,
        references=[
            Reference(name="DekuDeals bundle", url=archive.url),
            *([Reference(name=f"{archive.store_name} bundle", url=archive.real_url)] if archive.real_url else []),
            Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
            Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
        ],
        crawlers=["dekudeals"],
        games=games,
    )
    atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
    written.append(path)
    return tuple(written)
# end def write_deku_offer
