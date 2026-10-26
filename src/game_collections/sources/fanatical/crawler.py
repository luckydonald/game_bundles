"""Fetch fanatical.com bundle offers and write deterministic list and archive output."""

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

from game_collections.models import Game, GameList, Reference, TierDefinition
from game_collections.sources.common import (
    atomic_write,
    backfill_existing_lists,
    dump_versioned_json,
    existing_list_match,
    load_cached_archive,
    merge_tiered_games,
    render_game_list_yaml,
)
from game_collections.sources.fanatical.models import (
    CURRENT_VERSION,
    FanaticalArchive,
    FanaticalDates,
    FanaticalItem,
    FanaticalTier,
)
from game_collections.sources.fanatical.parser import (
    BUNDLES_API_URL,
    FanaticalDraft,
    FanaticalParseError,
    FanaticalProduct,
    bundle_slug,
    page_url,
    parse_bundle,
    parse_bundles_json,
)
from game_collections.sources.fanatical.resolver import (
    FanaticalResolutionMap,
    SteamSearch,
    resolve_product_ids,
)
from game_collections.sources.names import SourceName
from game_collections.sources.timestamps import build_scraped_timestamp


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731

PROVIDER_SLUG = "fanatical"
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_")
# Fanatical's own product types worth a list entry: everything Steam could ever deliver.
LISTED_PRODUCT_TYPES = frozenset({"game", "bundle", "software"})


class FanaticalCrawlError(RuntimeError):
    """Fetching or writing a Fanatical offer failed."""

# end class FanaticalCrawlError


class FanaticalHttpClient:
    """Small retrying HTTP client for fanatical.com's JSON API (and Steam's store search)."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self._attempts = attempts
        # The API answers any browser-like `User-Agent`; the WAF blocks bare library defaults.
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; game-collections/0.1 fanatical metadata archiver)"},
        )
    # end def __init__

    def close(self) -> None:
        """Close pooled network resources."""
        self._client.close()
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one UTF-8 page with bounded transient retries."""
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
        raise FanaticalCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class FanaticalHttpClient


@dataclass(frozen=True, slots=True)
class CrawledFanaticalOffer:
    """One normalized bundle offer paired with its source payload."""

    archive: FanaticalArchive
    source: dict[str, Any]

# end class CrawledFanaticalOffer


@dataclass(frozen=True, slots=True)
class FanaticalCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledFanaticalOffer, ...]
    errors: tuple[str, ...]

# end class FanaticalCrawlReport


def _archive_paths(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "fanatical/bundle" / slug
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def _build_archive(
    draft: FanaticalDraft,
    mapping: FanaticalResolutionMap,
    search: SteamSearch,
    observed: datetime,
    log: LogFn,
) -> FanaticalArchive:
    """Resolve every distinct product once, then lay the tiers out in the archived shape.

    A regular bundle's tiers each list only their *newly* unlocked products, so each archived tier
    accumulates everything up to it. A pick-and-mix lists its whole pool on the first tier alone,
    and every archived tier shares that pool (they differ only in how many may be picked).
    """
    distinct: dict[str, FanaticalProduct] = {}
    for tier in draft.tiers:
        for product in tier.products:
            distinct.setdefault(product.slug, product)
        # end for
    # end for
    items: dict[str, FanaticalItem] = {}
    total = len(distinct)
    for index, (product_slug, product) in enumerate(distinct.items(), start=1):
        log(f"  Game {index}/{total}: {product.title}")
        ids = resolve_product_ids(product, draft.slug, mapping, search, log)
        items[product_slug] = FanaticalItem(
            slug=product.slug, title=product.title, product_type=product.product_type, ids=ids
        )
    # end for

    tiers: list[FanaticalTier] = []
    unlocked: dict[str, FanaticalItem] = {}
    for tier in draft.tiers:
        if draft.bundle_type == "pick-and-mix":
            tier_items = list(items.values())
        else:
            for product in tier.products:
                unlocked.setdefault(product.slug, items[product.slug])
            # end for
            tier_items = list(unlocked.values())
        # end if
        tiers.append(
            FanaticalTier(
                identifier=tier.identifier, price=tier.price, display_total=tier.display_total, items=tier_items
            )
        )
    # end for
    return FanaticalArchive(
        machine_name=draft.slug,
        url=page_url(draft.bundle_type, draft.slug),
        name=draft.name,
        bundle_type=draft.bundle_type,
        pay_what_you_want=draft.pay_what_you_want,
        discount_percent=draft.discount_percent,
        full_price=draft.full_price,
        dates=FanaticalDates(
            start=build_scraped_timestamp(draft.start, SourceName.FANATICAL, 1.0) if draft.start else None,
            end=build_scraped_timestamp(draft.end, SourceName.FANATICAL, 1.0) if draft.end else None,
            first_seen=observed,
            crawled=observed,
        ),
        tiers=tiers,
    )
# end def _build_archive


def crawl_fanatical_offers(
    fetch: Callable[[str], str],
    mapping: FanaticalResolutionMap,
    search: SteamSearch,
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledFanaticalOffer], None] | None = None,
) -> FanaticalCrawlReport:
    """Crawl explicit bundles or every currently listed one, from the single list endpoint.

    The endpoint is the only source: there is no per-bundle detail request, so an explicit URL whose
    bundle is no longer listed is an error. When `archive_root` is given, a bundle already written
    there (and still valid against the current schema) is reused as-is - no product resolution at all.
    Pass `on_offer` to write each offer to disk as soon as it's ready.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    try:
        raw_items = parse_bundles_json(fetch(BUNDLES_API_URL))
    except (OSError, ValueError, FanaticalCrawlError) as error:
        return FanaticalCrawlReport(offers=(), errors=(f"{BUNDLES_API_URL}: {error}",))
    # end try

    by_slug = {str(item.get("slug")): item for item in raw_items}
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
        slugs = list(by_slug)
    # end if

    offers: list[CrawledFanaticalOffer] = []
    total = len(slugs)
    for index, slug in enumerate(slugs, start=1):
        log(f"Bundle {index}/{total}: {slug}")
        try:
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, slug)
                cached = load_cached_archive(
                    FanaticalArchive, metadata_path, source_path, current_version=CURRENT_VERSION
                )
                if cached is not None:
                    log(f"Bundle {index}/{total}: {slug} (cached)")
                    archive, source = cached
                    offer = CrawledFanaticalOffer(archive=archive, source=source)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            raw = by_slug.get(slug)
            if raw is None:
                raise FanaticalCrawlError("not in Fanatical's currently listed bundles")
            # end if
            archive = _build_archive(parse_bundle(raw), mapping, search, observed, log)
            offer = CrawledFanaticalOffer(archive=archive, source=raw)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, FanaticalParseError, FanaticalCrawlError) as error:
            errors.append(f"{slug}: {error}")
        # end try
    # end for
    return FanaticalCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_fanatical_offers


def _listed_games(items: Iterable[FanaticalItem]) -> list[Game]:
    """Games Steam could deliver, deduped by id; books, comics and audio are archive-only.

    `software` (e-learning courses, asset packs, ...) is only listed when it resolved to a Steam
    product, i.e. carries an id other than the `fanatical:` anchor every item gets.
    """
    games: list[Game] = []
    seen_ids: set[str] = set()
    for item in items:
        if item.product_type not in LISTED_PRODUCT_TYPES:
            continue
        # end if
        if item.product_type == "software" and all(value.startswith("fanatical:") for value in item.ids):
            continue
        # end if
        if any(value in seen_ids for value in item.ids):
            continue
        # end if
        games.append(Game(name=item.title, ids=item.ids))
        seen_ids.update(item.ids)
    # end for
    return games
# end def _listed_games


def is_same_bundle(match: Path, slug: str) -> bool:
    """Whether `match` is named after exactly this bundle's slug (ignoring a leading date prefix)."""
    return DATE_PREFIX_PATTERN.sub("", match.stem if match.is_file() else match.name) == slug
