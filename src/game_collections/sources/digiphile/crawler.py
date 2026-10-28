"""Fetch digiphile.co bundle offers and write deterministic list and archive output."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from game_collections.models import Game, GameList, Reference, TierKind
from game_collections.sources.common import (
    atomic_write,
    backfill_existing_lists,
    dump_versioned_json,
    load_cached_archive,
    merge_tiered_games,
    render_game_list_yaml,
)
from game_collections.sources.digiphile.models import (
    CURRENT_VERSION,
    DigiphileArchive,
    DigiphileItem,
    DigiphileTier,
)
from game_collections.sources.digiphile.parser import (
    COLLECTIONS_URL,
    DigiphileParseError,
    bundle_slug,
    extract_bundle,
    extract_bundle_slugs,
    page_url,
    parse_bundle,
)


LogFn = Callable[[str], None]
NO_LOG: LogFn = lambda _message: None  # noqa: E731

PROVIDER_SLUG = "digiphile"
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_")
NON_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class DigiphileCrawlError(RuntimeError):
    """Fetching or writing a Digiphile offer failed."""

# end class DigiphileCrawlError


class DigiphileHttpClient:
    """Small retrying HTTP client for digiphile.co."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self.attempts = attempts
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; game-collections/0.1 digiphile metadata archiver)"},
        )
    # end def __init__

    def close(self) -> None:
        """Close pooled network resources."""
        self.client.close()
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one UTF-8 page with bounded transient retries."""
        last_error: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}", request=response.request, response=response
                    )
                # end if
                response.raise_for_status()
                return response.text
            except (httpx.TransportError, httpx.HTTPStatusError) as error:
                last_error = error
                if attempt == self.attempts:
                    break
                # end if
                time.sleep(0.25 * (2 ** (attempt - 1)))
            # end try
        # end for
        raise DigiphileCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class DigiphileHttpClient


@dataclass(frozen=True, slots=True)
class CrawledDigiphileOffer:
    """One normalized bundle offer paired with its source payload."""

    archive: DigiphileArchive
    source: dict[str, Any]

# end class CrawledDigiphileOffer


@dataclass(frozen=True, slots=True)
class DigiphileCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledDigiphileOffer, ...]
    errors: tuple[str, ...]

# end class DigiphileCrawlReport


def archive_paths(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "digiphile/bundle" / slug
    return directory / "metadata.json", directory / "source.json"
# end def archive_paths


def crawl_digiphile_offers(
    fetch: Callable[[str], str],
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = NO_LOG,
    on_offer: Callable[[CrawledDigiphileOffer], None] | None = None,
) -> DigiphileCrawlReport:
    """Crawl explicit bundles or every bundle listed on `/collections` (expired ones included).

    The list page only names the bundles, every bundle then needs its own detail page. When `archive_root` is
    given, a bundle already written there (and still valid against the current schema) is reused as-is.
    Pass `on_offer` to write each offer to disk as soon as it's ready.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    explicit = list(urls or [])
    if explicit:
        slugs: list[str] = []
        for url in explicit:
            try:
                slugs.append(bundle_slug(url))
            except ValueError as error:
                errors.append(str(error))
            # end try
        # end for
    else:
        try:
            slugs = extract_bundle_slugs(fetch(COLLECTIONS_URL))
        except (OSError, ValueError, DigiphileCrawlError) as error:
            return DigiphileCrawlReport(offers=(), errors=(f"{COLLECTIONS_URL}: {error}",))
        # end try
    # end if

    offers: list[CrawledDigiphileOffer] = []
    total = len(slugs)
    for index, slug in enumerate(slugs, start=1):
        log(f"Bundle {index}/{total}: {slug}")
        try:
            if archive_root is not None:
                metadata_path, source_path = archive_paths(archive_root, slug)
                cached = load_cached_archive(
                    DigiphileArchive, metadata_path, source_path, current_version=CURRENT_VERSION
                )
                if cached is not None:
                    log(f"Bundle {index}/{total}: {slug} (cached)")
                    archive, source = cached
                    offer = CrawledDigiphileOffer(archive=archive, source=source)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            raw = extract_bundle(fetch(page_url(slug)))
            if raw.get("slug") != slug:
                raise DigiphileCrawlError(f"page of {slug!r} describes bundle {raw.get('slug')!r}")
            # end if
            offer = CrawledDigiphileOffer(archive=parse_bundle(raw, observed), source=raw)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, DigiphileParseError, DigiphileCrawlError) as error:
            errors.append(f"{slug}: {error}")
        # end try
    # end for
    return DigiphileCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_digiphile_offers


