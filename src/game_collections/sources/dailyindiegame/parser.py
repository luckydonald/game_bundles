"""Parse the plain-HTML table markup served by dailyindiegame.com."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from game_collections.sources.dailyindiegame.models import (
    DigArchive,
    DigDates,
    DigItem,
    DigPrice,
)


DIG_ROOT = "https://www.dailyindiegame.com/"

BUNDLE_LINK_PATTERN = re.compile(r"^site_weeklybundle_(\d+)\.html$")
STEAM_APP_PATTERN = re.compile(r"store\.steampowered\.com/app/(\d+)")
# The bundle name is not one fixed literal - naming varies ("DIG Bundle <N>
# - ADULT", "FRIDAY BARGAIN <N>", ...) - but every bundle page has exactly
# one heading span with this class, always first, holding whatever name is
# displayed for that bundle.
TITLE_PATTERN = re.compile(
    r'<span class="DIG-contentOrangeBIG">(.*?)</span>', re.IGNORECASE | re.DOTALL
)
SUMMARY_PATTERN = re.compile(
    r"(\d+)\s+awesome STEAM games\s*,\s*worth a total of \$([\d.,]+)\.\s*"
    r"Grab them now for only \$([\d.,]+) and save (\d+)%\s*\(\$([\d.,]+)\)",
    re.IGNORECASE,
)
COUNTDOWN_PATTERN = re.compile(
    r"ends in (\d+)\s*days?\s*:\s*(\d+)\s*:\s*(\d+)\s*:\s*(\d+)",
    re.IGNORECASE,
)
GAME_LISTING_PATTERN = re.compile(
    r"\$(-?[\d.,]+)\s*\(\s*\$-?[\d.,]+\s*\)\s*[\W]*?You save:\s*\$-?[\d.,]+\s*\(-?\d+%\)\s*"
    r"Region:\s*([A-Z]+)\s*VIEW STEAM PAGE\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)
COVER_ART_PATTERN = re.compile(r"dig3-images-steam/\d+\.jpg")


class DigParseError(ValueError):
    """A DailyIndieGame page did not contain the expected structure."""

# end class DigParseError


class _VisibleTextParser(HTMLParser):
    """Flatten a page's visible text, skipping script/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        # end if
    # end def handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        # end if
    # end def handle_endtag

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)
        # end if
    # end def handle_data

# end class _VisibleTextParser


def _visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())
# end def _visible_text


class _BundleLinksParser(HTMLParser):
    """Collect distinct weekly-bundle numbers in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.numbers: list[str] = []
        self._seen: set[str] = set()
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        # end if
        href = dict(attrs).get("href")
        match = BUNDLE_LINK_PATTERN.match(href or "")
        if match and match.group(1) not in self._seen:
            self._seen.add(match.group(1))
            self.numbers.append(match.group(1))
        # end if
    # end def handle_starttag

# end class _BundleLinksParser


def parse_bundle_index_page(html: str) -> list[str]:
    """Return the weekly-bundle numbers currently listed for sale."""
    parser = _BundleLinksParser()
    parser.feed(html)
    if not parser.numbers:
        raise DigParseError("bundles page has no weekly-bundle links")
    # end if
    return parser.numbers
# end def parse_bundle_index_page


class _BundleGamesParser(HTMLParser):
    """Collect (title, steam app ID) pairs from a bundle page's game table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.games: list[tuple[str, str]] = []
        self._in_cell = False
        self._parts: list[str] = []
        self._captured = False
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "td":
            self._in_cell = True
            self._parts = []
            self._captured = False
            return
        # end if
        if tag != "a" or not self._in_cell or self._captured:
            return
        # end if
        match = STEAM_APP_PATTERN.search(dict(attrs).get("href") or "")
        if not match:
            return
        # end if
        title = " ".join("".join(self._parts).split())
        if title:
            self.games.append((title, match.group(1)))
            self._captured = True
        # end if
    # end def handle_starttag

    def handle_data(self, data: str) -> None:
        if self._in_cell and not self._captured:
            self._parts.append(data)
        # end if
    # end def handle_data

    def handle_endtag(self, tag: str) -> None:
        if tag == "td":
            self._in_cell = False
        # end if
    # end def handle_endtag

