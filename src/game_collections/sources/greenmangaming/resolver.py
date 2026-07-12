"""Resolve Green Man Gaming product names to qualified storefront identities."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self, cast

import yaml
from pydantic import Field, model_validator

from game_collections.models import QualifiedGameId, StrictModel
from game_collections.sources.greenmangaming.models import GmgArchive, GmgItem, GmgResolution
from game_collections.sources.humblebundle.resolver import (
    STORE_ROOTS,
    STORE_SEARCH_URLS,
    StoreCandidate,
    StoreName,
    normalized_title,
    parse_store_candidates,
    parse_store_identity,
)


__all__ = [
    "STORE_ROOTS",
    "STORE_SEARCH_URLS",
    "StoreCandidate",
    "StoreName",
    "normalized_title",
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


CandidateChooser = Callable[[GmgItem, StoreName, list[StoreCandidate]], str | None]
Fetcher = Callable[[str], str]
LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class StorefrontResolver:
    """Resolve item identities using official store searches and reviewed choices."""

    def __init__(self, fetch: Fetcher, choose: CandidateChooser) -> None:
        self._fetch = fetch
        self._choose = choose
    # end def __init__

    def search(self, provider: StoreName, title: str) -> list[StoreCandidate]:
        """Search a storefront and return its ranked product candidates."""
        from urllib.parse import quote_plus

        url = STORE_SEARCH_URLS[provider].format(query=quote_plus(title))
        return parse_store_candidates(provider, self._fetch(url))
    # end def search

    def resolve_item(self, item: GmgItem, mapping: GmgResolutionMap) -> list[str]:
        """Resolve one game, updating the durable mapping in memory."""
        existing = mapping.games.get(item.product_id)
        if existing is not None:
            return list(existing)
        # end if
        ids: list[str] = []
        unresolved_stores: list[str] = []
        for store_value in item.redeem_on:
            typed_provider = cast(StoreName, store_value)
            try:
                candidates = self.search(typed_provider, item.title)
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
            ids.append(f"unresolved:source:greenmangaming:{item.product_id}")
        # end if
        mapping.games[item.product_id] = list(dict.fromkeys(ids))
        return mapping.games[item.product_id]
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
        resolved: dict[str, list[str]] = {}
        unresolved_by_id: dict[str, list[str]] = {}
        total = len(distinct)
        for index, item in enumerate(distinct, start=1):
            log(f"  Game {index}/{total}: {item.title}")
            ids = self.resolve_item(item, mapping)
            resolved[item.product_id] = ids
            unresolved_by_id[item.product_id] = [
                store
                for store in item.redeem_on
                if not any(identifier.startswith(f"{store}:") for identifier in ids)
            ]
        # end for
        tiers = []
        for tier in archive.tiers:
            items = []
            for item in tier.items:
                if item.product_id not in resolved:
                    items.append(item)
                    continue
                # end if
                items.append(
                    item.model_copy(
                        update={
                            "resolution": GmgResolution(
                                ids=resolved[item.product_id],
                                unresolved_stores=unresolved_by_id[item.product_id],
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
