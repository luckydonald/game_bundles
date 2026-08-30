from __future__ import annotations

from game_collections.sources.storefronts import (
    is_known_store_url,
    match_store,
    parse_store_identity,
    product_url,
    qualified_ids_from_urls,
)


def test_match_store_recognizes_both_epic_hosts() -> None:
    assert match_store("https://store.epicgames.com/en-US/p/fortnite") == "epic"
    assert match_store("https://www.epicgames.com/store/p/cyberpunk-2077") == "epic"
# end def test_match_store_recognizes_both_epic_hosts


def test_match_store_unknown_host_returns_none() -> None:
    assert match_store("https://example.com/app/440") is None
# end def test_match_store_unknown_host_returns_none


def test_product_url_round_trips_through_parse_store_identity() -> None:
    for provider, value in [
        ("steam", "440"),
        ("gog", "some-slug"),
        ("epic", "some-slug"),
        ("ubisoft", "some-slug"),
        ("humble", "some-slug"),
    ]:
        url = product_url(provider, value)
        assert url is not None
        assert parse_store_identity(provider, url) == f"{provider}:{value}"
    # end for
# end def test_product_url_round_trips_through_parse_store_identity


def test_parse_store_identity_accepts_steam_bundle_url() -> None:
    url = "https://store.steampowered.com/bundle/46228/Forgive_Me_Father_2_Deluxe_Edition/"
    assert parse_store_identity("steam", url) == "steam:bundle/46228"
# end def test_parse_store_identity_accepts_steam_bundle_url


def test_product_url_round_trips_steam_bundle_identity() -> None:
    url = product_url("steam", "bundle/46228")
    assert url == "https://store.steampowered.com/bundle/46228"
    assert parse_store_identity("steam", url) == "steam:bundle/46228"
# end def test_product_url_round_trips_steam_bundle_identity


def test_product_url_unknown_provider_returns_none() -> None:
    assert product_url("unresolved", "whatever") is None
    assert product_url("isthereanydeal", "whatever") is None
# end def test_product_url_unknown_provider_returns_none


def test_qualified_ids_from_urls_resolves_known_stores_and_skips_unknown() -> None:
    urls = [
        "https://store.steampowered.com/app/440/",
        "https://apps.microsoft.com/detail/9n0h62kz3bxv?hl=en-US&gl=DE",
        "https://www.2game.com/de-de/products/diablo-iv-standard-edition-microsoft?ref=itad",
        "https://eu.shop.battle.net/login/oauth2/code/storefront",
    ]
    assert qualified_ids_from_urls(urls) == [
        "steam:440",
        "microsoft:9n0h62kz3bxv",
        "2game:diablo-iv-standard-edition-microsoft",
    ]
# end def test_qualified_ids_from_urls_resolves_known_stores_and_skips_unknown


def test_qualified_ids_from_urls_dedupes() -> None:
    urls = ["https://store.steampowered.com/app/440/", "https://store.steampowered.com/app/440/Team_Fortress/"]
    assert qualified_ids_from_urls(urls) == ["steam:440"]
# end def test_qualified_ids_from_urls_dedupes


def test_is_known_store_url() -> None:
    assert is_known_store_url("https://apps.microsoft.com/detail/9n0h62kz3bxv") is True
    assert is_known_store_url("https://eu.shop.battle.net/login/oauth2/code/storefront") is False
# end def test_is_known_store_url
