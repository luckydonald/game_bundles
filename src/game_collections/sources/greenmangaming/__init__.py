"""Green Man Gaming bundle source."""

from game_collections.sources.greenmangaming.models import GmgArchive
from game_collections.sources.greenmangaming.parser import (
    GmgParseError,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_product_fragment,
)

__all__ = [
    "GmgArchive",
    "GmgParseError",
    "parse_bundle_index_page",
    "parse_bundle_page",
    "parse_product_fragment",
]
