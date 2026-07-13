"""Resolve `unresolved:source:isthereanydeal:*` markers via ITAD's per-game detail page."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from game_collections.sources.common import atomic_write, dump_json
from game_collections.sources.isthereanydeal.models import ItadDates, ItadGameArchive
from game_collections.sources.isthereanydeal.parser import parse_game_detail_json
from game_collections.sources.storefronts import qualified_ids_from_urls


UNRESOLVED_PREFIX = "unresolved:source:isthereanydeal:"
_UNRESOLVED_PATTERN = re.compile(rf"^{re.escape(UNRESOLVED_PREFIX)}(\d+):(.+)$")

GAME_DETAIL_URL = "https://isthereanydeal.com/game/{slug}/info/"

FetchDetailPage = Callable[[str], str]
FetchDeals = Callable[[str], dict[str, Any]]
ResolveRedirect = Callable[[str], str]


def parse_unresolved_marker(value: str) -> tuple[int, str] | None:
    """Return `(bundle_id, slug)` from an ITAD unresolved marker, or `None` if it isn't one."""
    match = _UNRESOLVED_PATTERN.match(value)
    if not match:
        return None
    # end if
    return int(match.group(1)), match.group(2)
# end def parse_unresolved_marker


@dataclass(frozen=True, slots=True)
class ItadGameResolution:
    """One resolved ITAD game, paired with its raw payloads for archiving."""

    archive: ItadGameArchive
    source: dict[str, Any]

# end class ItadGameResolution


def _deal_urls(
    slug: str,
    gid: str,
    fetch_deals: FetchDeals,
    resolve_redirect: ResolveRedirect,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch `deals` for `gid` and resolve every deal's redirect to its real URL."""
    deals_payload = fetch_deals(gid)
    deals_raw = deals_payload.get("deals")
    resolved: list[dict[str, Any]] = []
    for deal in deals_raw if isinstance(deals_raw, list) else []:
        if not isinstance(deal, dict):
            continue
        # end if
        url = deal.get("url")
        if not isinstance(url, str) or not url:
            continue
        # end if
        resolved_url = resolve_redirect(url)
        resolved.append({"shop": deal.get("shop"), "url": url, "url_resolved": resolved_url})
    # end for
    return deals_payload, resolved
# end def _deal_urls


def resolve_game(
    slug: str,
    fetch_detail_page: FetchDetailPage,
    fetch_deals: FetchDeals,
    resolve_redirect: ResolveRedirect,
    crawled: datetime,
) -> ItadGameResolution:
    """Resolve one ITAD game slug into an `ItadGameArchive`, using its own detail page and deals.

    Always includes `isthereanydeal:<slug>` in the resulting `ids`, plus
    `steam:<appid>` when the detail page has one, plus every other
    storefront resolved from the game's `deals` (see
    `sources.storefronts.qualified_ids_from_urls` - shops with no verified
    URL-parsing rule yet are silently skipped there, not guessed).
    """
    url = GAME_DETAIL_URL.format(slug=slug)
    detail = parse_game_detail_json(fetch_detail_page(url), slug)
    deals_payload, deals_resolved = _deal_urls(slug, detail.gid, fetch_deals, resolve_redirect)

    ids = qualified_ids_from_urls([entry["url_resolved"] for entry in deals_resolved])
    if detail.appid is not None:
        ids = [f"steam:{detail.appid}", *[value for value in ids if value != f"steam:{detail.appid}"]]
    # end if
    ids.append(f"isthereanydeal:{slug}")
    ids = list(dict.fromkeys(ids))

    archive = ItadGameArchive(
        schema=1,
        slug=slug,
        title=detail.title,
        appid=detail.appid,
        ids=ids,
        url=url,
        dates=ItadDates(start=None, expiry=None, crawled=crawled),
    )
    source = {"page": detail.payload, "deals": deals_payload, "deals_resolved": deals_resolved}
    return ItadGameResolution(archive=archive, source=source)
# end def resolve_game


def resolve_game_with_aliases(
    slug: str,
    alias_groups: dict[str, frozenset[str]],
    resolve_one: Callable[[str], ItadGameResolution],
) -> ItadGameResolution:
    """Resolve `slug`, merging in ids from every ITAD slug reviewed as the same real game.

    Each group member is still resolved (and archived) independently - each
    is a genuinely distinct ITAD entry - but the returned resolution's `ids`
    is the union of every member's ids, and its own metadata (title/appid/
    url) stays that of the originally requested `slug`.
    """
    group = alias_groups.get(slug, frozenset({slug}))
    own = resolve_one(slug)
    if group == frozenset({slug}):
        return own
    # end if
    merged_ids = list(own.archive.ids)
    for other_slug in sorted(group - {slug}):
        other = resolve_one(other_slug)
        for value in other.archive.ids:
            if value not in merged_ids:
                merged_ids.append(value)
            # end if
        # end for
    # end for
    return ItadGameResolution(archive=own.archive.model_copy(update={"ids": merged_ids}), source=own.source)
# end def resolve_game_with_aliases


def resolve_isthereanydeal_markers(
    current: list[str],
    resolve: Callable[[str], ItadGameResolution],
) -> list[str]:
    """Resolve every ITAD unresolved marker in `current`, merging in ids and dropping solved markers."""
    result = list(current)
    for value in current:
        parsed = parse_unresolved_marker(value)
        if parsed is None:
            continue
        # end if
        _bundle_id, slug = parsed
        resolution = resolve(slug)
        for new_id in resolution.archive.ids:
            if new_id not in result:
                result.append(new_id)
            # end if
        # end for
        solved = any(not new_id.startswith("isthereanydeal:") for new_id in resolution.archive.ids)
        if solved:
            result = [item for item in result if item != value]
        # end if
    # end for
    return result
# end def resolve_isthereanydeal_markers


def _archive_paths(archive_root: Path, slug: str) -> tuple[Path, Path]:
    directory = archive_root / "isthereanydeal/game" / slug
    return directory / "metadata.json", directory / "source.json"
# end def _archive_paths


def write_itad_game_archive(resolution: ItadGameResolution, archive_root: Path) -> tuple[Path, Path]:
    """Atomically write `archives/isthereanydeal/game/<slug>/{metadata.json,source.json}`."""
    metadata_path, source_path = _archive_paths(archive_root, resolution.archive.slug)
    atomic_write(metadata_path, dump_json(resolution.archive.model_dump(by_alias=True, mode="json")))
    atomic_write(source_path, dump_json(resolution.source))
    return metadata_path, source_path
# end def write_itad_game_archive
