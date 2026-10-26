"""Fanatical bundle source."""

from game_collections.sources.fanatical.models import FanaticalArchive
from game_collections.sources.fanatical.parser import (
    FanaticalParseError,
    bundle_slug,
    parse_bundle,
    parse_bundles_json,
)

__all__ = [
    "FanaticalArchive",
    "FanaticalParseError",
    "bundle_slug",
    "parse_bundle",
    "parse_bundles_json",
]
