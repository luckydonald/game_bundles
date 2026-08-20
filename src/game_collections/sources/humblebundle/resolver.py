"""Resolve Humble product names to qualified storefront identities."""

from __future__ import annotations

from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Annotated, Literal, Self, cast
from urllib.parse import quote_plus, urljoin

import yaml
from pydantic import Field, StringConstraints, model_validator

from game_collections.models import QualifiedGameId, StrictModel
from game_collections.sources.humblebundle.models import HumbleArchive, HumbleItem, HumbleResolution
from game_collections.sources.humblebundle.steamdb import STEAMDB_SEARCH_URL, parse_steamdb_results
from game_collections.sources.storefronts import (
    STORE_ROOTS,
    StoreName,
    normalized_title,
    parse_store_identity,
)


__all__ = [
    "STEAMDB_SEARCH_URL",
    "STORE_ROOTS",
    "STORE_SEARCH_URLS",
    "HumbleResolutionMap",
    "StoreCandidate",
    "StoreName",
    "StorefrontResolver",
    "load_resolution_map",
    "normalized_title",
    "parse_steamdb_results",
    "parse_store_candidates",
    "parse_store_identity",
    "render_resolution_map",
]


NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ALLOWED_STORES: tuple[StoreName, ...] = ("steam", "gog", "epic", "ubisoft", "humble")
STORE_SEARCH_URLS: dict[StoreName, str] = {
    "steam": "https://store.steampowered.com/search/?term={query}",
    "gog": "https://www.gog.com/en/games?query={query}",
    "epic": "https://store.epicgames.com/en-US/browse?q={query}&sortBy=relevancy&sortDir=DESC",
    "ubisoft": "https://store.ubisoft.com/search?q={query}",
    "humble": "https://www.humblebundle.com/store/search?search={query}",
}


class StoreCandidate(StrictModel):
    """One result returned by an official storefront search."""

    title: NonEmptyString
    url: NonEmptyString
    qualified_id: NonEmptyString

# end class StoreCandidate


class HumbleResolutionMap(StrictModel):
    """Reviewed mappings from stable Humble names to storefront IDs."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    games: dict[NonEmptyString, list[NonEmptyString]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        for machine_name, ids in self.games.items():
            if not ids:
                raise ValueError(f"resolution map entry has no IDs: {machine_name}")
            # end if
            compact = [QualifiedGameId.parse(value).compact() for value in ids]
            if len(compact) != len(set(compact)):
                raise ValueError(f"resolution map entry has duplicate IDs: {machine_name}")
            # end if
            self.games[machine_name] = compact
        # end for
        return self
    # end def validate_ids

# end class HumbleResolutionMap


class _StoreLinkParser(HTMLParser):
    """Collect visible link labels from a storefront result page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self._title_parts: list[str] = []
        self._inside_title = False
        self.links: list[tuple[str, str]] = []
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "a" and self._href is None:
            href = values.get("href")
            if href:
                self._href = href
                self._parts = []
                self._title_parts = []
            # end if
            return
        # end if
        classes = (values.get("class") or "").split()
        if self._href is not None and tag in {"span", "div"} and "title" in classes:
            self._inside_title = True
        # end if
    # end def handle_starttag

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)
            if self._inside_title:
                self._title_parts.append(data)
            # end if
        # end if
    # end def handle_data

    def handle_endtag(self, tag: str) -> None:
        if tag in {"span", "div"} and self._inside_title:
            self._inside_title = False
            return
        # end if
        if tag != "a" or self._href is None:
            return
        # end if
        preferred = self._title_parts or self._parts
        title = " ".join("".join(preferred).split())
        if title:
            self.links.append((self._href, title))
        # end if
        self._href = None
        self._parts = []
        self._title_parts = []
        self._inside_title = False
    # end def handle_endtag

# end class _StoreLinkParser


def parse_store_candidates(provider: StoreName, html: str) -> list[StoreCandidate]:
    """Extract ranked canonical product links from a store search response."""
    parser = _StoreLinkParser()
    parser.feed(html)
    candidates: list[StoreCandidate] = []
    seen: set[str] = set()
    for url, title in parser.links:
        absolute_url = urljoin(STORE_ROOTS[provider], url)
        try:
            qualified_id = parse_store_identity(provider, absolute_url)
        except ValueError:
            continue
        # end try
        if qualified_id in seen:
            continue
        # end if
        seen.add(qualified_id)
        candidates.append(StoreCandidate(title=title, url=absolute_url, qualified_id=qualified_id))
        if len(candidates) == 10:
            break
        # end if
    # end for
    return candidates
# end def parse_store_candidates


