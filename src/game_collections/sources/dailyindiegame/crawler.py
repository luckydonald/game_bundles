"""Fetch DailyIndieGame bundles and write deterministic list and archive output."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from game_collections.models import Game, GameList, Reference
from game_collections.sources.common import (
    atomic_write,
    dump_json,
    load_cached_archive,
    render_game_list_yaml,
)
from game_collections.sources.dailyindiegame.models import DigArchive, DigItem
from game_collections.sources.dailyindiegame.parser import (
    DIG_ROOT,
    BUNDLE_LINK_PATTERN,
    bundle_number,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_game_listing_page,
)


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


INDEX_URL = f"{DIG_ROOT}site_content_bundles.html"


class DigCrawlError(RuntimeError):
    """Fetching or writing a DailyIndieGame offer failed."""

# end class DigCrawlError


class DigBrowserClient:
    """Browser fetcher: dailyindiegame.com sits behind a Cloudflare managed challenge.

    Plain HTTP clients get an instant 403, and even Playwright's stock Chromium
    hangs on the challenge forever regardless of headless/stealth tweaks
    (Cloudflare fingerprints CDP-driven automation). `patchright` is a
    Playwright fork patched specifically to evade that detection, but only in
    a *headed* persistent context - a plain `launch(headless=True)` context
    (patchright or not) still hangs indefinitely on this site.
    """

    def __init__(self, timeout: float = 30.0, attempts: int = 3) -> None:
        # Imported lazily so importing this module (e.g. for unit tests that
        # inject a fake `fetch`) never requires `patchright` or its downloaded
        # browser binary to be present.
        import tempfile

        from patchright.sync_api import sync_playwright

        self._attempts = attempts
        self._timeout_ms = timeout * 1000
        self._playwright = sync_playwright().start()
        self._user_data_dir = tempfile.mkdtemp(prefix="dig-patchright-")
        self._context = self._playwright.chromium.launch_persistent_context(
            self._user_data_dir,
            headless=False,
            no_viewport=True,
        )
    # end def __init__

    def close(self) -> None:
        """Close the browser and its Playwright driver."""
        import shutil

        self._context.close()
        self._playwright.stop()
        shutil.rmtree(self._user_data_dir, ignore_errors=True)
    # end def close

    def fetch(self, url: str) -> str:
        """Fetch one page's rendered HTML, waiting out the Cloudflare challenge."""
        last_error: Exception | None = None
        for attempt in range(1, self._attempts + 1):
            page = self._context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
                # The challenge (and the redirect that follows it) resolve
                # client-side; poll the tab title rather than a fixed sleep.
                deadline = time.monotonic() + self._timeout_ms / 1000
                while time.monotonic() < deadline:
                    title = page.title()
                    if "Just a moment" not in title and not title.startswith("Loading "):
                        break
                    # end if
                    time.sleep(1)
                # end while
                # This site never reaches true network idle (persistent
                # connections/polling), but a bounded best-effort wait still
                # gives client-side rendering more time than a fixed sleep
                # alone before falling back once the timeout elapses.
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:  # noqa: BLE001 - timeout is expected, not fatal
                    pass
                # end try
                page.wait_for_timeout(3000)
                return page.content()
            except Exception as error:  # noqa: BLE001 - Playwright raises its own broad errors
                last_error = error
                if attempt == self._attempts:
                    break
                # end if
                time.sleep(0.5 * (2 ** (attempt - 1)))
            finally:
                page.close()
            # end try
        # end for
        raise DigCrawlError(f"request failed for {url}: {last_error}") from last_error
    # end def fetch

# end class DigBrowserClient


@dataclass(frozen=True, slots=True)
class CrawledDigOffer:
    """One normalized bundle offer paired with its source payload."""

    archive: DigArchive
    source: dict[str, Any]

# end class CrawledDigOffer


@dataclass(frozen=True, slots=True)
class DigCrawlReport:
    """Successful offers and isolated failures from one crawl."""

    offers: tuple[CrawledDigOffer, ...]
    errors: tuple[str, ...]

# end class DigCrawlReport


def _validated_explicit_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"dailyindiegame.com", "www.dailyindiegame.com"}:
        raise ValueError(f"DailyIndieGame URLs must use https://www.dailyindiegame.com: {value}")
    # end if
    if BUNDLE_LINK_PATTERN.match(Path(parsed.path).name):
        return value
    # end if
    raise ValueError(f"expected a DailyIndieGame weekly bundle URL: {value}")
# end def _validated_explicit_url


