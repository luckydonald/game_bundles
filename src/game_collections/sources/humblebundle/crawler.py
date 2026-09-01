"""Fetch Humble offers and write deterministic list and archive output."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from game_collections.lists import load_game_list
from game_collections.models import Game, GameGroup, GameList, Reference
from game_collections.sources.common import (
    atomic_write,
    dump_json,
    load_cached_archive,
    merge_game_list,
    render_game_list_yaml,
)
from game_collections.sources.humblebundle.models import HumbleArchive, HumbleItem, HumbleTier
from game_collections.sources.humblebundle.parser import (
    HUMBLE_ROOT,
    parse_bundle_index,
    parse_bundle_page,
    parse_choice_page,
)
from game_collections.sources.humblebundle.resolver import (
    HumbleResolutionMap,
    StorefrontResolver,
    render_resolution_map,
)


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


BUNDLES_URL = "https://www.humblebundle.com/bundles"
CHOICE_URL = "https://www.humblebundle.com/membership"
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class HumbleCrawlError(RuntimeError):
    """Fetching or writing a Humble offer failed."""

# end class HumbleCrawlError


class HumbleHttpClient:
    """Small retrying HTTP client for public Humble and store pages."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self._attempts = attempts
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "game-collections/0.1 Humble metadata archiver"},
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
        raise HumbleCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class HumbleHttpClient


@dataclass(frozen=True, slots=True)
class CrawledHumbleOffer:
    """One resolved normalized offer paired with its source payload."""

    archive: HumbleArchive
    source: dict[str, Any]

# end class CrawledHumbleOffer


@dataclass(frozen=True, slots=True)
class HumbleCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledHumbleOffer, ...]
    errors: tuple[str, ...]

# end class HumbleCrawlReport


def _validated_explicit_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"humblebundle.com", "www.humblebundle.com"}:
        raise ValueError(f"Humble URLs must use https://www.humblebundle.com: {value}")
    # end if
    if parsed.path == "/membership" or parsed.path.startswith("/games/"):
        return value
    # end if
    raise ValueError(f"expected a Humble Choice or Games URL: {value}")
# end def _validated_explicit_url


