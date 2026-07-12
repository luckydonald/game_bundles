"""Fetch Humble offers and write deterministic list and archive output."""

from __future__ import annotations

import json
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
import yaml

from game_collections.models import Game, GameList
from game_collections.sources.humblebundle.models import HumbleArchive
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
) -> HumbleCrawlReport:
    """Crawl explicit offers or discover current Choice and active Games bundles."""
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
    for url, listing in targets:
        try:
            page = fetch(url)
            if urlparse(url).path == "/membership":
                archive, source = parse_choice_page(page, observed)
            else:
                archive, source = parse_bundle_page(page, listing, observed)
            # end if
            offers.append(
                CrawledHumbleOffer(
                    archive=resolver.resolve_archive(archive, mapping),
                    source=source,
                )
            )
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


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # end with
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    # end try
# end def _atomic_write


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
# end def _json


def _game_list_yaml(game_list: GameList, path: Path, repository_root: Path) -> str:
    schema_path = os.path.relpath(repository_root / "schemas/game-list.schema.json", path.parent)
    value = game_list.model_dump(by_alias=True, mode="json")
    return (
        f"# yaml-language-server: $schema={schema_path}\n"
        + yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    )
# end def _game_list_yaml


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
        archive_directory = archive_root / "humblebundle/choice" / key
        list_directory = lists_root / "humblebundle/choice"
    else:
        archive_directory = archive_root / "humblebundle/bundle" / key
        list_directory = lists_root / "humblebundle/bundle" / key
    # end if
    written: list[Path] = []
    metadata_path = archive_directory / "metadata.json"
    source_path = archive_directory / "source.json"
    _atomic_write(metadata_path, _json(archive.model_dump(by_alias=True, mode="json")))
    _atomic_write(source_path, _json(offer.source))
    written.extend((metadata_path, source_path))
    for index, tier in enumerate(archive.tiers):
        games = [
            Game(name=item.title, ids=item.resolution.ids)
            for item in tier.items
            if item.is_game
        ]
        if not games:
            continue
        # end if
        name = archive.name if archive.kind == "choice" else f"{archive.name} — {tier.name}"
        game_list = GameList(schema=1, name=name, games=games)
        if archive.kind == "choice":
            path = list_directory / f"{key}.yml"
        else:
            prefix = "entire-" if index == 0 else ""
            path = list_directory / f"{prefix}{tier.item_count}-item-bundle.yml"
        # end if
        _atomic_write(path, _game_list_yaml(game_list, path, repository_root))
        written.append(path)
    # end for
    return tuple(written)
# end def write_humble_offer


def write_resolution_map(path: Path, mapping: HumbleResolutionMap) -> None:
    """Atomically persist reviewed storefront decisions."""
    _atomic_write(path, render_resolution_map(mapping))
# end def write_resolution_map
