"""Storefront URL identity parsing shared by every source that links to official stores."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal
from urllib.parse import unquote, urlparse

from game_collections.models import QualifiedGameId


StoreName = Literal["steam", "gog", "epic", "ubisoft", "humble"]
STORE_ROOTS: dict[StoreName, str] = {
    "steam": "https://store.steampowered.com/",
    "gog": "https://www.gog.com/",
    "epic": "https://store.epicgames.com/",
    "ubisoft": "https://store.ubisoft.com/",
    "humble": "https://www.humblebundle.com/",
}


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
        if host != "store.steampowered.com":
            raise ValueError("Steam URLs must use store.steampowered.com")
        # end if
        match = re.search(r"/app/(\d+)(?:/|$)", path)
        if not match:
            raise ValueError("Steam URL does not contain an AppID")
        # end if
        return f"steam:{int(match.group(1))}"
    # end if
    if provider == "gog":
        if host not in {"gog.com", "www.gog.com"}:
            raise ValueError("GOG URLs must use gog.com")
        # end if
        slug = _canonical_slug(path, "game")
    elif provider == "epic":
        if host != "store.epicgames.com":
            raise ValueError("Epic URLs must use store.epicgames.com")
        # end if
        slug = _canonical_slug(path, "p")
    elif provider == "ubisoft":
        if host not in {"store.ubisoft.com", "www.ubisoft.com"}:
            raise ValueError("Ubisoft URLs must use an official Ubisoft store host")
        # end if
        slug = _canonical_slug(path, "game")
        if slug is None:
            components = [part for part in path.split("/") if part]
            slug = components[-1].removesuffix(".html") if components else None
        # end if
    elif provider == "humble":
        if host not in {"humblebundle.com", "www.humblebundle.com"}:
            raise ValueError("Humble Store URLs must use humblebundle.com")
        # end if
        slug = _canonical_slug(path, "store")
    # end if
    if not slug:
        raise ValueError(f"could not derive a {provider} product ID from URL")
    # end if
    return f"{provider}:{slug}"
# end def parse_store_identity
