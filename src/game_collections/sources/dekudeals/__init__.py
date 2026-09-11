"""DekuDeals bundle source."""

from game_collections.sources.dekudeals.models import DekuArchive
from game_collections.sources.dekudeals.parser import (
    DekuParseError,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_item_page,
)

__all__ = [
    "DekuArchive",
    "DekuParseError",
    "parse_bundle_index_page",
    "parse_bundle_page",
    "parse_item_page",
]
