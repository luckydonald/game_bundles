"""Resolve Fanatical products to qualified storefront ids; persisted slug -> id lookup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self
from urllib.parse import quote_plus

import yaml
from pydantic import Field, model_validator

from game_collections.models import QualifiedGameId, StrictModel
from game_collections.sources.common import atomic_write
from game_collections.sources.fanatical.parser import FanaticalProduct
from game_collections.sources.humblebundle.resolver import STORE_SEARCH_URLS, parse_store_candidates
from game_collections.sources.storefronts import StoreCandidate, normalized_title


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731

# Product types which are never sold on Steam: only given their `fanatical:<slug>` anchor id.
NON_STEAM_PRODUCT_TYPES = frozenset({"book", "comic", "audio"})

SteamSearch = Callable[[str], list[StoreCandidate]]


class FanaticalResolutionMap(StrictModel):
    """Cached mappings from a stable Fanatical product slug to storefront ids.

    Only ids found by a title search are stored here (Fanatical's own `steamId` is
    already in the bundle data), so a product recurring across bundles is searched once.
    """

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    games: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_ids(self) -> Self:
        for product_slug, ids in self.games.items():
            if not ids:
                raise ValueError(f"resolution map entry has no IDs: {product_slug}")
            # end if
            compact = [QualifiedGameId.parse(value).compact() for value in ids]
            if len(compact) != len(set(compact)):
                raise ValueError(f"resolution map entry has duplicate IDs: {product_slug}")
            # end if
            self.games[product_slug] = compact
        # end for
        return self
    # end def validate_ids

# end class FanaticalResolutionMap


def load_resolution_map(path: Path) -> FanaticalResolutionMap:
    """Load a strict cached mapping or return an empty map when absent."""
    if not path.exists():
        return FanaticalResolutionMap(schema=1, games={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return FanaticalResolutionMap.model_validate(raw)
# end def load_resolution_map


def render_resolution_map(mapping: FanaticalResolutionMap) -> str:
    """Render the cached mapping deterministically."""
    value = mapping.model_dump(by_alias=True, mode="json")
    value["games"] = dict(sorted(value["games"].items()))
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
# end def render_resolution_map


def write_resolution_map(path: Path, mapping: FanaticalResolutionMap) -> None:
    """Atomically persist the cached mapping."""
    atomic_write(path, render_resolution_map(mapping))
# end def write_resolution_map


def steam_title_search(fetch: Callable[[str], str]) -> SteamSearch:
    """Build a Steam store title search on top of a plain page fetcher."""

    def search(title: str) -> list[StoreCandidate]:
        url = STORE_SEARCH_URLS["steam"].format(query=quote_plus(title))
        return parse_store_candidates("steam", fetch(url))
    # end def search

    return search
# end def steam_title_search


def resolve_product_ids(
    product: FanaticalProduct,
    bundle_slug: str,
    mapping: FanaticalResolutionMap,
    search: SteamSearch,
    log: LogFn = _NO_LOG,
) -> list[str]:
    """Qualified ids for one product, always ending in the `fanatical:<slug>` anchor.

    Order of preference: Fanatical's own `steamId`; a cached earlier title search; a fresh Steam title
    search accepting only a *unique exact* normalized-title match (never guessing between candidates);
    otherwise `unresolved:source:fanatical:<bundle>:<slug>` for `game-collections complete` to follow up.
    Books, comics and audio, and anything not delivered via Steam, never search at all.
    """
    anchor = f"fanatical:{product.slug}"
    if product.steam_app_id is not None:
        return [f"steam:{product.steam_app_id}", anchor]
    # end if
    if product.product_type in NON_STEAM_PRODUCT_TYPES or "steam" not in product.drm:
        return [anchor]
    # end if
    cached = mapping.games.get(product.slug)
    if cached is not None:
        return [*cached, anchor]
    # end if
    log(f"  Searching Steam for {product.title}")
    try:
        candidates = search(product.title)
    except (OSError, RuntimeError) as error:
        log(f"  Steam search failed for {product.title}: {error}")
        candidates = []
    # end try
    exact = [candidate for candidate in candidates if normalized_title(candidate.title) == normalized_title(product.title)]
    if len(exact) == 1:
        mapping.games[product.slug] = [exact[0].qualified_id]
        return [exact[0].qualified_id, anchor]
    # end if
    return [f"unresolved:source:fanatical:{bundle_slug}:{product.slug}", anchor]
# end def resolve_product_ids
