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
from game_collections.sources.humblebundle.models import (
    HumbleArchive,
    HumbleItem,
    HumbleResolution,
    HumbleResolvedGame,
)
from game_collections.sources.humblebundle.steamdb import (
    STEAMDB_SEARCH_URL,
    STEAMDB_SUB_URL,
    parse_steamdb_results,
    parse_steamdb_sub_apps,
)
from game_collections.sources.prompting import (
    ChosenCandidate,
    EnterMultiple,
)
from game_collections.sources.prompting import announce_exact_match as _default_announce_exact_match
from game_collections.sources.prompting import collect_one_name as _default_collect_one_name
from game_collections.sources.storefronts import (
    STORE_ROOTS,
    StoreCandidate,
    StoreName,
    normalized_title,
    parse_store_identity,
)


__all__ = [
    "STEAMDB_SEARCH_URL",
    "STEAMDB_SUB_URL",
    "STORE_ROOTS",
    "STORE_SEARCH_URLS",
    "EnterMultiple",
    "HumbleResolutionMap",
    "ResolvedGame",
    "StoreCandidate",
    "StoreName",
    "StorefrontResolver",
    "load_resolution_map",
    "normalized_title",
    "parse_steamdb_results",
    "parse_steamdb_sub_apps",
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


CandidateChooser = Callable[[str, StoreName, list[StoreCandidate]], ChosenCandidate]
NameCollector = Callable[[int], str | None]
AnnounceFn = Callable[[str, str], None]
Fetcher = Callable[[str], str]
LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class ResolvedGame(StrictModel):
    """One resolved game produced from an item - usually one, several when split."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(default_factory=list)
    requires: list[NonEmptyString] = Field(default_factory=list)

# end class ResolvedGame


class StorefrontResolver:
    """Resolve item identities using official store searches and reviewed choices."""

    def __init__(
        self,
        fetch: Fetcher,
        choose: CandidateChooser,
        steamdb_fetch: Fetcher | None = None,
        collect_name: NameCollector = _default_collect_one_name,
        announce_exact_match: AnnounceFn = _default_announce_exact_match,
    ) -> None:
        self._fetch = fetch
        self._choose = choose
        self._steamdb_fetch = steamdb_fetch
        self._collect_name = collect_name
        self._announce_exact_match = announce_exact_match
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
                # `result_id` is a bare appid ("1123050") for an App row, or
                # "bundle/<id>" for a Bundle row (see `parse_steamdb_results`).
                url=f"https://store.steampowered.com/{result_id if '/' in result_id else f'app/{result_id}'}/",
                qualified_id=f"steam:{result_id}",
            )
            for result_id, result_title in results
        ]
    # end def _search_steam

    def _resolve_steam_sub(self, sub_id: str) -> list[tuple[int, str]] | None:
        """Fetch a Steam package's own steamdb.info page and parse its member apps.

        Returns `None` (never an empty list) if there's no steamdb fetcher, the fetch fails, or
        the page has no recognizable app rows - callers fall back to normal single-title handling.
        """
        if self._steamdb_fetch is None:
            return None
        # end if
        try:
            apps = parse_steamdb_sub_apps(self._steamdb_fetch(STEAMDB_SUB_URL.format(sub_id=sub_id)))
        except (OSError, RuntimeError):
            return None
        # end try
        return apps or None
    # end def _resolve_steam_sub

    def _resolve_title(
        self,
        title: str,
        stores: list[str],
        cache_key: str,
        mapping: HumbleResolutionMap,
        allow_multiple: bool = True,
    ) -> list[ResolvedGame]:
        """Resolve one title across `stores`, caching the plain (unsplit) result under `cache_key`.

        Returns more than one `ResolvedGame` when the user declares "Multiple…" for some store -
        names are then collected and resolved one at a time, immediately, via `_collect_name`
        (each re-resolved from scratch across every store, `allow_multiple=False` so a name
        collected this way can't itself be split again, cached under its own compound key so
        re-runs don't re-prompt; a unique exact match found this way is announced via
        `_announce_exact_match` for transparency, since it would otherwise happen silently) - or
        when a unique exact match turns out to be a Steam package/"Sub" (e.g. an "Edition"
        bundling a base app + its DLCs into one purchase, with no single matching app page) - that
        Sub is expanded into one entry per app it contains instead of being kept as an inert
        `steam:sub/<id>` (which, like a Steam retail bundle, can't drive ownership matching on its
        own), each cached under its own compound key with the appid already known, no re-search
        needed. `allow_multiple=False` also omits the "Multiple…" row itself from the menu.
        """
        existing = mapping.games.get(cache_key)
        if existing is not None:
            return [ResolvedGame(name=title, ids=list(existing))]
        # end if
        ids: list[str] = []
        for store_value in stores:
            typed_provider = cast(StoreName, store_value)
            try:
                candidates = (
                    self._search_steam(title) if typed_provider == "steam" else self.search(typed_provider, title)
                )
            except (OSError, RuntimeError):
                candidates = []
            # end try
            exact = [
                candidate for candidate in candidates if normalized_title(candidate.title) == normalized_title(title)
            ]
            if len(exact) == 1:
                match = exact[0]
                sub_id = (
                    match.qualified_id.removeprefix("steam:sub/")
                    if typed_provider == "steam" and match.qualified_id.startswith("steam:sub/")
                    else None
                )
                sub_apps = self._resolve_steam_sub(sub_id) if sub_id is not None else None
                if sub_apps is not None:
                    results: list[ResolvedGame] = []
                    for index, (appid, name) in enumerate(sub_apps, start=1):
                        split_ids = [f"steam:{appid}"]
                        mapping.games[f"{cache_key}::{index}"] = split_ids
                        results.append(ResolvedGame(name=name, ids=split_ids))
                    # end for
                    return results
                # end if
                if not allow_multiple:
                    self._announce_exact_match(match.qualified_id, match.url)
                # end if
                ids.append(match.qualified_id)
                continue
            # end if
            store_resolved = False
            while not store_resolved:
                selected = self._choose(
                    title, typed_provider, candidates, allow_multiple=allow_multiple, interleaved=True
                )
                if selected is None:
                    store_resolved = True
                    continue
                # end if
                if isinstance(selected, EnterMultiple):
                    multiple_results: list[ResolvedGame] = []
                    count = 0
                    while True:
                        name = self._collect_name(count)
                        if name is None:
                            break
                        # end if
                        count += 1
                        multiple_results.extend(
                            self._resolve_title(name, stores, f"{cache_key}::{count}", mapping, allow_multiple=False)
                        )
                    # end while
                    if not multiple_results:
                        continue
                    # end if
                    return multiple_results
                # end if
                ids.append(parse_store_identity(typed_provider, selected))
                store_resolved = True
            # end while
        # end for
        if not ids:
            ids.append(f"unresolved:source:humblebundle:{cache_key}")
        # end if
        deduped = list(dict.fromkeys(ids))
        mapping.games[cache_key] = deduped
        return [ResolvedGame(name=title, ids=deduped)]
    # end def _resolve_title

    def resolve_item(self, item: HumbleItem, mapping: HumbleResolutionMap) -> list[ResolvedGame]:
        """Resolve one item, possibly splitting into several games (a "DLC pack"/"Edition bundle",
        a user-declared "Multiple…", or an auto-expanded Steam Sub - see `_resolve_title`)."""
        stores = [store for store in item.redeem_on if store in ALLOWED_STORES]
        requires: list[str] = []
        if item.base_game_url is not None:
            try:
                requires = [parse_store_identity("steam", str(item.base_game_url))]
            except ValueError:
                requires = []
            # end try
        # end if
        component_titles = item.bundled_dlc_names or item.edition_component_titles
        if component_titles:
            results: list[ResolvedGame] = []
            for index, component_title in enumerate(component_titles, start=1):
                for resolved in self._resolve_title(
                    component_title, stores, f"{item.machine_name}::{index}", mapping
                ):
                    results.append(resolved.model_copy(update={"requires": requires}))
                # end for
            # end for
            return results
        # end if
        resolved = self._resolve_title(item.title, stores, item.machine_name, mapping)
        return [entry.model_copy(update={"requires": requires}) for entry in resolved]
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
        resolutions: dict[str, HumbleResolution] = {}
        total = len(distinct)
        for index, item in enumerate(distinct, start=1):
            log(f"  Game {index}/{total}: {item.title}")
            results = self.resolve_item(item, mapping)
            all_ids = [identifier for entry in results for identifier in entry.ids]
            unresolved_stores = [
                store for store in item.redeem_on if not any(identifier.startswith(f"{store}:") for identifier in all_ids)
            ]
            requires = results[0].requires if results else []
            # `results` holds more than one entry not just for a parser-driven split
            # (`bundled_dlc_names`/`edition_component_titles`), but also whenever resolution
            # itself discovered several distinct games from a single title - the user declaring
            # "Multiple…" interactively, or a Steam Sub auto-expanding into its member apps (see
            # `_resolve_title`) - each case needs its own `Game` entry, not one entry sharing all
            # their ids.
            if item.bundled_dlc_names or item.edition_component_titles or len(results) > 1:
                resolutions[item.machine_name] = HumbleResolution(
                    splits=[HumbleResolvedGame(name=entry.name, ids=entry.ids) for entry in results],
                    unresolved_stores=unresolved_stores,
                    requires=requires,
                )
            else:
                resolutions[item.machine_name] = HumbleResolution(
                    ids=all_ids,
                    unresolved_stores=unresolved_stores,
                    requires=requires,
                )
            # end if
        # end for
        tiers = []
        for tier in archive.tiers:
            items = []
            for item in tier.items:
                if item.machine_name not in resolutions:
                    items.append(item)
                    continue
                # end if
                items.append(item.model_copy(update={"resolution": resolutions[item.machine_name]}))
            # end for
            tiers.append(tier.model_copy(update={"items": items}))
        # end for
        return archive.model_copy(update={"tiers": tiers})
    # end def resolve_archive

# end class StorefrontResolver
