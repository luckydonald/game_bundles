from __future__ import annotations

from game_collections.sources.humblebundle.steamdb import STEAMDB_SEARCH_URL, parse_steamdb_results


# Fixture markup mirrors a real steamdb.info search results table (confirmed
# live for q=GRIME): each row has an ID-column link whose own text is just the
# numeric appid, and a separate name-column link; the type marker for
# non-Game rows sits in its own sibling <i class="stype"> tag, never inside
# the name link's own text.
_RESULTS_PAGE = """
<table>
<tbody>
<tr>
<td class="dt-type-numeric"><a href="/app/1123050/">1123050</a></td>
<td class="applogo dt-type-numeric"></td>
<td><a href="/app/1123050/">GRIME</a></td>
</tr>
<tr>
<td class="dt-type-numeric"><a href="/app/1701310/">1701310</a></td>
<td class="applogo dt-type-numeric"></td>
<td><a href="/app/1701310/">GRIME - Soundtrack</a><i class="stype">Music</i></td>
</tr>
</tbody>
</table>
"""


def test_parse_steamdb_results_extracts_title_without_type_suffix() -> None:
    results = parse_steamdb_results(_RESULTS_PAGE)

    assert results == [
        ("1123050", "GRIME"),
        ("1701310", "GRIME - Soundtrack"),
    ]
# end def test_parse_steamdb_results_extracts_title_without_type_suffix


def test_parse_steamdb_results_ignores_store_page_link() -> None:
    page = """
    <a href="/app/42/">Sample Game</a>
    <a href="https://store.steampowered.com/app/42/?curator_clanid=1&utm_source=SteamDB">store page</a>
    """

    results = parse_steamdb_results(page)

    assert results == [("42", "Sample Game")]
# end def test_parse_steamdb_results_ignores_store_page_link


def test_parse_steamdb_results_dedupes_by_appid() -> None:
    page = """
    <a href="/app/42/">42</a>
    <a href="/app/42/">Sample Game</a>
    <a href="/app/42/">Sample Game Duplicate</a>
    """

    results = parse_steamdb_results(page)

    assert results == [("42", "Sample Game")]
# end def test_parse_steamdb_results_dedupes_by_appid


def test_steamdb_search_url_formats_query() -> None:
    assert STEAMDB_SEARCH_URL.format(query="GRIME") == "https://steamdb.info/search/?q=GRIME"
# end def test_steamdb_search_url_formats_query


def test_parse_steamdb_results_includes_bundle_rows() -> None:
    page = """
    <a href="/bundle/46228/">46228</a>
    <a href="/bundle/46228/">Forgive Me Father 2 Deluxe Edition</a>
    """

    results = parse_steamdb_results(page)

    assert results == [("bundle/46228", "Forgive Me Father 2 Deluxe Edition")]
# end def test_parse_steamdb_results_includes_bundle_rows
