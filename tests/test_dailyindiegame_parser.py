from __future__ import annotations

from datetime import UTC, datetime

from game_collections.sources.dailyindiegame.parser import (
    DigParseError,
    parse_bundle_index_page,
    parse_bundle_page,
    parse_game_listing_page,
)


CRAWLED = datetime(2026, 7, 12, tzinfo=UTC)

BUNDLE_URL = "https://www.dailyindiegame.com/site_weeklybundle_2351.html"


def _bundle_page(title: str = "DIG Bundle 2351 - ADULT") -> str:
    return f"""
    <table><tr><td><span class="DIG-contentOrangeBIG">{title}</span></td></tr></table>
    <div id="countdown">Bundle ends in 20 days : 03 : 09 : 13</div>
    <table><tr><td>
    9 awesome STEAM games , worth a total of $105.91. Grab them now for only $0.99 and save 100% ($104.92)
    </td></tr></table>
    <table><tr>
    <td>The Office: Dirty Affairs<br><br>
    <a href="https://store.steampowered.com/app/4543360">view on STEAM</a><br><br>
    <a href="site_gamelisting_4543360.html"></a></td>
    <td>Hentai Jigsaw Puzzle Collection<br><br>
    <a href="https://store.steampowered.com/app/2248470">view on STEAM</a><br><br>
    <a href="site_gamelisting_2248470.html"></a></td>
    </tr></table>
    """
# end def _bundle_page


def test_bundle_index_returns_distinct_numbers_in_order() -> None:
    html = """
    <table><tr><td>
    <a href="site_weeklybundle_2351.html"><img src="a.png"></a>
    <a href="site_weeklybundle_2350.html"><img src="b.png"></a>
    <a href="site_weeklybundle_2351.html"><img src="c.png"></a>
    <a href="site_content_bundles.html">not a bundle</a>
    </td></tr></table>
    """

    assert parse_bundle_index_page(html) == ["2351", "2350"]
# end def test_bundle_index_returns_distinct_numbers_in_order


def test_bundle_index_requires_at_least_one_link() -> None:
    try:
        parse_bundle_index_page("<html></html>")
    except DigParseError:
        return
    # end try
    raise AssertionError("expected DigParseError")
# end def test_bundle_index_requires_at_least_one_link


def test_bundle_page_normalizes_metadata_adult_flag_and_games() -> None:
    archive, source = parse_bundle_page(_bundle_page(), BUNDLE_URL, CRAWLED)

    assert archive.machine_name == "2351"
    assert archive.name == "DIG Bundle 2351 - ADULT"
    assert archive.is_adult is True
    assert archive.game_count == 2
    assert archive.total_value.value == 105.91
    assert archive.bundle_price.value == 0.99
    assert archive.savings_percent == 100
    assert archive.savings_amount.value == 104.92
    assert archive.dates.crawled == CRAWLED
    assert archive.dates.end == datetime(2026, 8, 1, 3, 9, 13, tzinfo=UTC)
    assert [(item.title, item.ids) for item in archive.items] == [
        ("The Office: Dirty Affairs", ["steam:4543360"]),
        ("Hentai Jigsaw Puzzle Collection", ["steam:2248470"]),
    ]
    assert source["games"] == [
        {"title": "The Office: Dirty Affairs", "steam_id": "4543360"},
        {"title": "Hentai Jigsaw Puzzle Collection", "steam_id": "2248470"},
    ]
# end def test_bundle_page_normalizes_metadata_adult_flag_and_games


def test_bundle_page_without_adult_suffix_is_not_flagged() -> None:
    archive, _source = parse_bundle_page(
        _bundle_page(title="DIG Bundle 2200"), BUNDLE_URL, CRAWLED
    )

    assert archive.name == "DIG Bundle 2200"
    assert archive.is_adult is False
# end def test_bundle_page_without_adult_suffix_is_not_flagged


def test_bundle_page_requires_a_title() -> None:
    try:
        parse_bundle_page("<html>no title here</html>", BUNDLE_URL, CRAWLED)
    except DigParseError:
        return
    # end try
    raise AssertionError("expected DigParseError")
# end def test_bundle_page_requires_a_title


def test_game_listing_page_extracts_price_region_description_and_cover() -> None:
    html = """
    <table><tr><td>The Office: Dirty Affairs $7.99 ( $7.99 ) You save: $0.00 (0%)Region: WORLDWIDE
    VIEW STEAM PAGE Step into the world of high stakes corporate ambition.
    <img src="dig3-images-steam/4543360.jpg"></td></tr></table>
    """

    result = parse_game_listing_page(html, "https://www.dailyindiegame.com/site_gamelisting_4543360.html")

    assert result["individual_price"].value == 7.99
    assert result["region"] == "WORLDWIDE"
    assert result["description"] == "Step into the world of high stakes corporate ambition."
    assert result["cover_art_url"] == "https://www.dailyindiegame.com/dig3-images-steam/4543360.jpg"
# end def test_game_listing_page_extracts_price_region_description_and_cover
