"""Backfill historical Humble Choice monthly lists from a community mirror.

Humble's own site does not expose past Choice months to guests, so this
one-off script reads https://dangarbri.tech/humblechoice, which mirrors every
month back to June 2023 (title, genre, and a per-game
``humblebundle.com/membership/<month>-<year>/<slug>`` link), and writes the
same list/archive shape ``game-collections scrape humblebundle`` produces for
the current month.

Usage::

    uv run python scripts/backfill_humble_choice.py --month 2026-06 --month 2026-05
    uv run python scripts/backfill_humble_choice.py --from 2024-01 --to 2024-12
    uv run python scripts/backfill_humble_choice.py --all --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from game_collections.models import Game, GameList, Reference  # noqa: E402
from game_collections.search import complete_game_list  # noqa: E402
from game_collections.sources.common import atomic_write, dump_json, render_game_list_yaml  # noqa: E402
from game_collections.sources.humblebundle.crawler import (  # noqa: E402
    MONTHS,
    HumbleCrawlError,
    HumbleHttpClient,
)
from game_collections.sources.humblebundle.resolver import StorefrontResolver  # noqa: E402


DANGARBRI_URL = "https://dangarbri.tech/humblechoice"
LISTS_ROOT = REPO_ROOT / "lists"
ARCHIVE_ROOT = REPO_ROOT / "archives"
MONTH_KEY_RE = re.compile(r"^\d{4}-\d{2}$")
# Standalone roman-numeral tokens (I-X) so page titles like "Octopath Traveler Ii"
# read as "Octopath Traveler II".
ROMAN_TOKEN_RE = re.compile(
    r"\b(X|IX|VIII|VII|VI|V|IV|III|II|I)\b", re.IGNORECASE
)


class MirrorEntry(NamedTuple):
    title: str
    genre: str
    url: str


class _DangarbriParser(HTMLParser):
    """Collect month headings and their game-card entries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.months: dict[str, list[MirrorEntry]] = {}
        self._current_month: str | None = None
        self._in_h2 = False
        self._h2_text: list[str] = []
        self._in_card = False
        self._href: str | None = None
        self._field: str | None = None
        self._title_parts: list[str] = []
        self._genre_parts: list[str] = []
    # end def __init__

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "h2":
            self._in_h2 = True
            self._h2_text = []
        elif tag == "div" and (attributes.get("class") or "") == "game-card":
            self._in_card = True
            self._href = None
            self._title_parts = []
            self._genre_parts = []
        elif self._in_card and tag == "a" and "href" in attributes:
            self._href = attributes["href"]
        elif self._in_card and tag == "p":
            css_class = attributes.get("class") or ""
            if css_class == "title":
                self._field = "title"
            elif css_class == "game-genre":
                self._field = "genre"
            else:
                self._field = None
            # end if
        # end if
    # end def handle_starttag

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2":
            self._in_h2 = False
            heading = "".join(self._h2_text).strip()
            self._current_month = _parse_month_heading(heading)
        elif tag == "p":
            self._field = None
        elif tag == "div" and self._in_card:
            self._in_card = False
            title = "".join(self._title_parts).strip()
            genre = "".join(self._genre_parts).strip()
            if self._current_month and title and self._href:
                self.months.setdefault(self._current_month, []).append(
                    MirrorEntry(title=title, genre=genre, url=self._href)
                )
            # end if
        # end if
    # end def handle_endtag

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_text.append(data)
        elif self._in_card and self._field == "title":
            self._title_parts.append(data)
        elif self._in_card and self._field == "genre":
            self._genre_parts.append(data)
        # end if
    # end def handle_data

# end class _DangarbriParser


def _parse_month_heading(heading: str) -> str | None:
    match = re.match(r"([A-Za-z]+)\s+(\d{4})\s+Games", heading)
    if not match:
        return None
    # end if
    month_name, year = match.group(1).lower(), match.group(2)
    month_number = MONTHS.get(month_name)
    if month_number is None:
        return None
    # end if
    return f"{year}-{month_number:02d}"
# end def _parse_month_heading


def _fix_title_casing(title: str) -> str:
    return ROMAN_TOKEN_RE.sub(lambda match: match.group(0).upper(), title)
# end def _fix_title_casing


def _month_slug(month_key: str) -> str:
    year, month_number = month_key.split("-")
    for name, number in MONTHS.items():
        if number == int(month_number):
            return f"{name}-{year}"
        # end if
    # end for
    raise ValueError(f"unknown month key: {month_key}")
# end def _month_slug


def _month_range(start: str, end: str) -> list[str]:
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    keys: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        keys.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
        # end if
    # end while
    return keys
# end def _month_range


def _non_interactive_choose(*_args: object) -> None:
    return None
# end def _non_interactive_choose


