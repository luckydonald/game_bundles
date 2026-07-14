"""Fetch isthereanydeal.com (ITAD) bundle offers and write deterministic list/archive output."""

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

from game_collections.models import Game, GameList, Reference
from game_collections.sources.common import (
    atomic_write,
    dump_json,
    load_cached_archive,
    render_game_list_yaml,
)
from game_collections.sources.isthereanydeal.models import ItadArchive, ItadByobTier, ItadDates, ItadListSummary, ItadTier
from game_collections.sources.isthereanydeal.parser import (
    ItadParseError,
    parse_bootstrap_page,
    parse_bundle_detail_byob,
    parse_bundle_detail_json,
    parse_bundle_detail_page,
    parse_list_page,
    real_provider_slug,
    real_provider_url,
)
from game_collections.sources.isthereanydeal.provider_config import ItadProviderConfig, resolve_provider_slug


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731

ITAD_ROOT = "https://isthereanydeal.com/"
BUNDLES_INDEX_URL = f"{ITAD_ROOT}bundles/"
LIST_API_URL = f"{ITAD_ROOT}bundles/api/list/"
GAME_INFO_API_URL = f"{ITAD_ROOT}api/game/info/"
PAGE_SIZE = 30
DEFAULT_TABS: tuple[str, ...] = ("live",)

# The one known fixed-cadence bundle (Humble Choice, YYYY-MM with no day) is
# always deduped away by the dedicated Humble scraper before a list write
# happens, but the rule is kept general in case another provider's
# monthly-cadence bundle ever needs it.
_MONTHLY_TITLE_PATTERN = re.compile(r"^Humble Choice ([A-Za-z]+) (\d{4})$")
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


class ItadCrawlError(RuntimeError):
    """Fetching or writing an ITAD offer failed."""

# end class ItadCrawlError


class ItadHttpClient:
    """Small retrying HTTP client for isthereanydeal.com's public pages and list API."""

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        self._attempts = attempts
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "game-collections/0.1 isthereanydeal metadata archiver"},
        )
        self._token: str | None = None
    # end def __init__

    def close(self) -> None:
        """Close pooled network resources."""
        self._client.close()
    # end def close

    def _send(self, request: Callable[[], httpx.Response]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                response = request()
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"transient HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                # end if
                return response
            except httpx.HTTPError as error:
                last_error = error
                if attempt == self._attempts:
                    break
                # end if
                time.sleep(0.25 * (2 ** (attempt - 1)))
            # end try
        # end for
        raise ItadCrawlError(f"request failed: {last_error}") from last_error
    # end def _send

    def fetch(self, url: str) -> str:
        """Fetch one UTF-8 HTML page with bounded transient retries."""
        response = self._send(lambda: self._client.get(url))
        response.raise_for_status()
        return response.text
    # end def fetch

    def bootstrap(self) -> None:
        """Anonymously visit `/bundles/` to obtain the session cookie and CSRF-style token."""
        html = self.fetch(BUNDLES_INDEX_URL)
        token, _shop_names = parse_bootstrap_page(html)
        self._token = token
    # end def bootstrap

    def list_page(self, tab: str, offset: int) -> tuple[bool, list[ItadListSummary]]:
        """Fetch and validate one page of the bundle discovery API."""
        if self._token is None:
            self.bootstrap()
        # end if

        def send() -> httpx.Response:
            return self._client.post(
                LIST_API_URL,
                params={"tab": tab},
                json={"offset": offset, "sort": None, "filter": None},
                headers={"Accept": "application/json", "itad-sessiontoken": self._token or ""},
            )
        # end def send

        response = self._send(send)
        if response.status_code == 400:
            # The anonymous session token expired or was never valid; refresh once.
            self.bootstrap()
            response = self._send(send)
        # end if
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise ItadCrawlError(f"list API returned invalid JSON: {error}") from error
        # end try
        try:
            return parse_list_page(payload)
        except ItadParseError as error:
            raise ItadCrawlError(f"list API response for tab={tab} offset={offset}: {error}") from error
        # end try
    # end def list_page

    def fetch_deals(self, gid: str) -> dict[str, Any]:
        """Fetch one game's raw `deals` payload from the anonymous game-info API."""
        if self._token is None:
            self.bootstrap()
        # end if

        def send() -> httpx.Response:
            return self._client.post(
                GAME_INFO_API_URL,
                json={"gid": gid},
                headers={"Accept": "application/json", "itad-sessiontoken": self._token or ""},
            )
        # end def send

        response = self._send(send)
        if response.status_code == 400:
            # Same anonymous-token expiry/invalidity as `list_page`; refresh once.
            self.bootstrap()
            response = self._send(send)
        # end if
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise ItadCrawlError(f"game info API returned invalid JSON: {error}") from error
        # end try
        if not isinstance(payload, dict):
            raise ItadCrawlError(f"game info API response for gid={gid} has an unexpected shape")
        # end if
        return payload
    # end def fetch_deals

    def resolve_redirect(self, url: str) -> str:
        """Follow one `itad.link/...` deal redirect to its real storefront URL.

        Uses GET, not HEAD - some destination stores (confirmed: Microsoft
        Store) reject HEAD requests with a 403 even though GET succeeds.
        """
        response = self._send(lambda: self._client.get(url))
        response.raise_for_status()
        return str(response.url)
    # end def resolve_redirect

# end class ItadHttpClient


@dataclass(frozen=True, slots=True)
class CrawledItadOffer:
    """One normalized ITAD offer paired with its validated list-API summary."""

    archive: ItadArchive
    summary: ItadListSummary

# end class CrawledItadOffer


@dataclass(frozen=True, slots=True)
class ItadCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledItadOffer, ...]
    errors: tuple[str, ...]

