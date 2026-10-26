from __future__ import annotations

from pathlib import Path

from game_collections.sources.fanatical.parser import FanaticalProduct
from game_collections.sources.fanatical.resolver import (
    FanaticalResolutionMap,
    load_resolution_map,
    resolve_product_ids,
    write_resolution_map,
)
from game_collections.sources.storefronts import StoreCandidate


def make_product(
    slug: str = "critter-cafe",
    title: str = "Critter Café",
    steam_app_id: int | None = None,
    product_type: str = "game",
    drm: tuple[str, ...] = ("steam",),
) -> FanaticalProduct:
    return FanaticalProduct(slug=slug, title=title, product_type=product_type, drm=drm, steam_app_id=steam_app_id)
# end def make_product


def candidate(title: str, app_id: int) -> StoreCandidate:
    return StoreCandidate(
        title=title, url=f"https://store.steampowered.com/app/{app_id}/", qualified_id=f"steam:{app_id}"
    )
# end def candidate


def empty_map() -> FanaticalResolutionMap:
    return FanaticalResolutionMap(schema=1, games={})
# end def empty_map


def no_search(_title: str) -> list[StoreCandidate]:
    raise AssertionError("must not search")
# end def no_search


def test_fanatical_steam_id_is_used_without_searching() -> None:
    ids = resolve_product_ids(make_product(steam_app_id=440), "b", empty_map(), no_search)

    assert ids == ["steam:440", "fanatical:critter-cafe"]
# end def test_fanatical_steam_id_is_used_without_searching


def test_unique_exact_title_match_resolves_and_is_cached() -> None:
    mapping = empty_map()
    searches: list[str] = []

    def search(title: str) -> list[StoreCandidate]:
        searches.append(title)
        return [candidate("Critter Cafe", 2367610), candidate("Critter Cafe Soundtrack", 1)]
    # end def search

    first = resolve_product_ids(make_product(), "b", mapping, search)
    second = resolve_product_ids(make_product(), "other-bundle", mapping, no_search)

    assert first == second == ["steam:2367610", "fanatical:critter-cafe"]
    assert searches == ["Critter Café"]
    assert mapping.games == {"critter-cafe": ["steam:2367610"]}
# end def test_unique_exact_title_match_resolves_and_is_cached


def test_ambiguous_or_missing_match_is_marked_unresolved_and_not_cached() -> None:
    mapping = empty_map()
    ambiguous = resolve_product_ids(
        make_product(title="Foo"), "b", mapping, lambda _t: [candidate("Foo", 1), candidate("Foo", 2)]
    )
    missing = resolve_product_ids(make_product(slug="bar", title="Bar"), "b", mapping, lambda _t: [])

    assert ambiguous == ["unresolved:source:fanatical:b:critter-cafe", "fanatical:critter-cafe"]
    assert missing == ["unresolved:source:fanatical:b:bar", "fanatical:bar"]
    assert mapping.games == {}
# end def test_ambiguous_or_missing_match_is_marked_unresolved_and_not_cached


def test_search_failures_are_logged_and_leave_the_product_unresolved() -> None:
    messages: list[str] = []

    def failing(_title: str) -> list[StoreCandidate]:
        raise OSError("offline")
    # end def failing

    ids = resolve_product_ids(make_product(), "b", empty_map(), failing, messages.append)

    assert ids[0].startswith("unresolved:source:fanatical:")
    assert any("offline" in message for message in messages)
# end def test_search_failures_are_logged_and_leave_the_product_unresolved


def test_books_and_non_steam_products_only_get_the_anchor_id() -> None:
    book = make_product(slug="a-book", product_type="book")
    course = make_product(slug="a-course", product_type="software", drm=("fanatical",))

    assert resolve_product_ids(book, "b", empty_map(), no_search) == ["fanatical:a-book"]
    assert resolve_product_ids(course, "b", empty_map(), no_search) == ["fanatical:a-course"]
# end def test_books_and_non_steam_products_only_get_the_anchor_id


def test_resolution_map_round_trips_sorted(tmp_path: Path) -> None:
    path = tmp_path / "ids.yml"
    mapping = FanaticalResolutionMap(schema=1, games={"b": ["steam:2"], "a": ["steam:1"]})

    write_resolution_map(path, mapping)

    assert path.read_text(encoding="utf-8").index("a:") < path.read_text(encoding="utf-8").index("b:")
    assert load_resolution_map(path).games == {"a": ["steam:1"], "b": ["steam:2"]}
    assert load_resolution_map(tmp_path / "missing.yml").games == {}
# end def test_resolution_map_round_trips_sorted
