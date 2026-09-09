"""Resolve Green Man Gaming product names to qualified storefront identities."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import Field, model_validator

from game_collections.models import NonEmptyString, QualifiedGameId, StrictModel
from game_collections.sources.greenmangaming.models import GmgArchive, GmgItem, GmgResolution, GmgResolvedGame
from game_collections.sources.humblebundle.resolver import (
    STORE_SEARCH_URLS,
    StoreCandidate,
    parse_store_candidates,
)
from game_collections.sources.humblebundle.steamdb import STEAMDB_SEARCH_URL, parse_steamdb_results
from game_collections.sources.prompting import ChosenCandidate, ChosenNames
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
    "ResolvedGame",
    "StoreCandidate",
    "StoreName",
    "normalized_title",
    "parse_steamdb_results",
    "parse_store_candidates",
    "parse_store_identity",
]


# Green Man Gaming reports a single free-text DRM platform per product
# (e.g. "Steam", "GOG", "Uplay"). Only values recognized here pick a store to
# search; anything else is left unresolved rather than guessed.
DRM_STORE_MAP: dict[str, StoreName] = {
    "steam": "steam",
    "gog": "gog",
    "epic": "epic",
    "epic games store": "epic",
    "uplay": "ubisoft",
    "ubisoft connect": "ubisoft",
}


def redeem_on_for_drm(drm: str | None) -> list[str]:
    """Map a Green Man Gaming DRM label to the stores worth searching."""
    if drm is None:
        return []
    # end if
    store = DRM_STORE_MAP.get(drm.strip().casefold())
    return [store] if store else []
# end def redeem_on_for_drm


class GmgResolutionMap(StrictModel):
    """Reviewed mappings from stable Green Man Gaming product IDs to storefront IDs."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    games: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        for product_id, ids in self.games.items():
            if not ids:
                raise ValueError(f"resolution map entry has no IDs: {product_id}")
            # end if
            compact = [QualifiedGameId.parse(value).compact() for value in ids]
            if len(compact) != len(set(compact)):
                raise ValueError(f"resolution map entry has duplicate IDs: {product_id}")
            # end if
            self.games[product_id] = compact
        # end for
        return self
    # end def validate_ids

# end class GmgResolutionMap


