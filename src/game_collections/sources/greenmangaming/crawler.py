"""Fetch Green Man Gaming bundles and write deterministic list and archive output."""

from __future__ import annotations

import time
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from game_collections.models import Game, GameGroup, GameList, Reference
from game_collections.sources.common import (
    atomic_write,
    dump_json,
    load_cached_archive,
    render_game_list_yaml,
)
from game_collections.sources.greenmangaming.models import GmgArchive, GmgItem, GmgTier
from game_collections.sources.greenmangaming.parser import (
    GMG_ROOT,
    bundle_url,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_product_fragment,
)
from game_collections.sources.greenmangaming.resolver import (
    GmgResolutionMap,
    StorefrontResolver,
    render_resolution_map,
)


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


BUNDLES_INDEX_URL = f"{GMG_ROOT}bundles/"


class GmgCrawlError(RuntimeError):
    """Fetching or writing a Green Man Gaming offer failed."""

# end class GmgCrawlError


class GmgHttpClient:
    """Small retrying HTTP client for public Green Man Gaming pages."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self._attempts = attempts
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={
                "User-Agent": "game-collections/0.1 Green Man Gaming metadata archiver",
                "HX-Request": "true",
            },
        )
    # end def __init__

    def close(self) -> None:
        """Close pooled network resources."""
        self._client.close()
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one UTF-8 HTML page/fragment with bounded transient retries."""
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                response = self._client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                # end if
                response.raise_for_status()
                return response.text
            except httpx.HTTPError as error:
                last_error = error
                if attempt == self._attempts:
                    break
                # end if
                time.sleep(0.25 * (2 ** (attempt - 1)))
            # end try
        # end for
        raise GmgCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class GmgHttpClient


@dataclass(frozen=True, slots=True)
class CrawledGmgOffer:
    """One resolved normalized offer paired with its source payload."""

    archive: GmgArchive
    source: dict[str, Any]

# end class CrawledGmgOffer


@dataclass(frozen=True, slots=True)
class GmgCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledGmgOffer, ...]
    errors: tuple[str, ...]

# end class GmgCrawlReport


def _validated_explicit_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "greenmangamingbundles.com",
        "www.greenmangamingbundles.com",
    }:
        raise ValueError(f"Green Man Gaming bundle URLs must use https://www.greenmangamingbundles.com: {value}")
    # end if
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0] != "bundles":
        raise ValueError(f"expected a Green Man Gaming bundle detail URL: {value}")
    # end if
    return path_parts[1]
# end def _validated_explicit_url


