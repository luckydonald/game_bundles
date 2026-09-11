"""The single canonical list of crawler/source names, shared across every module that
names a specific source instead of re-declaring an ad-hoc string or Literal each time."""

from __future__ import annotations

from enum import StrEnum


class SourceName(StrEnum):
    """One entry per `sources/<name>/` crawler package."""

    HUMBLEBUNDLE = "humblebundle"
    GREENMANGAMING = "greenmangaming"
    DAILYINDIEGAME = "dailyindiegame"
    ISTHEREANYDEAL = "isthereanydeal"
    DEKUDEALS = "dekudeals"

# end class SourceName