def _archive_paths(archive_root: Path, number: str) -> tuple[Path, Path]:
    directory = archive_root / "dailyindiegame/bundle" / number
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def _enrich_item(
    item: DigItem,
    fetch: Callable[[str], str],
    log: LogFn,
    index: int,
    total: int,
) -> DigItem:
    log(f"  Game {index}/{total}: {item.title}")
    listing_url = f"{DIG_ROOT}site_gamelisting_{item.ids[0].removeprefix('steam:')}.html"
    listing = parse_game_listing_page(fetch(listing_url), listing_url)
    # model_copy(update=...) does not revalidate, so build via model_validate
    # instead - the listing's cover_art_url must go through HttpUrl coercion.
    return DigItem.model_validate(item.model_dump() | listing)
# end def _enrich_item


def crawl_dig_offers(
    fetch: Callable[[str], str],
    urls: Iterable[str] | None = None,
    crawled: datetime | None = None,
    archive_root: Path | None = None,
    log: LogFn = _NO_LOG,
    on_offer: Callable[[CrawledDigOffer], None] | None = None,
) -> DigCrawlReport:
    """Crawl explicit bundle pages or discover every currently listed bundle.

    When `archive_root` is given, a bundle already written there (and still
    valid against the current schema) is reused as-is - no bundle-page or
    per-game listing-page fetch at all - instead of being re-crawled. Pass
    `on_offer` to write each offer to disk as soon as it's ready, rather than
    waiting for the whole crawl to finish.
    """
    observed = (crawled or datetime.now(UTC)).astimezone(UTC)
    errors: list[str] = []
    explicit = list(urls or [])
    if explicit:
        targets = [_validated_explicit_url(url) for url in explicit]
    else:
        targets = []
        try:
            numbers = parse_bundle_index_page(fetch(INDEX_URL))
            targets = [f"{DIG_ROOT}site_weeklybundle_{number}.html" for number in numbers]
        except (OSError, ValueError, DigCrawlError) as error:
            errors.append(f"{INDEX_URL}: {error}")
        # end try
    # end if
    offers: list[CrawledDigOffer] = []
    total = len(targets)
    for index, url in enumerate(targets, start=1):
        number = bundle_number(url)
        log(f"Bundle {index}/{total}: {number}")
        try:
            if archive_root is not None:
                metadata_path, source_path = _archive_paths(archive_root, number)
                cached = load_cached_archive(DigArchive, metadata_path, source_path)
                if cached is not None:
                    log(f"Bundle {index}/{total}: {number} (cached)")
                    archive, source = cached
                    offer = CrawledDigOffer(archive=archive, source=source)
                    offers.append(offer)
                    if on_offer is not None:
                        on_offer(offer)
                    # end if
                    continue
                # end if
            # end if
            page = fetch(url)
            archive, source = parse_bundle_page(page, url, observed)
            item_total = len(archive.items)
            enriched_items = [
                _enrich_item(item, fetch, log, item_index, item_total)
                for item_index, item in enumerate(archive.items, start=1)
            ]
            archive = archive.model_copy(update={"items": enriched_items})
            offer = CrawledDigOffer(archive=archive, source=source)
            offers.append(offer)
            if on_offer is not None:
                on_offer(offer)
            # end if
        except (OSError, ValueError, DigCrawlError) as error:
            errors.append(f"{url}: {error}")
        # end try
    # end for
    return DigCrawlReport(offers=tuple(offers), errors=tuple(errors))
# end def crawl_dig_offers


def write_dig_offer(
    offer: CrawledDigOffer,
    lists_root: Path,
    archive_root: Path,
    repository_root: Path,
) -> tuple[Path, ...]:
    """Atomically write the normalized/source archive and standard game list."""
    archive = offer.archive
    list_directory = lists_root / "dailyindiegame/bundle"
    metadata_path, source_path = _archive_paths(archive_root, archive.machine_name)
    atomic_write(metadata_path, dump_json(archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(offer.source))
    written: list[Path] = [metadata_path, source_path]

    games: list[Game] = []
    seen_ids: set[str] = set()
    for item in archive.items:
        if any(value in seen_ids for value in item.ids):
            continue
        # end if
        games.append(Game(name=item.title, ids=item.ids))
        seen_ids.update(item.ids)
    # end for
    path = list_directory / f"{archive.machine_name}.yml"
    game_list = GameList(
        schema=1,
        name=archive.name,
        references=[
            Reference(name="DailyIndieGame bundle", url=archive.url),
            Reference(name="Crawl metadata", path=os.path.relpath(metadata_path, path.parent)),
            Reference(name="Crawl source", path=os.path.relpath(source_path, path.parent)),
        ],
        crawlers=["dailyindiegame"],
        games=games,
    )
    atomic_write(path, render_game_list_yaml(game_list, path, repository_root))
    written.append(path)
    return tuple(written)
# end def write_dig_offer
