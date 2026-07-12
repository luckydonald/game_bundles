from __future__ import annotations

import pytest

from game_collections.sources.isthereanydeal.parser import (
    ItadParseError,
    parse_bootstrap_page,
    parse_bundle_detail_page,
    parse_list_page,
    real_provider_slug,
    real_provider_url,
)


BOOTSTRAP_HTML = """
<html><script>
var g = {"country":"DE","currency":"EUR","user":{"id":"abc","token":"tok_abc123"},
"shops":{"61":["Steam",0],"35":["GOG",1],"36":["GreenManGaming",1]},"theme":{}};
</script></html>
"""


def test_parse_bootstrap_page_extracts_token_and_shops() -> None:
    token, shops = parse_bootstrap_page(BOOTSTRAP_HTML)
    assert token == "tok_abc123"
    assert shops == {61: "Steam", 35: "GOG", 36: "GreenManGaming"}
# end def test_parse_bootstrap_page_extracts_token_and_shops


def test_parse_bootstrap_page_missing_token_raises() -> None:
    with pytest.raises(ItadParseError):
        parse_bootstrap_page("<html>no token here</html>")
    # end with
# end def test_parse_bootstrap_page_missing_token_raises


def _list_entry(bundle_id: int = 16316, byob: bool = False, is_mature: bool = False) -> dict:
    return {
        "id": bundle_id,
        "title": "Metroidvania Madness",
        "page": {"id": 73, "name": "GreenManGaming", "shopId": 36},
        "url": (
            "https://greenmangaming.sjv.io/c/2545989/3298418/15105"
            "?u=https%3A%2F%2Fwww.greenmangamingbundles.com%2Fbundles%2Fmetroidvania-madness%2F"
        ),
        "isMature": is_mature,
        "isPending": False,
        "start": 1783715387,
        "expiry": 1785556800,
        "counts": {"games": 6, "media": 0, "waitlist": 0, "collection": 0, "comments": 0},
        "byob": byob,
        # Embedded ITAD-internal tier/game preview - present on the live API
        # but intentionally not modeled (see parser.py); must not break
        # validation.
        "tiers": [
            {
                "price": [800, "EUR"],
                "addon": False,
                "games": [
                    {
                        "id": "018d937f-13b7-711d-a4c1-9a03271721f9",
                        "slug": "some-itad-slug",
                        "title": "Some Game",
                        "type": 1,
                        "mature": False,
                        "assets": {"banner145": "https://assets.isthereanydeal.com/x/banner145.jpg"},
                        "drmfree": False,
                        "keys": [61],
                        "platforms": [1],
                        "note": None,
                    }
                ],
            }
        ],
    }
# end def _list_entry


def test_parse_list_page_validates_and_drops_tiers_preview() -> None:
    done, summaries = parse_list_page({"done": False, "data": [_list_entry()]})
    assert done is False
    assert len(summaries) == 1
    assert summaries[0].title == "Metroidvania Madness"
    assert summaries[0].page.name == "GreenManGaming"
    assert summaries[0].counts.games == 6
# end def test_parse_list_page_validates_and_drops_tiers_preview


def test_parse_list_page_missing_keys_raises() -> None:
    with pytest.raises(ItadParseError):
        parse_list_page({"data": []})
    # end with
# end def test_parse_list_page_missing_keys_raises


def test_parse_list_page_rejects_unknown_field() -> None:
    entry = _list_entry()
    entry["somethingNew"] = "unexpected"
    with pytest.raises(Exception):
        parse_list_page({"done": True, "data": [entry]})
    # end with
# end def test_parse_list_page_rejects_unknown_field


def test_real_provider_url_decodes_u_param() -> None:
    url = "https://greenmangaming.sjv.io/c/x?u=https%3A%2F%2Fwww.greenmangamingbundles.com%2Fbundles%2Ffoo%2F"
    assert real_provider_url(url) == "https://www.greenmangamingbundles.com/bundles/foo/"
# end def test_real_provider_url_decodes_u_param


def test_real_provider_url_decodes_ued_param_awin() -> None:
    url = (
        "https://www.awin1.com/cread.php?awinmid=118821&awinaffid=235265"
        "&ued=https%3A%2F%2Fwww.fanatical.com%2Fen%2Fpick-and-mix%2Ffoo"
    )
    assert real_provider_url(url) == "https://www.fanatical.com/en/pick-and-mix/foo"
# end def test_real_provider_url_decodes_ued_param_awin


def test_real_provider_url_falls_back_to_unwrapped_link() -> None:
    url = "https://www.indiegala.com/bundle/foo-bundle?ref=itad"
    assert real_provider_url(url) == url
# end def test_real_provider_url_falls_back_to_unwrapped_link


def test_real_provider_slug_prefers_non_numeric_segment() -> None:
    url = "https://www.indiegala.com/store/game/no-mans-sky-exclusive-bundle/26441?ref=itad"
    assert real_provider_slug(url) == "no-mans-sky-exclusive-bundle"