def listed_games(items: Iterable[DigiphileItem]) -> list[Game]:
    """Steam games (ebooks are archive-only), deduped by id."""
    games: list[Game] = []
    seen_ids: set[str] = set()
    for item in items:
        if not any(value.startswith("steam:") for value in item.ids):
            continue
        # end if
        if any(value in seen_ids for value in item.ids):
            continue
        # end if
        games.append(Game(name=item.title, ids=item.ids))
        seen_ids.update(item.ids)
    # end for
    return games
# end def listed_games


def title_slug(name: str) -> str:
    """`Social Multiplayer` as `social-multiplayer`, the name the aggregators give their lists."""
    return NON_SLUG_PATTERN.sub("-", name.casefold()).strip("-")
# end def title_slug


def find_covering_list(lists_root: Path, names: Iterable[str]) -> Path | None:
    """An already written Digiphile list named exactly after one of `names` (a leading date ignored).

    The shared fuzzy/substring `existing_list_match` is deliberately not used: it would also hit older editions
    and asks for confirmation on a terminal, while the aggregators name their list after either the slug or the title.
    """
    provider_root = lists_root / PROVIDER_SLUG
    if not provider_root.is_dir():
        return None
    # end if
    wanted = set(names)
    for path in sorted(provider_root.rglob("*.yml")):
        if DATE_PREFIX_PATTERN.sub("", path.stem) in wanted:
            return path
        # end if
    # end for
    return None
# end def find_covering_list


def tier_label(tier: DigiphileTier) -> str:
    """A base tier is named after its price, an add-on keeps Digiphile's descriptive name."""
    if tier.tier_type == "base":
        return f"{tier.price:.2f} USD"
    # end if
    return tier.name
# end def tier_label


def write_digiphile_offer(
    offer: CrawledDigiphileOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
    log: LogFn = NO_LOG,
) -> tuple[Path, ...]:
    """Atomically write the archive record, plus one list unless already covered or game-less."""
    archive = offer.archive
    metadata_path, source_path = archive_paths(archive_root, archive.machine_name)
    atomic_write(metadata_path, dump_versioned_json(CURRENT_VERSION, archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_versioned_json(CURRENT_VERSION, offer.source))
    written: list[Path] = [metadata_path, source_path]

    pool = listed_games(item for tier in archive.tiers for item in tier.items)
    if not pool:
        log(f"  No Steam products in {archive.machine_name}: archive only")
        return tuple(written)
    # end if
    existing = find_covering_list(lists_root, {archive.machine_name, title_slug(archive.name)})
    if existing is not None:
        backfill_existing_lists(
            pool,
            existing,
            PROVIDER_SLUG,
            archive.machine_name,
            Reference(name="Digiphile bundle", url=archive.url),
            metadata_path,
            source_path,
            repository_root,
            log,
        )
        return tuple(written)
    # end if

    effective_start = (
        datetime.fromtimestamp(archive.dates.start.timestamp, tz=UTC) if archive.dates.start else archive.dates.crawled
    )
    path = lists_root / PROVIDER_SLUG / "bundle" / f"{effective_start.date().isoformat()}_{archive.machine_name}.yml"

    # Tiers without any Steam game (ebook-only add-ons) have no list entry. The base tiers come first (see
    # `parser.parse_bundle`), so the lowest remaining base tier is the one every add-on needs.
    tier_games = [
        (rank, tier_label(tier), listed_games(tier.items), None) for rank, tier in enumerate(archive.tiers, start=1)
    ]
    tier_games = [entry for entry in tier_games if entry[2]]
    first_base_rank = next(
        (rank for rank, _name, _games, _quota in tier_games if archive.tiers[rank - 1].tier_type == "base"), None
    )
    add_ons: dict[int, tuple[TierKind, list[int]]] = {}
    for rank, _name, _games, _quota in tier_games:
        tier_type = archive.tiers[rank - 1].tier_type
        if tier_type != "base":
            add_ons[rank] = (tier_type, [] if first_base_rank is None else [first_base_rank])
        # end if
    # end for
    if len(tier_games) == 1:
        # One purchasable level and no add-on: a plain list, not a tier choice.
        tier_definitions, games = [], pool
    else:
        tier_definitions, games = merge_tiered_games(tier_games, add_ons)
    # end if

    game_list = GameList(
        name=archive.name,
        tiers=tier_definitions,
        references=[
            Reference(name="Digiphile bundle", url=archive.url),
            Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
            Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
        ],
        crawlers=[PROVIDER_SLUG],
        games=games,
    )
    atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
    written.append(path)
    return tuple(written)
# end def write_digiphile_offer
