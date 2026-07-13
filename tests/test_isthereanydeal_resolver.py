from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from game_collections.sources.isthereanydeal.resolver import (
    ItadGameResolution,
    UNRESOLVED_PREFIX,
    parse_unresolved_marker,
    resolve_game,
    resolve_game_with_aliases,
    resolve_isthereanydeal_markers,
    write_itad_game_archive,
)


CRAWLED = datetime(2026, 7, 13, tzinfo=UTC)


def _detail_html(gid: str, title: str, appid: int | None) -> str:
    payload = {"game": {"id": gid, "slug": "unused", "title": title}, "detail": {"appid": appid}}
    return f"<html><script>var page = {json.dumps(['Game', payload])};</script></html>"
# end def _detail_html


def test_parse_unresolved_marker_matches() -> None:
    assert parse_unresolved_marker(f"{UNRESOLVED_PREFIX}2126:wildstar") == (2126, "wildstar")
# end def test_parse_unresolved_marker_matches


def test_parse_unresolved_marker_rejects_other_values() -> None:
    assert parse_unresolved_marker("steam:440") is None
    assert parse_unresolved_marker("unresolved:store:steam:foo") is None
# end def test_parse_unresolved_marker_rejects_other_values


def test_resolve_game_appid_only() -> None:
    html = _detail_html("gid-1", "Sample Game", 440)
    resolution = resolve_game(
        "sample-game",
        fetch_detail_page=lambda _url: html,
        fetch_deals=lambda _gid: {"deals": []},
        resolve_redirect=lambda url: url,
        crawled=CRAWLED,
    )
    assert resolution.archive.appid == 440
    assert resolution.archive.ids == ["steam:440", "isthereanydeal:sample-game"]
# end def test_resolve_game_appid_only


def test_resolve_game_deals_only() -> None:
    html = _detail_html("gid-2", "No Appid Game", None)
    deals_payload = {"deals": [{"shop": 35, "url": "https://itad.link/abc/"}]}

    def resolve_redirect(url: str) -> str:
        assert url == "https://itad.link/abc/"
        return "https://www.gog.com/en/game/no_appid_game"
    # end def resolve_redirect

    resolution = resolve_game(
        "no-appid-game",
        fetch_detail_page=lambda _url: html,
        fetch_deals=lambda _gid: deals_payload,
        resolve_redirect=resolve_redirect,
        crawled=CRAWLED,
    )
    assert resolution.archive.appid is None
    assert resolution.archive.ids == ["gog:no_appid_game", "isthereanydeal:no-appid-game"]
    assert resolution.source["deals_resolved"] == [
        {"shop": 35, "url": "https://itad.link/abc/", "url_resolved": "https://www.gog.com/en/game/no_appid_game"}
    ]
# end def test_resolve_game_deals_only


def test_resolve_game_no_match_keeps_only_own_id() -> None:
    html = _detail_html("gid-3", "Untraceable Game", None)
    deals_payload = {"deals": [{"shop": 4, "url": "https://itad.link/xyz/"}]}
    resolution = resolve_game(
        "untraceable-game",
        fetch_detail_page=lambda _url: html,
        fetch_deals=lambda _gid: deals_payload,
        resolve_redirect=lambda _url: "https://eu.shop.battle.net/login/oauth2/code/storefront",
        crawled=CRAWLED,
    )
    assert resolution.archive.ids == ["isthereanydeal:untraceable-game"]
# end def test_resolve_game_no_match_keeps_only_own_id