def load_resolution_map(path: Path) -> GmgResolutionMap:
    """Load a strict reviewed mapping or return an empty map when absent."""
    if not path.exists():
        return GmgResolutionMap(schema=1, games={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return GmgResolutionMap.model_validate(raw)
# end def load_resolution_map


def render_resolution_map(mapping: GmgResolutionMap) -> str:
    """Render the reviewed mapping deterministically."""
    value = mapping.model_dump(by_alias=True, mode="json")
    value["games"] = dict(sorted(value["games"].items()))
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
# end def render_resolution_map


CandidateChooser = Callable[..., ChosenCandidate]
Fetcher = Callable[[str], str]
LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class ResolvedGame(StrictModel):
    """One resolved game produced from an item - usually one, several when split."""

    name: NonEmptyString
    ids: list[NonEmptyString] = Field(default_factory=list)

# end class ResolvedGame


class StorefrontResolver:
    """Resolve item identities using official store searches and reviewed choices."""

    def __init__(self, fetch: Fetcher, choose: CandidateChooser, steamdb_fetch: Fetcher | None = None) -> None:
        self._fetch = fetch
        self._choose = choose
        self._steamdb_fetch = steamdb_fetch
    # end def __init__

    def search(self, provider: StoreName, title: str) -> list[StoreCandidate]:
        """Search a storefront and return its ranked product candidates."""
        from urllib.parse import quote_plus

        url = STORE_SEARCH_URLS[provider].format(query=quote_plus(title))
        return parse_store_candidates(provider, self._fetch(url))
    # end def search

    def _search_steam(self, title: str) -> list[StoreCandidate]:
        """Search steampowered.com first; fall back to steamdb.info if not a unique match.

        See `humblebundle.resolver.StorefrontResolver._search_steam` (this
        class mirrors it) for why steamdb.info is only a fallback: it needs a
        real headed browser session (`humblebundle.steamdb`), so it's only
        tried when steampowered.com's own search doesn't already resolve
        unambiguously.
        """
        from urllib.parse import quote_plus

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

    def _resolve_title(
        self,
        title: str,
        stores: list[str],
        cache_key: str,
        mapping: GmgResolutionMap,
        known_names: set[str] | None = None,
    ) -> list[ResolvedGame]:
        """Resolve one title across `stores`, caching the plain (unsplit) result under `cache_key`.

        See `humblebundle.resolver.StorefrontResolver._resolve_title` (this
        mirrors it): more than one `ResolvedGame` comes back only when the
        user declares "Multiple…" for some store, splitting the title into
        sub-titles that are each re-resolved from scratch.

        `known_names`, when given, is a live set of casefolded names already destined for the
        current bundle - seeded by `resolve_archive` from every distinct item's title. `title`
        itself is removed from it for the duration of this call (it's about to be either kept as
        one entry or replaced by a split), and added back before any "kept as one entry" return,
        so a "Multiple…" prompt that defaults to `title` doesn't immediately reject its own
        default, while a duplicate typed against any *other* name is still caught immediately -
        see `prompting.choose_store_candidate`.
        """
        if known_names is not None:
            known_names.discard(title.casefold())
        # end if
        existing = mapping.games.get(cache_key)
        if existing is not None:
            if known_names is not None:
                known_names.add(title.casefold())
            # end if
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
                ids.append(exact[0].qualified_id)
                continue
            # end if
            selected = self._choose(title, typed_provider, candidates, known_names=known_names)
            if selected is None:
                continue
            # end if
            if isinstance(selected, ChosenNames):
                results: list[ResolvedGame] = []
                for index, sub_title in enumerate(selected.names, start=1):
                    results.extend(
                        self._resolve_title(sub_title, stores, f"{cache_key}::{index}", mapping, known_names)
                    )
                # end for
                return results
            # end if
            ids.append(parse_store_identity(typed_provider, selected))
        # end for
        if not ids:
            ids.append(f"unresolved:source:greenmangaming:{cache_key}")
        # end if
        deduped = list(dict.fromkeys(ids))
        mapping.games[cache_key] = deduped
        if known_names is not None:
            known_names.add(title.casefold())
        # end if
        return [ResolvedGame(name=title, ids=deduped)]
    # end def _resolve_title

    def resolve_item(
        self, item: GmgItem, mapping: GmgResolutionMap, known_names: set[str] | None = None
    ) -> list[ResolvedGame]:
        """Resolve one game, updating the durable mapping in memory."""
        return self._resolve_title(item.title, item.redeem_on, item.product_id, mapping, known_names)
    # end def resolve_item

    def resolve_archive(
        self,
        archive: GmgArchive,
        mapping: GmgResolutionMap,
        log: LogFn = _NO_LOG,
    ) -> GmgArchive:
        """Resolve every distinct product and update all cumulative tier copies."""
        distinct: list[GmgItem] = []
        seen_ids: set[str] = set()
        for tier in archive.tiers:
            for item in tier.items:
                if item.product_id not in seen_ids:
                    seen_ids.add(item.product_id)
                    distinct.append(item)
                # end if
            # end for
        # end for
        known_names = {item.title.casefold() for item in distinct}
        resolutions: dict[str, GmgResolution] = {}
        total = len(distinct)
        for index, item in enumerate(distinct, start=1):
            log(f"  Game {index}/{total}: {item.title}")
            results = self.resolve_item(item, mapping, known_names)
            all_ids = [identifier for entry in results for identifier in entry.ids]
            unresolved_stores = [
                store for store in item.redeem_on if not any(identifier.startswith(f"{store}:") for identifier in all_ids)
            ]
            if len(results) > 1:
                resolutions[item.product_id] = GmgResolution(
                    splits=[GmgResolvedGame(name=entry.name, ids=entry.ids) for entry in results],
                    unresolved_stores=unresolved_stores,
                )
            else:
                resolutions[item.product_id] = GmgResolution(ids=all_ids, unresolved_stores=unresolved_stores)
            # end if
        # end for
        tiers = []
        for tier in archive.tiers:
            items = []
            for item in tier.items:
                if item.product_id not in resolutions:
                    items.append(item)
                    continue
                # end if
                items.append(item.model_copy(update={"resolution": resolutions[item.product_id]}))
            # end for
            tiers.append(tier.model_copy(update={"items": items}))
        # end for
        return archive.model_copy(update={"tiers": tiers})
    # end def resolve_archive

# end class StorefrontResolver