# end class ItadCrawlReport


ListPageFetcher = Callable[[str, int], tuple[bool, list[ItadListSummary]]]


def _discover_summaries(list_page: ListPageFetcher, tabs: Iterable[str], log: LogFn) -> list[ItadListSummary]:
    summaries: list[ItadListSummary] = []
    for tab in tabs:
        offset = 0
        while True:
            log(f"Discovering {tab} bundles: offset {offset}")
            done, page = list_page(tab, offset)
            summaries.extend(page)
            if done or not page:
                break
            # end if
            offset += PAGE_SIZE
        # end while
    # end for
    return summaries
# end def _discover_summaries


def _bundle_date_prefix(summary: ItadListSummary, provider_slug: str, start: datetime) -> str:
    if provider_slug == "humblebundle":
        match = _MONTHLY_TITLE_PATTERN.match(summary.title)
        if match:
            month_name, year = match.groups()
            month = _MONTHS.get(month_name.casefold())
            if month is not None:
                return f"{int(year):04d}-{month:02d}"
            # end if
        # end if
    # end if
    return start.date().isoformat()
# end def _bundle_date_prefix


def _archive_paths(archive_root: Path, bundle_id: int) -> tuple[Path, Path]:
    directory = archive_root / "isthereanydeal/bundle" / str(bundle_id)
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def crawl_itad_offers(
    fetch: Callable[[str], str],
    list_page: ListPageFetcher,
    provider_config: ItadProviderConfig,
    tabs: Iterable[str] = DEFAULT_TABS,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledItadOffer], None] | None = None,
    shop_names: dict[int, str] | None = None,
) -> ItadCrawlReport:
    """Discover bundles across the requested tabs and normalize each one's detail page.

    `fetch` retrieves one plain HTML page (used for bundle detail pages, and
    internally by `list_page`'s own bootstrap step); `list_page(tab, offset)`
    fetches and validates one page of the discovery API - both are injectable
    so tests never need a live network. See `ItadHttpClient.fetch`/`list_page`
    for the real implementations. When `archive_root` is given and a valid
    cached archive already exists for a bundle id, its detail page
    fetch/parse is skipped entirely in favor of the cached, already-
    normalized archive. Pass `on_offer` to write each offer to disk as soon
    as it's ready, rather than waiting for the whole crawl to finish. Pass
    `shop_names` (the reviewed `config/isthereanydeal-shops.yml` table) to
    get a corroboration log line when a game's shop-key ids don't match any
    resolved storefront id - purely informational, never affects resolution.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    try:
        summaries = _discover_summaries(list_page, tabs, log)
    except (OSError, ValueError, ItadCrawlError) as error:
        return ItadCrawlReport(offers=(), errors=(f"{LIST_API_URL}: {error}",))
    # end try

    offers: list[CrawledItadOffer] = []
    total = len(summaries)
    for index, summary in enumerate(summaries, start=1):
        log(f"Bundle {index}/{total}: {summary.title} ({summary.page.name})")
        try:
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, summary.id)
                cached = load_cached_archive(ItadArchive, metadata_path, source_path)
                if cached is not None:
                    log(f"Bundle {index}/{total}: {summary.title} (cached)")
                    archive, source = cached
                    cached_summary = ItadListSummary.model_validate(source)
                    offer = CrawledItadOffer(archive=archive, summary=cached_summary)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            detail_url = f"{ITAD_ROOT}bundles/{summary.id}/"
            html = fetch(detail_url)
            provider_slug = resolve_provider_slug(summary.page, provider_config, log)
            tiers: list[ItadTier] | None = None
            try:
                tiers = parse_bundle_detail_json(
                    html, summary.id, summary.counts.games, provider_slug, shop_names=shop_names, log=log
                )
            except ItadParseError as error:
                log(f"  {summary.id}: embedded page data failed to parse ({error}), falling back to HTML parsing")
            # end try
            if tiers is None:
                if not summary.is_mature:
                    # Mature-rated bundles normally parse fine via the JSON
                    # path above (their embedded data isn't gated, only the
                    # page's visual rendering is) - the legacy HTML fallback
                    # only works for non-mature bundles, whose titles/links
                    # still render even without the JSON blob.
                    log(f"  {summary.id}: no embedded page data, falling back to HTML parsing")
                # end if
                tiers = parse_bundle_detail_page(html, summary.id, summary.counts.games)
            # end if
            byob_tiers: list[ItadByobTier] = []
            if summary.byob:
                try:
                    byob_tiers = parse_bundle_detail_byob(html, summary.id) or []
                except ItadParseError as error:
                    log(f"  {summary.id}: byob data failed to parse ({error}), leaving it unmodeled")
                # end try
            # end if
            slug = real_provider_slug(summary.url)
            archive = ItadArchive(
                schema=1,
                id=summary.id,
                title=summary.title,
                provider_name=summary.page.name,
                provider_slug=provider_slug,
                real_slug=slug,
                url=detail_url,
                dates=ItadDates(
                    start=datetime.fromtimestamp(summary.start, tz=UTC) if summary.start is not None else None,
                    expiry=datetime.fromtimestamp(summary.expiry, tz=UTC) if summary.expiry is not None else None,
                    crawled=observed,
                ),
                tiers=tiers,
                byob_tiers=byob_tiers,
            )
            offer = CrawledItadOffer(archive=archive, summary=summary)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, ItadParseError, ItadCrawlError) as error:
            errors.append(f"bundle {summary.id} ({summary.title}): {error}")
        # end try
    # end for
    return ItadCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_itad_offers


def _existing_choice_match(lists_root: Path, provider_slug: str, summary: ItadListSummary) -> Path | None:
    """Dedup check specific to Humble Choice: a different naming scheme entirely.

    The dedicated Humble scraper writes Choice months as
    `lists/humblebundle/choice/<YYYY-MM>.yml` - no bundle slug text at all -
    so the generic substring dedup below can never match it against ITAD's
    "Humble Choice <Month> <Year>" title. Checked separately, using the same
    monthly-title pattern the date-prefix cadence detection uses.
    """
    if provider_slug != "humblebundle":
        return None
    # end if
    match = _MONTHLY_TITLE_PATTERN.match(summary.title)
    if not match:
        return None
    # end if
    month_name, year = match.groups()
    month = _MONTHS.get(month_name.casefold())
    if month is None:
        return None
    # end if
    path = lists_root / "humblebundle/choice" / f"{int(year):04d}-{month:02d}.yml"
    return path if path.exists() else None
# end def _existing_choice_match


def _existing_list_match(lists_root: Path, provider_slug: str, real_slug: str) -> Path | None:
    """Best-effort dedup check: is this bundle already covered by a dedicated scraper?

    Matches by substring, not exact path, since e.g. Humble's own directories
    are date-prefixed (`2026-07-10_squad-goals`) rather than the bare slug.
    """
    provider_root = lists_root / provider_slug
    if not provider_root.is_dir():
        return None
    # end if
    needle = real_slug.casefold()
    for path in sorted(provider_root.rglob("*")):
        if needle and needle in path.name.casefold():
            return path
        # end if
    # end for
    return None
# end def _existing_list_match


def write_itad_offer(
    offer: CrawledItadOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
    log: LogFn = _NO_LOG,
) -> tuple[Path, ...]:
    """Atomically write the archive record, plus one list per tier unless already covered."""
    archive = offer.archive
    metadata_path, source_path = _archive_paths(archive_root, archive.id)
    atomic_write(metadata_path, dump_json(archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(offer.summary.model_dump(by_alias=True, mode="json")))
    written: list[Path] = [metadata_path, source_path]

    existing = _existing_choice_match(lists_root, archive.provider_slug, offer.summary) or _existing_list_match(
        lists_root, archive.provider_slug, archive.real_slug
    )
    if existing is not None:
        log(f"  Skipped {archive.real_slug}: already covered by {existing}")
        return tuple(written)
    # end if

    date_prefix = _bundle_date_prefix(offer.summary, archive.provider_slug, archive.dates.start or archive.dates.crawled)
    list_directory = lists_root / archive.provider_slug / "bundle" / f"{date_prefix}_{archive.real_slug}"

    if archive.byob_tiers:
        pool_games: list[Game] = []
        seen_ids: set[str] = set()
        for tier in archive.tiers:
            for item in tier.items:
                if any(value in seen_ids for value in item.ids):
                    continue
                # end if
                pool_games.append(Game(name=item.title, ids=item.ids))
                seen_ids.update(item.ids)
            # end for
        # end for
        for rank, byob_tier in enumerate(archive.byob_tiers, start=1):
            if len(archive.byob_tiers) == 1:
                path = list_directory / "bundle.yml"
                list_tier = None
            else:
                path = list_directory / f"tier-{rank}.yml"
                list_tier = rank
            # end if
            game_list = GameList(
                schema=1,
                name=f"{archive.title} — pick {byob_tier.count}",
                tier=list_tier,
                pick_quota=byob_tier.count,
                references=[
                    Reference(name="isthereanydeal.com bundle", url=archive.url),
                    Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
                    Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
                ],
                games=pool_games,
            )
            atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
            written.append(path)
        # end for
        return tuple(written)
    # end if

    tiers_with_games: list[tuple[ItadTier, list[Game]]] = []
    for tier in archive.tiers:
        games: list[Game] = []
        seen_ids: set[str] = set()
        for item in tier.items:
            if any(value in seen_ids for value in item.ids):
                continue
            # end if
            games.append(Game(name=item.title, ids=item.ids))
            seen_ids.update(item.ids)
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
            name=f"{archive.title} — {tier.name}",
            tier=list_tier,
            references=[
                Reference(name="isthereanydeal.com bundle", url=archive.url),
                Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
                Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
            ],
            games=games,
        )
        atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
        written.append(path)
    # end for
    return tuple(written)
# end def write_itad_offer