def crawl_humble_offers(
    fetch: Callable[[str], str],
    resolver: StorefrontResolver,
    mapping: HumbleResolutionMap,
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledHumbleOffer], None] | None = None,
) -> HumbleCrawlReport:
    """Crawl explicit offers or discover current Choice and active Games bundles.

    The offer's cache key depends on parsed fields, so its page is always
    fetched - but when `archive_root` is given and a valid cached archive is
    already on disk for that key, the (expensive, one-storefront-search-per-
    game) `resolver.resolve_archive` call is skipped in favor of the cached,
    already-resolved archive. Pass `on_offer` to write each offer to disk as
    soon as it's ready, rather than waiting for the whole crawl to finish.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    targets: list[tuple[str, dict[str, Any] | None]] = []
    errors: list[str] = []
    explicit = list(urls or [])
    if explicit:
        targets = [(_validated_explicit_url(url), None) for url in explicit]
    else:
        targets.append((CHOICE_URL, None))
        try:
            index = parse_bundle_index(fetch(BUNDLES_URL))
            targets.extend((urljoin(HUMBLE_ROOT, item["product_url"]), item) for item in index)
        except (OSError, ValueError, HumbleCrawlError) as error:
            errors.append(f"{BUNDLES_URL}: {error}")
        # end try
    # end if
    offers: list[CrawledHumbleOffer] = []
    total = len(targets)
    for index, (url, listing) in enumerate(targets, start=1):
        log(f"Offer {index}/{total}: {url}")
        try:
            page = fetch(url)
            if urlparse(url).path == "/membership":
                archive, source = parse_choice_page(page, observed)
            else:
                archive, source = parse_bundle_page(page, listing, observed)
            # end if
            cached = None
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, archive)
                cached = load_cached_archive(HumbleArchive, metadata_path, source_path)
            # end if
            if cached is not None:
                log(f"Offer {index}/{total}: {url} (cached, skipping resolution)")
                resolved_archive, cached_source = cached
                offer = CrawledHumbleOffer(archive=resolved_archive, source=cached_source)
            else:
                offer = CrawledHumbleOffer(
                    archive=resolver.resolve_archive(archive, mapping, log=log),
                    source=source,
                )
            # end if
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, HumbleCrawlError) as error:
            errors.append(f"{url}: {error}")
        # end try
    # end for
    return HumbleCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_humble_offers


def _offer_key(archive: HumbleArchive) -> str:
    if archive.kind == "choice":
        match = re.fullmatch(r"([a-z]+)_(\d{4})_choice", archive.machine_name)
        if not match or match.group(1) not in MONTHS:
            raise HumbleCrawlError(f"unsupported Choice machine name: {archive.machine_name}")
        # end if
        return f"{int(match.group(2)):04d}-{MONTHS[match.group(1)]:02d}"
    # end if
    date = archive.dates.start or archive.dates.end
    if date is None:
        raise HumbleCrawlError(f"bundle has neither a start nor end date: {archive.url}")
    # end if
    slug = Path(urlparse(str(archive.url)).path).name
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        raise HumbleCrawlError(f"bundle URL has an unsafe slug: {archive.url}")
    # end if
    return f"{date.date().isoformat()}_{slug}"
# end def _offer_key


def _archive_paths(archive_root: Path, archive: HumbleArchive) -> tuple[Path, Path]:
    key = _offer_key(archive)
    if archive.kind == "choice":
        directory = archive_root / "humblebundle/choice" / key
    else:
        directory = archive_root / "humblebundle/bundle" / key
    # end if
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def _item_all_ids(item: HumbleItem) -> list[str]:
    """Every qualified ID an item resolved to, whether or not it split into several games."""
    if item.resolution.splits:
        return [identifier for split in item.resolution.splits for identifier in split.ids]
    # end if
    return list(item.resolution.ids)
# end def _item_all_ids


def _games_for_item(item: HumbleItem) -> list[Game]:
    """Build one Game per item, or several when it resolved as a "DLC pack" split."""
    if item.resolution.splits:
        group = GameGroup(id=item.machine_name, name=item.title)
        return [
            Game(name=split.name, ids=split.ids, requires=item.resolution.requires, group=group)
            for split in item.resolution.splits
        ]
    # end if
    return [Game(name=item.title, ids=item.resolution.ids, requires=item.resolution.requires)]
# end def _games_for_item


def _write_merged_game_list(game_list: GameList, path: Path, lists_root: Path, repository_root: Path) -> None:
    """Merge with any already-committed list at `path` (see `merge_game_list`) before writing.

    Humble is authoritative for its own bundles: a game no longer present in
    the fresh crawl is quarantined into `invalid` (never hard-deleted, and
    restored if a later crawl lists it again), while a game still present
    keeps its existing `ids:`/`group` state rather than being replaced. An
    existing file that fails to load is a real problem (hand-edited into an
    invalid state, or a stale schema) and should fail loudly rather than being
    silently discarded and overwritten.
    """
    existing = load_game_list(path, lists_root).data if path.exists() else None
    merged = merge_game_list(existing, game_list, authoritative=True)
    atomic_write(path, render_game_list_yaml(merged, path, repository_root))
# end def _write_merged_game_list


def write_humble_offer(
    offer: CrawledHumbleOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
) -> tuple[Path, ...]:
    """Atomically write normalized/source archives and standard game lists."""
    archive = offer.archive
    key = _offer_key(archive)
    if archive.kind == "choice":
        list_directory = lists_root / "humblebundle/choice"
    else:
        list_directory = lists_root / "humblebundle/bundle" / key
    # end if
    written: list[Path] = []
    metadata_path, source_path = _archive_paths(archive_root, archive)
    atomic_write(metadata_path, dump_json(archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(offer.source))
    written.extend((metadata_path, source_path))

    if archive.kind == "choice" and archive.choice_pick_options:
        pool_games: list[Game] = []
        seen_pool_ids: set[str] = set()
        for item in archive.tiers[0].items:
            item_ids = _item_all_ids(item)
            if not item.is_game or any(value in seen_pool_ids for value in item_ids):
                continue
            # end if
            pool_games.extend(_games_for_item(item))
            seen_pool_ids.update(item_ids)
        # end for
        pick_directory = list_directory / key
        for rank, option in enumerate(archive.choice_pick_options, start=1):
            if len(archive.choice_pick_options) == 1:
                path = pick_directory / "bundle.yml"
                list_tier = None
            else:
                path = pick_directory / f"tier-{rank}.yml"
                list_tier = rank
            # end if
            game_list = GameList(
                schema=1,
                name=f"{archive.name} — {option.tier_key.title()}",
                tier=list_tier,
                pick_quota=option.quota,
                references=[
                    Reference(name="Humble Bundle offer", url=archive.url),
                    Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
                    Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
                ],
                crawlers=["humblebundle"],
                games=pool_games,
            )
            _write_merged_game_list(game_list, path, lists_root, repository_root)
            written.append(path)
        # end for
        return tuple(written)
    # end if

    tiers_with_games: list[tuple[HumbleTier, list[Game]]] = []
    for tier in archive.tiers:
        games: list[Game] = []
        seen_ids: set[str] = set()
        for item in tier.items:
            item_ids = _item_all_ids(item)
            if not item.is_game or any(value in seen_ids for value in item_ids):
                continue
            # end if
            games.extend(_games_for_item(item))
            seen_ids.update(item_ids)
        # end for
        if games:
            tiers_with_games.append((tier, games))
        # end if
    # end for
    # Humble's own `tier_order` lists the full/entire tier first (descending item
    # count); re-sort ascending so `tier-1.yml` is the smallest tier and the
    # highest-numbered file is always the full bundle, matching isthereanydeal's
    # convention and avoiding cross-source file conflicts.
    tiers_with_games.sort(key=lambda pair: pair[0].item_count)
    for rank, (tier, games) in enumerate(tiers_with_games, start=1):
        name = archive.name if archive.kind == "choice" else f"{archive.name} — {tier.name}"
        if archive.kind == "choice":
            path = list_directory / f"{key}.yml"
            list_tier = None
        elif len(tiers_with_games) == 1:
            path = list_directory / "bundle.yml"
            list_tier = None
        else:
            path = list_directory / f"tier-{rank}.yml"
            list_tier = rank
        # end if
        game_list = GameList(
            schema=1,
            name=name,
            tier=list_tier,
            references=[
                Reference(name="Humble Bundle offer", url=archive.url),
                Reference(
                    name="Crawl metadata",
                    path=os.path.relpath(metadata_path, path.parent),
                ),
                Reference(
                    name="Crawl source",
                    path=os.path.relpath(source_path, path.parent),
                ),
            ],
            crawlers=["humblebundle"],
            games=games,
        )
        _write_merged_game_list(game_list, path, lists_root, repository_root)
        written.append(path)
    # end for
    return tuple(written)
# end def write_humble_offer


def write_resolution_map(path: Path, mapping: HumbleResolutionMap) -> None:
    """Atomically persist reviewed storefront decisions."""
    atomic_write(path, render_resolution_map(mapping))
# end def write_resolution_map