# end class _BundleGamesParser


def _dig_price(raw: str, label: str) -> DigPrice:
    try:
        value = float(raw.replace(",", ""))
    except ValueError as error:
        raise DigParseError(f"{label} is not a number: {raw!r}") from error
    # end try
    return DigPrice(raw=f"${raw}", value=value, currency="$", currency_code="USD")
# end def _dig_price


def bundle_number(url: str) -> str:
    match = BUNDLE_LINK_PATTERN.match(Path(urlparse(url).path).name)
    if not match:
        raise DigParseError(f"URL does not look like a weekly bundle page: {url}")
    # end if
    return match.group(1)
# end def bundle_number


def parse_bundle_page(html: str, url: str, crawled: datetime) -> tuple[DigArchive, dict[str, Any]]:
    """Normalize one weekly bundle detail page."""
    title_match = TITLE_PATTERN.search(html)
    if not title_match:
        raise DigParseError("bundle page is missing its DIG-contentOrangeBIG title span")
    # end if
    name = " ".join(re.sub(r"<[^>]+>", " ", title_match.group(1)).split())
    if not name:
        raise DigParseError("bundle page title span is empty")
    # end if
    text = _visible_text(html)
    summary_match = SUMMARY_PATTERN.search(text)
    if not summary_match:
        raise DigParseError("bundle page is missing its price summary sentence")
    # end if
    games_parser = _BundleGamesParser()
    games_parser.feed(html)
    if not games_parser.games:
        raise DigParseError("bundle page has no Steam-linked games")
    # end if

    crawled = crawled.astimezone(UTC)
    end: datetime | None = None
    countdown_match = COUNTDOWN_PATTERN.search(text)
    if countdown_match:
        days, hours, minutes, seconds = (int(value) for value in countdown_match.groups())
        end = crawled + timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    # end if

    machine_name = bundle_number(url)
    is_adult = "ADULT" in name.upper()
    items = [
        DigItem(
            title=title,
            ids=[f"steam:{steam_id}"],
            url=f"https://store.steampowered.com/app/{steam_id}",
        )
        for title, steam_id in games_parser.games
    ]
    archive = DigArchive(
        schema=1,
        machine_name=machine_name,
        url=url,
        name=name,
        is_adult=is_adult,
        dates=DigDates(end=end, crawled=crawled),
        game_count=len(items),
        total_value=_dig_price(summary_match.group(2), "bundle total value"),
        bundle_price=_dig_price(summary_match.group(3), "bundle price"),
        savings_percent=int(summary_match.group(4)),
        savings_amount=_dig_price(summary_match.group(5), "bundle savings amount"),
        items=items,
    )
    source = {
        "title_text": title_match.group(0),
        "summary_text": summary_match.group(0),
        "games": [{"title": title, "steam_id": steam_id} for title, steam_id in games_parser.games],
    }
    return archive, source
# end def parse_bundle_page


def parse_game_listing_page(html: str, url: str) -> dict[str, Any]:
    """Extract one game's individual price, region, description, and cover art."""
    text = _visible_text(html)
    match = GAME_LISTING_PATTERN.search(text)
    if not match:
        raise DigParseError(f"game listing page is missing price/region data: {url}")
    # end if
    cover_match = COVER_ART_PATTERN.search(html)
    return {
        "individual_price": _dig_price(match.group(1), "game individual price"),
        "region": match.group(2),
        "description": match.group(3).strip(),
        "cover_art_url": urljoin(DIG_ROOT, cover_match.group(0)) if cover_match else None,
    }
# end def parse_game_listing_page