def backfill_month(
    month_key: str,
    entries: list[MirrorEntry],
    client: HumbleHttpClient,
    *,
    dry_run: bool,
) -> None:
    list_path = LISTS_ROOT / "humblebundle/choice" / f"{month_key}.yml"
    included = [entry for entry in entries if entry.genre]
    excluded = [entry for entry in entries if not entry.genre]
    if not included:
        print(f"{month_key}: no games found, skipping")
        return
    # end if

    draft_games = [
        {"name": _fix_title_casing(entry.title), "ids": []} for entry in included
    ]

    def _throttled_fetch(url: str) -> str:
        # Steam's search endpoint rate-limits aggressively; space out lookups
        # rather than hammering it once per game across many months.
        time.sleep(0.6)
        return client.fetch(url)
    # end def _throttled_fetch

    resolver = StorefrontResolver(_throttled_fetch, _non_interactive_choose)
    completed, unresolved = complete_game_list(
        {"schema": 1, "name": month_key, "games": draft_games},
        ("steam",),
        resolver,
        _non_interactive_choose,
        "blank",
    )

    games = [Game(name=game["name"], ids=game["ids"]) for game in completed["games"]]

    if dry_run:
        print(f"{month_key}: {len(games)} games, {len(unresolved)} unresolved (dry run)")
        for title in unresolved:
            print(f"  unresolved: {title}", file=sys.stderr)
        # end for
        return
    # end if

    archive_directory = ARCHIVE_ROOT / "humblebundle/choice" / month_key
    metadata_path = archive_directory / "metadata.json"
    source_path = archive_directory / "source.json"
    crawled_at = datetime.now(UTC).isoformat()

    source_payload = {
        "source": DANGARBRI_URL,
        "crawled": crawled_at,
        "month": month_key,
        "games": [entry._asdict() for entry in included],
        "excluded": [entry._asdict() for entry in excluded],
    }
    metadata_payload = {
        "source": DANGARBRI_URL,
        "crawled": crawled_at,
        "month": month_key,
        "games": [
            {"name": game.name, "ids": game.ids, "url": entry.url}
            for game, entry in zip(games, included, strict=True)
        ],
        "excluded": [entry._asdict() for entry in excluded],
    }
    atomic_write(metadata_path, dump_json(metadata_payload))
    atomic_write(source_path, dump_json(source_payload))

    references = [
        Reference(name="Humble Bundle offer", url=f"https://www.humblebundle.com/membership/{_month_slug(month_key)}"),
        Reference(name="Backfill source", url=DANGARBRI_URL),
        Reference(name="Crawl metadata", path=metadata_path.relative_to(list_path.parent, walk_up=True).as_posix()),
        Reference(name="Crawl source", path=source_path.relative_to(list_path.parent, walk_up=True).as_posix()),
    ]
    for entry in included:
        references.append(Reference(name=f"{_fix_title_casing(entry.title)} page", url=entry.url))
    # end for

    game_list = GameList(
        schema=1,
        name=f"{_month_slug(month_key).replace('-', ' ').title()} Humble Choice",
        references=references,
        games=games,
    )
    atomic_write(list_path, render_game_list_yaml(game_list, list_path, REPO_ROOT))
    print(f"{month_key}: wrote {list_path.relative_to(REPO_ROOT)} ({len(games)} games, {len(unresolved)} unresolved)")
    for title in unresolved:
        print(f"  unresolved: {title}", file=sys.stderr)
    # end for
# end def backfill_month


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="process every missing month found on the page")
    parser.add_argument("--month", action="append", default=[], metavar="YYYY-MM", help="process only this month (repeatable)")
    parser.add_argument("--from", dest="range_from", metavar="YYYY-MM", help="start of an inclusive month range")
    parser.add_argument("--to", dest="range_to", metavar="YYYY-MM", help="end of an inclusive month range")
    parser.add_argument("--refresh", action="store_true", help="also rewrite months that already have a list file")
    parser.add_argument("--dry-run", action="store_true", help="parse and resolve but do not write any files")
    args = parser.parse_args()

    if not args.all and not args.month and not (args.range_from and args.range_to):
        parser.error("pass --all, --month, or --from/--to")
    # end if

    client = HumbleHttpClient(attempts=5)
    try:
        html = client.fetch(DANGARBRI_URL)
    except HumbleCrawlError as error:
        print(str(error), file=sys.stderr)
        client.close()
        return 1
    # end try

    parser_state = _DangarbriParser()
    parser_state.feed(html)
    mirrored_months = parser_state.months

    if args.all:
        selected = sorted(mirrored_months)
    elif args.range_from and args.range_to:
        selected = [key for key in _month_range(args.range_from, args.range_to) if key in mirrored_months]
    else:
        selected = list(dict.fromkeys(args.month))
    # end if

    for month_key in selected:
        if not MONTH_KEY_RE.match(month_key):
            print(f"skipping invalid month key: {month_key}", file=sys.stderr)
            continue
        # end if
        entries = mirrored_months.get(month_key)
        if entries is None:
            print(f"{month_key}: not found on {DANGARBRI_URL}, skipping")
            continue
        # end if
        list_path = LISTS_ROOT / "humblebundle/choice" / f"{month_key}.yml"
        if list_path.exists() and not args.refresh:
            print(f"{month_key}: {list_path.relative_to(REPO_ROOT)} already exists, skipping")
            continue
        # end if
        try:
            backfill_month(month_key, entries, client, dry_run=args.dry_run)
        except HumbleCrawlError as error:
            print(f"{month_key}: {error}, skipping", file=sys.stderr)
        # end try
    # end for

    client.close()
    return 0
# end def main


if __name__ == "__main__":
    raise SystemExit(main())
# end if
