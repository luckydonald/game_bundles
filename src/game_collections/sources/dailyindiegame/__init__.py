"""DailyIndieGame bundle source."""

from game_collections.sources.dailyindiegame.models import DigArchive
from game_collections.sources.dailyindiegame.parser import (
    DigParseError,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_game_listing_page,
)

__all__ = [
    "DigArchive",
    "DigParseError",
    "parse_bundle_index_page",
    "parse_bundle_page",
    "parse_game_listing_page",
]