def load_resolution_map(path: Path) -> HumbleResolutionMap:
    """Load a strict reviewed mapping or return an empty map when absent."""
    if not path.exists():
        return HumbleResolutionMap(schema=1, games={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return HumbleResolutionMap.model_validate(raw)
# end def load_resolution_map


def render_resolution_map(mapping: HumbleResolutionMap) -> str:
    """Render the reviewed mapping deterministically."""
    value = mapping.model_dump(by_alias=True, mode="json")
    value["games"] = dict(sorted(value["games"].items()))
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
# end def render_resolution_map


CandidateChooser = Callable[[HumbleItem, StoreName, list[StoreCandidate]], str | None]
Fetcher = Callable[[str], str]
LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class StorefrontResolver:
    """Resolve item identities using official store searches and reviewed choices."""

    def __init__(self, fetch: Fetcher, choose: CandidateChooser, steamdb_fetch: Fetcher | None = None) -> None:
        self._fetch = fetch
        self._choose = choose
        self._steamdb_fetch = steamdb_fetch
    # end def __init__

    def search(self, provider: StoreName, title: str) -> list[StoreCandidate]:
        """Search a storefront and return its ranked product candidates."""
        url = STORE_SEARCH_URLS[provider].format(query=quote_plus(title))
        return parse_store_candidates(provider, self._fetch(url))
    # end def search

    def _search_steam(self, title: str) -> list[StoreCandidate]:
        """Search steampowered.com first; fall back to steamdb.info if not a unique match.

        steamdb.info's own search is often better at finding the exact
        product, but it sits behind a Cloudflare managed challenge that needs
        a real headed browser session (see `humblebundle.steamdb`), so it is
        only tried when the cheap steampowered.com search alone doesn't
        already resolve unambiguously.
        """
        candidates = self.search("steam", title)
        exact = [
            candidate for candidate in candidates if normalized_title(candidate.title) == normalized_title(title)
        ]
        if len(exact) == 1 or self._steamdb_fetch is None:
            return candidates
        # end if
        try:
            url = STEAMDB_SEARCH_URL.format(query=quote_plus(title))
            results = parse_steamdb_results(self._steamdb_fetch(url))
        except (OSError, RuntimeError):
            return candidates
        # end try
        if not results:
            return candidates
        # end if
        return [
            StoreCandidate(
                title=result_title,
                url=f"https://store.steampowered.com/app/{appid}/",
                qualified_id=f"steam:{appid}",
            )
            for appid, result_title in results
        ]
    # end def _search_steam

    def resolve_item(self, item: HumbleItem, mapping: HumbleResolutionMap) -> list[str]:
        """Resolve one game, updating the durable mapping in memory."""
        existing = mapping.games.get(item.machine_name)
        if existing is not None:
            return list(existing)
        # end if
        ids: list[str] = []
        unresolved_stores: list[str] = []
        stores = [store for store in item.redeem_on if store in ALLOWED_STORES]
        for store_value in stores:
            typed_provider = cast(StoreName, store_value)
            try:
                candidates = (
                    self._search_steam(item.title)
                    if typed_provider == "steam"
                    else self.search(typed_provider, item.title)
                )
            except (OSError, RuntimeError):
                candidates = []
            # end try
            exact = [
                candidate
                for candidate in candidates
                if normalized_title(candidate.title) == normalized_title(item.title)
            ]
            if len(exact) == 1:
                ids.append(exact[0].qualified_id)
                continue
            # end if
            selected = self._choose(item, typed_provider, candidates)
            if selected is None:
                unresolved_stores.append(typed_provider)
                continue
            # end if
            ids.append(parse_store_identity(typed_provider, selected))
        # end for
        if not ids:
            ids.append(f"unresolved:source:humblebundle:{item.machine_name}")
        # end if
        mapping.games[item.machine_name] = list(dict.fromkeys(ids))
        return mapping.games[item.machine_name]
    # end def resolve_item

    def resolve_archive(
        self,
        archive: HumbleArchive,
        mapping: HumbleResolutionMap,
        log: LogFn = _NO_LOG,
    ) -> HumbleArchive:
        """Resolve every distinct real game and update all cumulative tier copies."""
        distinct: list[HumbleItem] = []
        seen_names: set[str] = set()
        for tier in archive.tiers:
            for item in tier.items:
                if item.is_game and item.machine_name not in seen_names:
                    seen_names.add(item.machine_name)
                    distinct.append(item)
                # end if
            # end for
        # end for
        resolved: dict[str, list[str]] = {}
        unresolved_by_name: dict[str, list[str]] = {}
        total = len(distinct)
        for index, item in enumerate(distinct, start=1):
            log(f"  Game {index}/{total}: {item.title}")
            ids = self.resolve_item(item, mapping)
            resolved[item.machine_name] = ids
            unresolved_by_name[item.machine_name] = [
                store
                for store in item.redeem_on
                if not any(identifier.startswith(f"{store}:") for identifier in ids)
            ]
        # end for
        tiers = []
        for tier in archive.tiers:
            items = []
            for item in tier.items:
                if item.machine_name not in resolved:
                    items.append(item)
                    continue
                # end if
                items.append(
                    item.model_copy(
                        update={
                            "resolution": HumbleResolution(
                                ids=resolved[item.machine_name],
                                unresolved_stores=unresolved_by_name[item.machine_name],
                            )
                        }
                    )
                )
            # end for
            tiers.append(tier.model_copy(update={"items": items}))
        # end for
        return archive.model_copy(update={"tiers": tiers})
    # end def resolve_archive

# end class StorefrontResolver
