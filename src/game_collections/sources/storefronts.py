"""Storefront URL identity parsing shared by every source that links to official stores."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Literal
from urllib.parse import unquote, urlparse

from game_collections.models import NonEmptyString, QualifiedGameId, StrictModel


StoreName = Literal["steam", "gog", "epic", "ubisoft", "humble"]
STORE_ROOTS: dict[StoreName, str] = {
    "steam": "https://store.steampowered.com/",
    "gog": "https://www.gog.com/",
    "epic": "https://store.epicgames.com/",
    "ubisoft": "https://store.ubisoft.com/",
    "humble": "https://www.humblebundle.com/",
}

# Every host a store's product pages may be served from - epic and humble
# each have two live host forms in the wild (confirmed via real ITAD deal
# redirects: Epic serves https://www.epicgames.com/store/p/... alongside the
# https://store.epicgames.com/... form STORE_ROOTS/search results use).
STORE_HOSTS: dict[StoreName, frozenset[str]] = {
    "steam": frozenset({"store.steampowered.com"}),
    "gog": frozenset({"gog.com", "www.gog.com"}),
    "epic": frozenset({"store.epicgames.com", "www.epicgames.com"}),
    "ubisoft": frozenset({"store.ubisoft.com", "www.ubisoft.com"}),
    "humble": frozenset({"humblebundle.com", "www.humblebundle.com"}),
}


class StoreCandidate(StrictModel):
    """One result returned by an official storefront search."""

    title: NonEmptyString
    url: NonEmptyString
    qualified_id: NonEmptyString

# end class StoreCandidate


def normalized_title(value: str) -> str:
    """Normalize storefront punctuation and spacing for exact title comparison."""
    without_marks = value.translate(str.maketrans({"™": "", "®": "", "©": ""}))
    normalized = unicodedata.normalize("NFKD", without_marks).casefold()
    return "".join(character for character in normalized if character.isalnum())
# end def normalized_title


def _canonical_slug(path: str, marker: str) -> str | None:
    components = [unquote(value) for value in path.split("/") if value]
    try:
        index = components.index(marker)
    except ValueError:
        return None
    # end try
    if index + 1 >= len(components):
        return None
    # end if
    return components[index + 1].removesuffix(".html")
# end def _canonical_slug


def parse_store_identity(provider: StoreName, value: str) -> str:
    """Parse a provider-specific URL, direct ID, or qualified ID."""
    raw = value.strip()
    if not raw:
        raise ValueError("store identity must not be empty")
    # end if
    if ":" in raw and not raw.startswith(("http://", "https://")):
        identifier = QualifiedGameId.parse(raw)
        if identifier.provider != provider:
            raise ValueError(f"expected a {provider} identity, got {identifier.provider}")
        # end if
        return identifier.compact()
    # end if
    if provider == "steam" and raw.isdecimal():
        if int(raw) <= 0:
            raise ValueError("Steam AppID must be positive")
        # end if
        return f"steam:{int(raw)}"
    # end if
    parsed = urlparse(raw)
    host = (parsed.hostname or "").casefold()
    path = parsed.path
    slug: str | None = None
    if provider == "steam":
        if host not in STORE_HOSTS["steam"]:
            raise ValueError("Steam URLs must use store.steampowered.com")
        # end if
        app_match = re.search(r"/app/(\d+)(?:/|$)", path)
        if app_match:
            return f"steam:{int(app_match.group(1))}"
        # end if
        # A bundle (e.g. a "Deluxe Edition" only sold as a bundle of the base
        # app + DLC) has no single AppID; kept as its own `bundle/<id>` value
        # rather than a plain int so ownership matching (which needs a real
        # AppID) can tell it apart - see `completion.evaluate_completion`.
        bundle_match = re.search(r"/bundle/(\d+)(?:/|$)", path)
        if bundle_match:
            return f"steam:bundle/{int(bundle_match.group(1))}"
        # end if
        raise ValueError("Steam URL does not contain an AppID or bundle ID")
    # end if
    if provider == "gog":
        if host not in STORE_HOSTS["gog"]:
            raise ValueError("GOG URLs must use gog.com")
        # end if
        slug = _canonical_slug(path, "game")
    elif provider == "epic":
        if host not in STORE_HOSTS["epic"]:
            raise ValueError("Epic URLs must use store.epicgames.com or www.epicgames.com")
        # end if
        slug = _canonical_slug(path, "p")
    elif provider == "ubisoft":
        if host not in STORE_HOSTS["ubisoft"]:
            raise ValueError("Ubisoft URLs must use an official Ubisoft store host")
        # end if
        slug = _canonical_slug(path, "game")
        if slug is None:
            components = [part for part in path.split("/") if part]
            slug = components[-1].removesuffix(".html") if components else None
        # end if
    elif provider == "humble":
        if host not in STORE_HOSTS["humble"]:
            raise ValueError("Humble Store URLs must use humblebundle.com")
        # end if
        slug = _canonical_slug(path, "store")
    # end if
    if not slug:
        raise ValueError(f"could not derive a {provider} product ID from URL")
    # end if
    return f"{provider}:{slug}"
# end def parse_store_identity


_PRODUCT_PATH_MARKERS: dict[str, str] = {
    "steam": "app",
    "gog": "game",
    "epic": "p",
    "ubisoft": "game",
    "humble": "store",
}


def product_url(provider: str, value: str) -> str | None:
    """Build a storefront product page URL from a qualified ID's ``value``.

    The inverse of :func:`parse_store_identity`'s URL branch. Returns ``None`` for any provider
    that isn't one of the known, directly-linkable :data:`StoreName` stores - covers markers like
    ``unresolved`` or ``isthereanydeal`` that aren't real storefronts and have no product page.
    """
    if provider == "steam" and value.startswith("bundle/"):
        return f"{STORE_ROOTS['steam']}{value}"
    # end if
    marker = _PRODUCT_PATH_MARKERS.get(provider)
    if marker is None:
        return None
    # end if
    return f"{STORE_ROOTS[provider]}{marker}/{value}"
# end def product_url


def match_store(url: str) -> StoreName | None:
    """Return the launcher-relevant `StoreName` whose official host(s) this URL belongs to."""
    host = (urlparse(url).hostname or "").casefold()
    return next((provider for provider, hosts in STORE_HOSTS.items() if host in hosts), None)
# end def match_store


def _microsoft_store_identity(url: str) -> str | None:
    """`https://apps.microsoft.com/detail/<product-id>` -> `microsoft:<product-id>` (confirmed live)."""
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() != "apps.microsoft.com":
        return None
    # end if
    match = re.search(r"/detail/([^/?#]+)", parsed.path)
    return f"microsoft:{match.group(1)}" if match else None
# end def _microsoft_store_identity


def _2game_identity(url: str) -> str | None:
    """`https://www.2game.com/<locale>/products/<slug>` -> `2game:<slug>` (confirmed live)."""
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() not in {"2game.com", "www.2game.com"}:
        return None
    # end if
    components = [part for part in parsed.path.split("/") if part]
    return f"2game:{components[-1]}" if components else None
# end def _2game_identity


# Extra, launcher-irrelevant ITAD shops with a verified redirect-URL shape.
# Each is added only once a real deal redirect has actually been observed
# (see config/isthereanydeal-shops.yml and the ITAD solver's `resolve_game`
# for where these come from) - many more `isthereanydeal-shops.yml` entries
# have a `slug` set but no verified shape yet (Amazon, Fanatical, itch.io,
# Blizzard, Oculus, EA, Razer, WinGameStore, MacGameStore, App Store, Google
# Play, ...); those deals are skipped, not guessed, until verified here.
EXTRA_STORE_PARSERS: tuple[Callable[[str], str | None], ...] = (
    _microsoft_store_identity,
    _2game_identity,
)


def is_known_store_url(url: str) -> bool:
    """Return whether `url` belongs to any recognized store (launcher-relevant or extra)."""
    if match_store(url) is not None:
        return True
    # end if
    return any(parser(url) is not None for parser in EXTRA_STORE_PARSERS)
# end def is_known_store_url


def qualified_ids_from_urls(urls: list[str]) -> list[str]:
    """Resolve every recognized storefront URL into a qualified ID, deduped and ordered.

    Tries every launcher-relevant `StoreName` (`STORE_HOSTS`/`parse_store_identity`)
    first, then the smaller set of ITAD-only `EXTRA_STORE_PARSERS`. URLs
    matching neither are silently skipped, same as an unrecognized store
    always was here.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for url in urls:
        qualified_id: str | None = None
        provider = match_store(url)
        if provider is not None:
            try:
                qualified_id = parse_store_identity(provider, url)
            except ValueError:
                qualified_id = None
            # end try
        # end if
        if qualified_id is None:
            for parser in EXTRA_STORE_PARSERS:
                qualified_id = parser(url)
                if qualified_id is not None:
                    break
                # end if
            # end for
        # end if
        if qualified_id is None or qualified_id in seen:
            continue
        # end if
        seen.add(qualified_id)
        ids.append(qualified_id)
    # end for
    return ids
# end def qualified_ids_from_urls
