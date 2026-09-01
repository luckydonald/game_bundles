from __future__ import annotations

from game_collections.sources.humblebundle.steamdb import (
    STEAMDB_SEARCH_URL,
    parse_steamdb_results,
    parse_steamdb_sub_apps,
)


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


# Trimmed from a real steamdb.info search results row (confirmed live for
# q=Steelrising+Bastille+Edition): the highlighted-match <mark> spans are
# nested inside the name-column link, same as the ID-column's own numeric text.
_SUB_RESULT_ROW = """
<tbody><tr class="package" data-subid="729916">
<td class="dt-type-numeric"><a href="/sub/729916/">729916</a></td>
<td class="applogo dt-type-numeric" data-sort="-1">
<a href="/sub/729916/">
<img src="/static/img/applogo.svg" alt="">
</a>
</td>
<td>
<a href="/sub/729916/"><mark>Steelrising</mark> - <mark>Bastille</mark> <mark>Edition</mark></a>
<i class="stype">Package</i>
</td>
</tr></tbody>
"""


def test_parse_steamdb_results_includes_sub_rows() -> None:
    results = parse_steamdb_results(_SUB_RESULT_ROW)

    assert results == [("sub/729916", "Steelrising - Bastille Edition")]
# end def test_parse_steamdb_results_includes_sub_rows


# Trimmed from the real steamdb.info/sub/729916/ page's "Apps in this package" table.
_SUB_APPS_PAGE = """
<table>
<tbody>
<tr class="app" data-appid="2021370">
<td><a href="/app/2021370/">2021370</a></td>
<td>DLC</td>
<td>Steelrising - Discus Chain</td>
<td>...</td><td>...</td><td>...</td>
</tr><tr class="app" data-appid="2004261">
<td><a href="/app/2004261/">2004261</a></td>
<td>DLC</td>
<td>Steelrising - Cagliostro's Secrets</td>
<td>...</td><td>...</td><td>...</td>
</tr><tr class="app" data-appid="1283400">
<td><a href="/app/1283400/">1283400</a></td>
<td>Game</td>
<td>Steelrising</td>
<td>...</td><td>...</td><td>...</td>
</tr></tbody>
</table>
"""


def test_parse_steamdb_sub_apps_extracts_appid_and_name() -> None:
    apps = parse_steamdb_sub_apps(_SUB_APPS_PAGE)

    assert apps == [
        (2021370, "Steelrising - Discus Chain"),
        (2004261, "Steelrising - Cagliostro's Secrets"),
        (1283400, "Steelrising"),
    ]
# end def test_parse_steamdb_sub_apps_extracts_appid_and_name


def test_parse_steamdb_sub_apps_returns_empty_for_no_rows() -> None:
    assert parse_steamdb_sub_apps("<table><tbody></tbody></table>") == []
# end def test_parse_steamdb_sub_apps_returns_empty_for_no_rows