def test_resolve_game_with_aliases_merges_group_ids() -> None:
    htmls = {
        "pinball-fx-my-little-pony-pinball": _detail_html("gid-steam", "Pinball FX - MLP Pinball", 2351841),
        "my-little-pony-pinball": _detail_html("gid-epic", "MLP Pinball", None),
    }

    def resolve_one(slug: str) -> ItadGameResolution:
        return resolve_game(
            slug,
            fetch_detail_page=lambda _url, slug=slug: htmls[slug],
            fetch_deals=lambda _gid: {"deals": []},
            resolve_redirect=lambda url: url,
            crawled=CRAWLED,
        )
    # end def resolve_one

    alias_groups = {
        "pinball-fx-my-little-pony-pinball": frozenset(
            {"pinball-fx-my-little-pony-pinball", "my-little-pony-pinball"}
        ),
        "my-little-pony-pinball": frozenset({"pinball-fx-my-little-pony-pinball", "my-little-pony-pinball"}),
    }
    resolution = resolve_game_with_aliases("my-little-pony-pinball", alias_groups, resolve_one)
    assert resolution.archive.slug == "my-little-pony-pinball"
    assert resolution.archive.appid is None
    assert set(resolution.archive.ids) == {
        "isthereanydeal:my-little-pony-pinball",
        "steam:2351841",
        "isthereanydeal:pinball-fx-my-little-pony-pinball",
    }
# end def test_resolve_game_with_aliases_merges_group_ids


def test_resolve_game_with_aliases_no_group_returns_own_resolution() -> None:
    html = _detail_html("gid-1", "Sample Game", 440)

    def resolve_one(slug: str) -> ItadGameResolution:
        return resolve_game(
            slug,
            fetch_detail_page=lambda _url: html,
            fetch_deals=lambda _gid: {"deals": []},
            resolve_redirect=lambda url: url,
            crawled=CRAWLED,
        )
    # end def resolve_one

    resolution = resolve_game_with_aliases("sample-game", {}, resolve_one)
    assert resolution.archive.ids == ["steam:440", "isthereanydeal:sample-game"]
# end def test_resolve_game_with_aliases_no_group_returns_own_resolution


def test_resolve_isthereanydeal_markers_strips_solved_and_merges_ids() -> None:
    current = ["unresolved:source:isthereanydeal:2126:wildstar", "some:other-id"]

    def resolve(slug: str) -> ItadGameResolution:
        assert slug == "wildstar"
        return ItadGameResolution(
            archive=resolve_game(
                slug,
                fetch_detail_page=lambda _url: _detail_html("gid", "WildStar", 376870),
                fetch_deals=lambda _gid: {"deals": []},
                resolve_redirect=lambda url: url,
                crawled=CRAWLED,
            ).archive,
            source={},
        )
    # end def resolve

    result = resolve_isthereanydeal_markers(current, resolve)
    assert "unresolved:source:isthereanydeal:2126:wildstar" not in result
    assert "steam:376870" in result
    assert "isthereanydeal:wildstar" in result
    assert "some:other-id" in result
# end def test_resolve_isthereanydeal_markers_strips_solved_and_merges_ids


def test_resolve_isthereanydeal_markers_keeps_marker_when_unsolved() -> None:
    current = ["unresolved:source:isthereanydeal:1:untraceable-game"]

    def resolve(slug: str) -> ItadGameResolution:
        return resolve_game(
            slug,
            fetch_detail_page=lambda _url: _detail_html("gid", "Untraceable", None),
            fetch_deals=lambda _gid: {"deals": []},
            resolve_redirect=lambda url: url,
            crawled=CRAWLED,
        )
    # end def resolve

    result = resolve_isthereanydeal_markers(current, resolve)
    assert "unresolved:source:isthereanydeal:1:untraceable-game" in result
    assert "isthereanydeal:untraceable-game" in result
# end def test_resolve_isthereanydeal_markers_keeps_marker_when_unsolved


def test_write_itad_game_archive_round_trip(tmp_path: Path) -> None:
    resolution = resolve_game(
        "sample-game",
        fetch_detail_page=lambda _url: _detail_html("gid", "Sample Game", 440),
        fetch_deals=lambda _gid: {"deals": []},
        resolve_redirect=lambda url: url,
        crawled=CRAWLED,
    )
    metadata_path, source_path = write_itad_game_archive(resolution, tmp_path)
    assert metadata_path == tmp_path / "isthereanydeal/game/sample-game/metadata.json"
    assert source_path == tmp_path / "isthereanydeal/game/sample-game/source.json"
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["slug"] == "sample-game"
    assert json.loads(source_path.read_text(encoding="utf-8"))["page"]["game"]["title"] == "Sample Game"
# end def test_write_itad_game_archive_round_trip