# end def test_real_provider_slug_prefers_non_numeric_segment


def _game_block(slug: str, title: str, appid: int | None) -> str:
    store_link = (
        f'<a href="https://store.steampowered.com/app/{appid}/" class="simple">reviews</a>'
        if appid is not None
        else ""
    )
    return f"""
    <div class="item svelte-16sk5um">
      <a href="/game/{slug}/info/" class="button svelte-16sk5um">
        <span class="game-title"><span class="pack svelte-11k8hw5"> </span> {title}</span>
      </a>
      <div class="reviews svelte-lul36k">{store_link}</div>
    </div>
    """
# end def _game_block


def _tier_block(name_suffix: str, price: str, games_html: str) -> str:
    return f"""
    <div class="tier-name svelte-1bcxd10"><div class="name svelte-1bcxd10">Tier 1</div> {name_suffix}</div>
    <div class="values svelte-1bcxd10">
      <div>Historical value</div>
      <div>Price</div> <div class="value__price svelte-1lak40z">{price}</div>
    </div>
    <div class="tier tier--cards svelte-1bcxd10">{games_html}</div>
    """
# end def _tier_block


def test_parse_bundle_detail_page_single_flat_tier() -> None:
    html = _tier_block("", "8,00 €", _game_block("grime", "GRIME", 1123050) + _game_block("islets", "Islets", 1669420))
    tiers = parse_bundle_detail_page(html, bundle_id=1, expected_game_count=2)
    assert len(tiers) == 1
    assert tiers[0].name == "Tier 1"
    assert tiers[0].item_count == 2
    assert tiers[0].price is not None
    assert tiers[0].price.value == 8.0
    ids = {item.slug: item.ids for item in tiers[0].items}
    assert ids["grime"] == ["steam:1123050"]
    assert ids["islets"] == ["steam:1669420"]
# end def test_parse_bundle_detail_page_single_flat_tier


def test_parse_bundle_detail_page_cumulative_named_tiers() -> None:
    bronze = _tier_block("2/0 Bronze", "8,00 €", _game_block("laika", "Laika", 1796220) + _game_block("bo", "Bo", 1614440))
    silver = _tier_block("2/0 Silver", "12,00 €", _game_block("grime", "GRIME", 1123050) + _game_block("islets", "Islets", 1669420))
    tiers = parse_bundle_detail_page(bronze + silver, bundle_id=2, expected_game_count=4)
    assert [tier.name for tier in tiers] == ["Bronze", "Silver"]
    assert [tier.item_count for tier in tiers] == [2, 4]
    # Silver is cumulative: it includes Bronze's games too.
    assert {item.slug for item in tiers[1].items} == {"laika", "bo", "grime", "islets"}
# end def test_parse_bundle_detail_page_cumulative_named_tiers


def test_parse_bundle_detail_page_unresolved_game_gets_fallback_id() -> None:
    html = _tier_block("", "3,50 €", _game_block("mystery-game", "Mystery Game", None))
    tiers = parse_bundle_detail_page(html, bundle_id=99, expected_game_count=1)
    assert tiers[0].items[0].ids == ["unresolved:source:isthereanydeal:99:mystery-game"]
# end def test_parse_bundle_detail_page_unresolved_game_gets_fallback_id


def test_parse_bundle_detail_page_byob_single_synthetic_tier() -> None:
    html = _tier_block("", "--", _game_block("a", "Game A", 111) + _game_block("b", "Game B", None))
    tiers = parse_bundle_detail_page(html, bundle_id=3, expected_game_count=2)
    assert len(tiers) == 1
    assert tiers[0].price is None
# end def test_parse_bundle_detail_page_byob_single_synthetic_tier


def test_parse_bundle_detail_page_skips_zero_item_addon_tier() -> None:
    main = _tier_block("3/0", "8,00 €", _game_block("a", "Game A", 111))
    addon = _tier_block("0/0 Add-on tier", "--", "")
    tiers = parse_bundle_detail_page(main + addon, bundle_id=4, expected_game_count=1)
    assert len(tiers) == 1
    assert tiers[0].name == "Tier 1"
# end def test_parse_bundle_detail_page_skips_zero_item_addon_tier


def test_parse_bundle_detail_page_no_games_raises() -> None:
    with pytest.raises(ItadParseError):
        parse_bundle_detail_page("<html>no games here</html>", bundle_id=5, expected_game_count=1)
    # end with
# end def test_parse_bundle_detail_page_no_games_raises


def test_parse_bundle_detail_page_count_mismatch_raises() -> None:
    html = _tier_block("", "8,00 €", _game_block("grime", "GRIME", 1123050))
    with pytest.raises(ItadParseError):
        parse_bundle_detail_page(html, bundle_id=6, expected_game_count=99)
    # end with
# end def test_parse_bundle_detail_page_count_mismatch_raises