# end def is_same_bundle


def _tier_name(tier: FanaticalTier, bundle_type: str) -> str:
    if bundle_type == "pick-and-mix":
        return f"pick {tier.display_total}"
    # end if
    currency = "USD" if "USD" in tier.price else next(iter(tier.price))
    return f"{tier.price[currency]:.2f} {currency}"
# end def _tier_name


def write_fanatical_offer(
    offer: CrawledFanaticalOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
    log: LogFn = _NO_LOG,
) -> tuple[Path, ...]:
    """Atomically write the archive record, plus one list unless already covered or game-less."""
    archive = offer.archive
    metadata_path, source_path = _archive_paths(archive_root, archive.machine_name)
    atomic_write(metadata_path, dump_versioned_json(CURRENT_VERSION, archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_versioned_json(CURRENT_VERSION, offer.source))
    written: list[Path] = [metadata_path, source_path]

    pool = _listed_games(item for tier in archive.tiers for item in tier.items)
    if not pool:
        log(f"  No Steam-deliverable products in {archive.machine_name}: archive only")
        return tuple(written)
    # end if
    existing = existing_list_match(
        lists_root, PROVIDER_SLUG, archive.machine_name, pool, crawler_name="fanatical"
    )
    if existing is not None and not is_same_bundle(existing, archive.machine_name):
        # `existing_list_match` also substring-matches (`all-stars-bundle` inside the older edition
        # `all-stars-bundle-2`, `python-programming-bundle` inside another bundle's name). The
        # aggregators name a list after Fanatical's own slug, so anything else is a different bundle.
        existing = None
    # end if
    if existing is not None:
        backfill_existing_lists(
            pool,
            existing,
            "fanatical",
            archive.machine_name,
            Reference(name="Fanatical bundle", url=archive.url),
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

    pick_quota: int | None = None
    tier_definitions: list[TierDefinition] = []
    if archive.bundle_type == "pick-and-mix" and len(archive.tiers) == 1:
        # One purchasable pick count: a plain quota, not a tier choice.
        pick_quota = archive.tiers[0].display_total
        games = pool
    else:
        tier_definitions, games = merge_tiered_games(
            [
                (
                    rank,
                    _tier_name(tier, archive.bundle_type),
                    _listed_games(tier.items),
                    tier.display_total if archive.bundle_type == "pick-and-mix" else None,
                )
                for rank, tier in enumerate(archive.tiers, start=1)
            ]
        )
    # end if

    game_list = GameList(
        name=archive.name,
        tiers=tier_definitions,
        pick_quota=pick_quota,
        references=[
            Reference(name="Fanatical bundle", url=archive.url),
            Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
            Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
        ],
        crawlers=["fanatical"],
        games=games,
    )
    atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
    written.append(path)
    return tuple(written)
# end def write_fanatical_offer