def _archive_paths(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "greenmangaming/bundle" / slug
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def _enrich_item(item: GmgItem, slug: str, fetch: Callable[[str], str], log: LogFn, index: int, total: int) -> GmgItem:
    log(f"  Game {index}/{total}: {item.title}")
    fragment_url = f"{bundle_url(slug)}product/{item.product_id}/"
    fields = parse_product_fragment(fetch(fragment_url), item.product_id)
    return item.model_validate(item.model_dump() | fields)
# end def _enrich_item


def crawl_gmg_offers(
    fetch: Callable[[str], str],
    resolver: StorefrontResolver,
    mapping: GmgResolutionMap,
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledGmgOffer], None] | None = None,
) -> GmgCrawlReport:
    """Crawl explicit bundle pages or discover every currently listed video-games bundle.

    When `archive_root` is given and a valid cached archive already exists
    for a slug, both the per-item product-fragment fetches and
    `resolver.resolve_archive` are skipped entirely in favor of the cached,
    already-enriched-and-resolved archive - mirroring DailyIndieGame's
    resume behavior. Pass `on_offer` to write each offer to disk as soon as
    it's ready, rather than waiting for the whole crawl to finish.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    explicit = list(urls or [])
    if explicit:
        slugs = [_validated_explicit_url(url) for url in explicit]
    else:
        slugs = []
        try:
            slugs = parse_bundle_index_page(fetch(BUNDLES_INDEX_URL))
        except (OSError, ValueError, GmgCrawlError) as error:
            errors.append(f"{BUNDLES_INDEX_URL}: {error}")
        # end try
    # end if
    offers: list[CrawledGmgOffer] = []
    total = len(slugs)
    for index, slug in enumerate(slugs, start=1):
        log(f"Bundle {index}/{total}: {slug}")
        try:
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, slug)
                cached = load_cached_archive(GmgArchive, metadata_path, source_path)
                if cached is not None:
                    log(f"Bundle {index}/{total}: {slug} (cached)")
                    archive, source = cached
                    offer = CrawledGmgOffer(archive=archive, source=source)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            page = fetch(bundle_url(slug))
            archive, source = parse_bundle_page(page, slug, observed)
            distinct_items: dict[str, GmgItem] = {}
            for tier in archive.tiers:
                for item in tier.items:
                    distinct_items.setdefault(item.product_id, item)
                # end for
            # end for
            item_total = len(distinct_items)
            enriched = {
                product_id: _enrich_item(item, slug, fetch, log, item_index, item_total)
                for item_index, (product_id, item) in enumerate(distinct_items.items(), start=1)
            }
            tiers = [
                tier.model_copy(update={"items": [enriched[item.product_id] for item in tier.items]})
                for tier in archive.tiers
            ]
            archive = archive.model_copy(update={"tiers": tiers})
            archive = resolver.resolve_archive(archive, mapping, log=log)
            offer = CrawledGmgOffer(archive=archive, source=source)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, GmgCrawlError) as error:
            errors.append(f"{slug}: {error}")
        # end try
    # end for
    return GmgCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_gmg_offers


def _item_all_ids(item: GmgItem) -> list[str]:
    """Every qualified ID an item resolved to, whether or not it split into several games."""
    if item.resolution.splits:
        return [identifier for split in item.resolution.splits for identifier in split.ids]
    # end if
    return list(item.resolution.ids)
# end def _item_all_ids


def _games_for_item(item: GmgItem) -> list[Game]:
    """Build one Game per item, or several when "Multiple…" split it during resolution."""
    if item.resolution.splits:
        group = GameGroup(id=item.product_id, name=item.title)
        return [Game(name=split.name, ids=split.ids, group=group) for split in item.resolution.splits]
    # end if
    return [Game(name=item.title, ids=item.resolution.ids)]
# end def _games_for_item


def write_gmg_offer(
    offer: CrawledGmgOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
) -> tuple[Path, ...]:
    """Atomically write the normalized/source archive and one list per tier."""
    archive = offer.archive
    list_directory = lists_root / "greenmangaming/bundle" / archive.slug
    metadata_path, source_path = _archive_paths(archive_root, archive.slug)
    atomic_write(metadata_path, dump_json(archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(offer.source))
    written: list[Path] = [metadata_path, source_path]

    tiers_with_games: list[tuple[GmgTier, list[Game]]] = []
    for tier in archive.tiers:
        games: list[Game] = []
        seen_ids: set[str] = set()
        for item in tier.items:
            item_ids = _item_all_ids(item)
            if any(value in seen_ids for value in item_ids):
                continue
            # end if
            games.extend(_games_for_item(item))
            seen_ids.update(item_ids)
        # end for
        if games:
            tiers_with_games.append((tier, games))
        # end if
    # end for
    for rank, (tier, games) in enumerate(tiers_with_games, start=1):
        if len(tiers_with_games) == 1:
            path = list_directory / "bundle.yml"
            list_tier = None
        else:
            path = list_directory / f"tier-{rank}.yml"
            list_tier = rank
        # end if
        game_list = GameList(
            schema=1,
            name=f"{archive.name} — {tier.name}",
            tier=list_tier,
            references=[
                Reference(name="Green Man Gaming bundle", url=archive.url),
                Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
                Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
            ],
            games=games,
        )
        atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
        written.append(path)
    # end for
    return tuple(written)
# end def write_gmg_offer


def write_resolution_map(path: Path, mapping: GmgResolutionMap) -> None:
    """Atomically persist reviewed storefront decisions."""
    atomic_write(path, render_resolution_map(mapping))
# end def write_resolution_map
