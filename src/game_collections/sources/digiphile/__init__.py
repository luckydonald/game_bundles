"""Digiphile bundle source."""

from game_collections.sources.digiphile.models import DigiphileArchive
from game_collections.sources.digiphile.parser import (
    DigiphileParseError,
    bundle_slug,
    extract_bundle,
    extract_bundle_slugs,
    parse_bundle,
)

__all__ = [
    "DigiphileArchive",
    "DigiphileParseError",
    "bundle_slug",
    "extract_bundle",
    "extract_bundle_slugs",
    "parse_bundle",
]
