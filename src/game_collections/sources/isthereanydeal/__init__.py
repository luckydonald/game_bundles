"""isthereanydeal.com bundle-aggregator source."""

from game_collections.sources.isthereanydeal.models import ItadArchive
from game_collections.sources.isthereanydeal.parser import (
    ItadParseError,
    parse_bootstrap_page,
    parse_bundle_detail_page,
    parse_list_page,
)

__all__ = [
    "ItadArchive",
    "ItadParseError",
    "parse_bootstrap_page",
    "parse_bundle_detail_page",
    "parse_list_page",
]
