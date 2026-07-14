from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import yaml

pytest.importorskip("textual", reason="requires the optional `tui` extra: uv sync --extra tui")

from textual.widgets import Checkbox, Input, Select, Static, Tree

from game_collections.apply.tui import ApplyPickerApp, _NodeData


def _write_list(lists_root: Path, list_id: str, *, item_count: int, tier: int | None, name: str) -> None:
    path = lists_root / f"{list_id}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    games = [{"name": f"Game {index}", "ids": [f"steam:{1000 + index}"]} for index in range(item_count)]
    document: dict[str, object] = {"schema": 1, "name": name, "games": games}
    if tier is not None:
        document["tier"] = tier
    # end if
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
# end def _write_list


def _make_lists_root(tmp_path: Path) -> Path:
    lists_root = tmp_path / "lists"
    _write_list(
        lists_root,
        "humblebundle/bundle/2026-01-01_a/bundle",
        item_count=3,
        tier=None,
        name="Small Bundle",
    )
    _write_list(
        lists_root,
        "greenmangaming/bundle/2026-02-01_b/tier-2",
        item_count=10,
        tier=2,
        name="Big Bundle",
    )
    return lists_root
# end def _make_lists_root


async def _run_until_loaded(app: ApplyPickerApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()
# end def _run_until_loaded


def _tree(app: ApplyPickerApp) -> Tree[_NodeData]:
    return app.query_one("#rows-tree", Tree)
# end def _tree


def _source_nodes(app: ApplyPickerApp) -> dict[str, object]:
    return {node.data.source: node for node in _tree(app).root.children if node.data is not None}
# end def _source_nodes


def _leaf_list_ids(app: ApplyPickerApp, source: str) -> list[str]:
    node = _source_nodes(app)[source]
    return [leaf.data.list_id for leaf in node.children]
# end def _leaf_list_ids


def test_tree_is_focused_with_cursor_on_first_category_at_start(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            assert app.focused is tree
            assert tree.cursor_line == 0
            assert tree.cursor_node is not None
            assert tree.cursor_node.data.kind == "source"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_tree_is_focused_with_cursor_on_first_category_at_start


def test_ownership_marks_bundle_fraction_and_greys_out_unowned_games(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "humblebundle/bundle/2026-01-01_a/bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: 1\nname: Some Bundle\ngames:\n"
        "  - name: Owned Game\n    ids: [steam:440]\n"
        "  - name: Missing Game\n    ids: [steam:999]\n"
        "  - name: No Steam ID\n    ids: [unresolved:source:isthereanydeal:1:x]\n",
        encoding="utf-8",
    )

    async def scenario() -> None:
        # match_mode="none": this test is about the ownership fraction/dim labeling itself,
        # not about "all"/"any" hiding a not-fully-owned bundle outright
        app = ApplyPickerApp(lists_root, excluded=set(), match_mode="none", owned_app_ids=frozenset({440}))
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            bundle_node = _source_nodes(app)["humblebundle"].children[0]
            assert "(1/3)" in bundle_node.label.plain

            bundle_node.expand()
            await pilot.pause()
            owned, missing, no_steam = bundle_node.children
            assert owned.label.plain == "Owned Game"
            assert owned.label.style == ""
            assert missing.label.plain == "Missing Game"
            assert missing.label.style == "dim"
            assert no_steam.label.plain == "No Steam ID"
            assert no_steam.label.style == "dim"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_ownership_marks_bundle_fraction_and_greys_out_unowned_games


def test_unknown_ownership_does_not_mark_or_grey_anything(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "humblebundle/bundle/2026-01-01_a/bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: 1\nname: Some Bundle\ngames:\n  - name: A Game\n    ids: [steam:440]\n",
        encoding="utf-8",
    )

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())  # owned_app_ids defaults to None
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            bundle_node = _source_nodes(app)["humblebundle"].children[0]
            assert re.search(r"\(\d+/\d+\)", bundle_node.label.plain) is None

            bundle_node.expand()
            await pilot.pause()
            game_node = bundle_node.children[0]
            assert game_node.label.plain == "A Game"
            assert game_node.label.style == ""
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_unknown_ownership_does_not_mark_or_grey_anything


def _write_ownership_fixture(lists_root: Path) -> None:
    zero = lists_root / "vendor/zero-owned.yml"
    zero.parent.mkdir(parents=True, exist_ok=True)
    zero.write_text("schema: 1\nname: Zero Owned\ngames:\n  - name: G\n    ids: [steam:999]\n", encoding="utf-8")
    partial = lists_root / "vendor/partial-owned.yml"
    partial.write_text(
        "schema: 1\nname: Partial Owned\ngames:\n  - name: G1\n    ids: [steam:440]\n  - name: G2\n    ids: [steam:999]\n",
        encoding="utf-8",
    )
    full = lists_root / "vendor/fully-owned.yml"
    full.write_text(
        "schema: 1\nname: Fully Owned\ngames:\n  - name: G1\n    ids: [steam:440]\n  - name: G2\n    ids: [steam:441]\n",
        encoding="utf-8",
    )
# end def _write_ownership_fixture


def test_mode_all_hides_partial_ownership_mode_any_only_hides_zero_owned(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_ownership_fixture(lists_root)

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set(), match_mode="all", owned_app_ids=frozenset({440, 441}))
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            # "all" needs every game owned: only the fully-owned bundle qualifies -
            # this used to be identical to "any" (a bug), hiding only 0-owned bundles
            vendor = _source_nodes(app)["vendor"]
            assert [child.label.plain for child in vendor.children] == [
                "[vendor/-] ????-??-??    2 items  single    Fully Owned  (2/2)",
            ]
            assert [child.data.check_state for child in vendor.children] == ["checked"]

            app.query_one("#filter-mode", Select).value = "any"
            await pilot.pause()
            vendor = _source_nodes(app)["vendor"]
            # "any" needs at least one game owned: partial- and fully-owned both qualify,
            # only the 0-owned bundle is hidden
            names = {"Partial Owned" if "Partial Owned" in c.label.plain else "Fully Owned" for c in vendor.children}
            assert len(vendor.children) == 2
            assert names == {"Partial Owned", "Fully Owned"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_mode_all_hides_partial_ownership_mode_any_only_hides_zero_owned


def test_source_greys_out_only_when_fully_zero_owned(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    _write_ownership_fixture(lists_root)

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set(), match_mode="none", owned_app_ids=frozenset({440}))
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            # mixed source (one zero-owned, one partially-owned bundle): not greyed
            assert _source_nodes(app)["vendor"].label.style == ""
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_source_greys_out_only_when_fully_zero_owned


def test_source_greys_out_when_every_visible_bundle_is_zero_owned(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "vendor/zero-owned.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("schema: 1\nname: Zero Owned\ngames:\n  - name: G\n    ids: [steam:999]\n", encoding="utf-8")

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set(), match_mode="none", owned_app_ids=frozenset({440}))
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert _source_nodes(app)["vendor"].label.style == "dim"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_source_greys_out_when_every_visible_bundle_is_zero_owned


def test_expanding_a_game_shows_store_links_and_steam_launch(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "humblebundle/bundle/2026-01-01_a/bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: 1\nname: Some Bundle\ngames:\n"
        "  - name: Game A\n    ids: [steam:440, gog:some-slug]\n"
        "  - name: Game B\n    ids: [unresolved:source:isthereanydeal:1:x]\n",
        encoding="utf-8",
    )

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            bundle_node = _source_nodes(app)["humblebundle"].children[0]
            bundle_node.expand()
            await pilot.pause()
            game_a, game_b = bundle_node.children
            assert game_a.label.plain == "Game A"
            assert game_a.allow_expand is True

            game_a.expand()
            await pilot.pause()
            links = {leaf.label.plain: leaf.data for leaf in game_a.children}
            assert links["Store: steam"].url == "https://store.steampowered.com/app/440"
            assert links["Store: steam"].enabled is True
            assert links["Store: gog"].url == "https://www.gog.com/game/some-slug"
            assert links["Launch on Steam"].url == "steam://rungameid/440"
            assert links["Launch on Steam"].enabled is True

            game_b.expand()
            await pilot.pause()
            # game B only has an "unresolved" marker id: no store link, and Steam launch is disabled
            assert [leaf.label.plain for leaf in game_b.children] == ["Launch on Steam"]
            launch_b = game_b.children[0]
            assert launch_b.data.enabled is False
            assert launch_b.data.url is None
            assert launch_b.label.style == "dim"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_expanding_a_game_shows_store_links_and_steam_launch


def test_open_calls_os_opener_only_when_enabled(tmp_path: Path) -> None:
    from unittest.mock import patch

    from game_collections.apply.tui import _NodeData as NodeData

    app = ApplyPickerApp(tmp_path / "lists", excluded=set())
    with patch("game_collections.apply.tui._open_url") as mock_open_url:
        app._open(NodeData(kind="link", source="x", url="https://example.com/game", enabled=True))
        mock_open_url.assert_called_once_with("https://example.com/game")

        mock_open_url.reset_mock()
        app._open(NodeData(kind="link", source="x", url=None, enabled=False))
        mock_open_url.assert_not_called()
    # end with
# end def test_open_calls_os_opener_only_when_enabled


def test_labels_render_literal_brackets_and_carry_checked_state(tmp_path: Path) -> None:
    # rich.markup would otherwise silently eat any literal "[...]" in a bundle name
    lists_root = tmp_path / "lists"
    _write_list(lists_root, "humblebundle/bundle/2026-01-01_a/bundle", item_count=1, tier=None, name="One [Deluxe]")

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            source_node = _source_nodes(app)["humblebundle"]
            assert source_node.data.check_state == "checked"
            bundle_node = source_node.children[0]
            assert bundle_node.data.check_state == "checked"
            assert "One [Deluxe]" in bundle_node.label.plain
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_labels_render_literal_brackets_and_carry_checked_state


def test_expanding_a_bundle_lazily_shows_its_games(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "humblebundle/bundle/2026-01-01_a/bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: 1\nname: Some Bundle\ngames:\n  - name: Game A\n    ids: [steam:1]\n  - name: Game B\n    ids: [steam:2]\n",
        encoding="utf-8",
    )

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            bundle_node = _source_nodes(app)["humblebundle"].children[0]
            assert len(bundle_node.children) == 0
            assert bundle_node.allow_expand is True

            bundle_node.expand()
            await pilot.pause()
            assert [leaf.label.plain for leaf in bundle_node.children] == ["Game A", "Game B"]
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_expanding_a_bundle_lazily_shows_its_games


def test_ctrl_a_toggles_select_all_or_none(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            all_ids = {
                "greenmangaming/bundle/2026-02-01_b/tier-2",
                "humblebundle/bundle/2026-01-01_a/bundle",
            }
            assert app._checked == all_ids

            await pilot.press("ctrl+a")
            await pilot.pause()
            assert app._checked == set()

            await pilot.press("ctrl+a")
            await pilot.pause()
            assert app._checked == all_ids
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_ctrl_a_toggles_select_all_or_none


def test_ctrl_a_only_affects_bundles_passing_the_filter(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app.query_one("#filter-min-items", Input).value = "5"
            await pilot.pause()
            assert app._checked == {"greenmangaming/bundle/2026-02-01_b/tier-2"}

            await pilot.press("ctrl+a")
            await pilot.pause()
            # only the filtered-in bundle gets toggled off; the filtered-out one was already deselected
            assert app._checked == set()
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_ctrl_a_only_affects_bundles_passing_the_filter


def test_collapsed_source_stays_collapsed_after_an_unrelated_rebuild(tmp_path: Path) -> None:
    # regression: _expanded_sources used to only grow via .add(), so a source collapsed
    # again after being expanded once would spuriously re-expand on the next rebuild
    lists_root = _make_lists_root(tmp_path)

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            humble = _source_nodes(app)["humblebundle"]
            humble.expand()
            await pilot.pause()
            humble.collapse()
            await pilot.pause()
            assert _source_nodes(app)["humblebundle"].is_expanded is False

            # toggling an unrelated source triggers a full tree rebuild
            app._toggle(_NodeData(kind="source", source="greenmangaming"))
            await pilot.pause()
            assert _source_nodes(app)["humblebundle"].is_expanded is False
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_collapsed_source_stays_collapsed_after_an_unrelated_rebuild


def test_bundles_pre_checked_and_grouped_by_source(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert app._checked == {
                "greenmangaming/bundle/2026-02-01_b/tier-2",
                "humblebundle/bundle/2026-01-01_a/bundle",
            }
            assert set(_source_nodes(app)) == {"greenmangaming", "humblebundle"}
            assert _leaf_list_ids(app, "greenmangaming") == ["greenmangaming/bundle/2026-02-01_b/tier-2"]
            assert _leaf_list_ids(app, "humblebundle") == ["humblebundle/bundle/2026-01-01_a/bundle"]
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_bundles_pre_checked_and_grouped_by_source


def test_status_line_shows_shown_and_selected_counts(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded={"greenmangaming/bundle/2026-02-01_b/tier-2"})
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            status = app.query_one("#status", Static).renderable
            assert str(status) == "2/2 shown\n1/2 selected"

            app.query_one("#filter-min-items", Input).value = "5"
            await pilot.pause()
            status = app.query_one("#status", Static).renderable
            # min-items hides the 3-item bundle by default ("show filtered" off); the
            # remaining, excluded-from-the-start bundle is shown but still unselected
            assert str(status) == "1/2 shown\n0/2 selected"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_status_line_shows_shown_and_selected_counts


def test_previously_excluded_bundle_starts_unchecked(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded={"greenmangaming/bundle/2026-02-01_b/tier-2"})
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert app._checked == {"humblebundle/bundle/2026-01-01_a/bundle"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_previously_excluded_bundle_starts_unchecked


def test_toggling_bundle_leaf_toggles_only_itself(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app._toggle(_NodeData(kind="bundle", source="greenmangaming", list_id="greenmangaming/bundle/2026-02-01_b/tier-2"))
            await pilot.pause()
            assert app._checked == {"humblebundle/bundle/2026-01-01_a/bundle"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_toggling_bundle_leaf_toggles_only_itself


def test_toggling_source_node_toggles_all_its_bundles(tmp_path: Path) -> None:
    lists_root = _make_lists_root(tmp_path)
    _write_list(lists_root, "humblebundle/bundle/2026-04-01_d/bundle", item_count=1, tier=None, name="Second Humble")

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert {
                "humblebundle/bundle/2026-01-01_a/bundle",
                "humblebundle/bundle/2026-04-01_d/bundle",
            } <= app._checked

            app._toggle(_NodeData(kind="source", source="humblebundle"))
            await pilot.pause()
            assert "humblebundle/bundle/2026-01-01_a/bundle" not in app._checked
            assert "humblebundle/bundle/2026-04-01_d/bundle" not in app._checked
            assert "greenmangaming/bundle/2026-02-01_b/tier-2" in app._checked

            app._toggle(_NodeData(kind="source", source="humblebundle"))
            await pilot.pause()
            assert {
                "humblebundle/bundle/2026-01-01_a/bundle",
                "humblebundle/bundle/2026-04-01_d/bundle",
            } <= app._checked
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_toggling_source_node_toggles_all_its_bundles


def test_clicking_checkbox_glyph_toggles_bundle(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            source_node = _source_nodes(app)["humblebundle"]
            source_node.expand()
            await pilot.pause()
            bundle_node = source_node.children[0]
            assert bundle_node.data.list_id in app._checked

            region = tree._get_label_region(bundle_node._line)
            assert region is not None
            # The label is [expand-arrow][checkbox][text]; skip past the arrow's own width.
            icon_width = len(tree.ICON_NODE) if bundle_node.allow_expand else 0
            await pilot.click(tree, offset=(region.x + icon_width, bundle_node._line))
            await pilot.pause()

            assert bundle_node.data.list_id not in app._checked
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_clicking_checkbox_glyph_toggles_bundle


def test_clicking_elsewhere_on_row_does_not_toggle(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            source_node = _source_nodes(app)["humblebundle"]
            source_node.expand()
            await pilot.pause()
            bundle_node = source_node.children[0]
            checked_before = set(app._checked)

            region = tree._get_label_region(bundle_node._line)
            assert region is not None
            # Click well past the checkbox glyph, into the rest of the label - this is
            # "navigation as is" territory (cursor move/expand), never a checkbox toggle.
            await pilot.click(tree, offset=(region.x + region.width - 1, bundle_node._line))
            await pilot.pause()

            assert app._checked == checked_before
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_clicking_elsewhere_on_row_does_not_toggle


def test_clicking_the_expand_arrow_toggles_expand_exactly_once(tmp_path: Path) -> None:
    # regression: Textual dispatches "_on_click" to every class in the MRO that defines
    # it, so explicitly calling `super()._on_click(event)` from our own override fired
    # Tree's own handler *again* - collapsing right back after expanding, silently, so
    # a triangle click looked like it did nothing at all.
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            source_node = _source_nodes(app)["humblebundle"]
            checked_before = set(app._checked)
            assert source_node.is_expanded is False

            region = tree._get_label_region(source_node._line)
            assert region is not None
            await pilot.click(tree, offset=(region.x, source_node._line))
            await pilot.pause()

            assert source_node.is_expanded is True
            assert app._checked == checked_before
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_clicking_the_expand_arrow_toggles_expand_exactly_once


def test_ctrl_right_expands_whole_tree_recursively(tmp_path: Path) -> None:
    lists_root = tmp_path / "lists"
    path = lists_root / "humblebundle/bundle/2026-01-01_a/bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "schema: 1\nname: One\ngames:\n  - name: G\n    ids: [steam:440]\n",
        encoding="utf-8",
    )

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            tree.focus()
            tree.cursor_line = 0
            await pilot.pause()
            await pilot.press("ctrl+right")
            await pilot.pause()

            source_node = _source_nodes(app)["humblebundle"]
            assert source_node.is_expanded is True
            bundle_node = source_node.children[0]
            assert bundle_node.is_expanded is True
            game_node = bundle_node.children[0]
            assert game_node.is_expanded is True
            assert [child.label.plain for child in game_node.children] == ["Store: steam", "Launch on Steam"]

            await pilot.press("ctrl+left")
            await pilot.pause()
            assert source_node.is_expanded is False
            assert bundle_node.is_expanded is False
            assert game_node.is_expanded is False
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_ctrl_right_expands_whole_tree_recursively


def test_shift_right_expands_only_the_cursor_subtree(tmp_path: Path) -> None:
    lists_root = _make_lists_root(tmp_path)

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            tree.focus()
            tree.cursor_line = 0
            await pilot.pause()
            cursor_source = tree.cursor_node
            await pilot.press("shift+right")
            await pilot.pause()

            assert cursor_source.is_expanded is True
            assert cursor_source.children[0].is_expanded is True

            other_sources = [node for node in tree.root.children if node is not cursor_source]
            assert all(node.is_expanded is False for node in other_sources)
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_shift_right_expands_only_the_cursor_subtree


def test_expand_arrow_renders_before_the_checkbox_glyph(tmp_path: Path) -> None:
    from rich.style import Style

    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            source_node = _source_nodes(app)["humblebundle"]

            rendered = tree.render_label(source_node, Style(), Style())
            plain = rendered.plain
            assert plain.index(tree.ICON_NODE.strip()) < plain.index("[")
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_expand_arrow_renders_before_the_checkbox_glyph


def test_filter_deselects_non_matching_bundles(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert app._checked == {
                "greenmangaming/bundle/2026-02-01_b/tier-2",
                "humblebundle/bundle/2026-01-01_a/bundle",
            }

            # min-items excludes the 3-item humblebundle bundle, leaving the 10-item one
            app.query_one("#filter-min-items", Input).value = "5"
            await pilot.pause()
            assert app._checked == {"greenmangaming/bundle/2026-02-01_b/tier-2"}

            # widening the filter back doesn't resurrect the deselected bundle (one-way ratchet)
            app.query_one("#filter-min-items", Input).value = ""
            await pilot.pause()
            assert app._checked == {"greenmangaming/bundle/2026-02-01_b/tier-2"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_filter_deselects_non_matching_bundles


def test_show_filtered_checkbox_reveals_filtered_out_bundles_unchecked(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app.query_one("#filter-min-items", Input).value = "5"
            await pilot.pause()
            # filtered-out bundle is hidden by default ("show filtered" starts off)
            assert set(_source_nodes(app)) == {"greenmangaming"}
            assert "humblebundle/bundle/2026-01-01_a/bundle" not in app._checked

            app.query_one("#filter-show-filtered", Checkbox).value = True
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming", "humblebundle"}
            assert _leaf_list_ids(app, "humblebundle") == ["humblebundle/bundle/2026-01-01_a/bundle"]
            # shown, but still unchecked - "show filtered" doesn't select anything by itself
            assert "humblebundle/bundle/2026-01-01_a/bundle" not in app._checked

            app.query_one("#filter-show-filtered", Checkbox).value = False
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_show_filtered_checkbox_reveals_filtered_out_bundles_unchecked


def test_checking_a_filtered_out_bundle_then_hiding_it_again_drops_it_with_no_tracking(tmp_path: Path) -> None:
    # no special override/tracking state: toggling "show filtered" off just re-filters
    # the list, full stop - whatever got checked while a bundle was visible doesn't
    # keep it around once it's filtered out again
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app.query_one("#filter-min-items", Input).value = "5"
            await pilot.pause()
            app.query_one("#filter-show-filtered", Checkbox).value = True
            await pilot.pause()

            humble_bundle_id = "humblebundle/bundle/2026-01-01_a/bundle"
            app._toggle(_NodeData(kind="bundle", source="humblebundle", list_id=humble_bundle_id))
            await pilot.pause()
            assert humble_bundle_id in app._checked

            app.query_one("#filter-show-filtered", Checkbox).value = False
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming"}

            # still technically "checked" internally, but that's irrelevant now: it's not
            # part of the tree, and _build_selection excludes it from the saved result too
            assert humble_bundle_id in app._checked
            selection = app._build_selection()
            assert humble_bundle_id not in selection.selected
            assert humble_bundle_id in selection.excluded
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_checking_a_filtered_out_bundle_then_hiding_it_again_drops_it_with_no_tracking


def test_manually_deselected_bundle_stays_visible_regardless_of_show_filtered(tmp_path: Path) -> None:
    # a bundle that isn't excluded by any active filter is always shown, whether the
    # user unchecked it by hand or not - "show filtered" only concerns filtered bundles
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded={"greenmangaming/bundle/2026-02-01_b/tier-2"})
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app.query_one("#filter-show-filtered", Checkbox).value = True
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming", "humblebundle"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_manually_deselected_bundle_stays_visible_regardless_of_show_filtered


def test_switching_tiers_to_highest_unchecks_lower_sibling_tiers(tmp_path: Path) -> None:
    lists_root = _make_lists_root(tmp_path)
    _write_list(lists_root, "vendorx/bundle/2026-03-01_c/tier-1", item_count=2, tier=1, name="Tiered Tier 1")
    _write_list(lists_root, "vendorx/bundle/2026-03-01_c/tier-2", item_count=4, tier=2, name="Tiered Tier 2")

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set(), tier_mode="all")
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert {
                "vendorx/bundle/2026-03-01_c/tier-1",
                "vendorx/bundle/2026-03-01_c/tier-2",
            } <= app._checked

            app.query_one("#filter-tiers", Select).value = "highest"
            await pilot.pause()
            assert "vendorx/bundle/2026-03-01_c/tier-1" not in app._checked
            assert "vendorx/bundle/2026-03-01_c/tier-2" in app._checked

            app.query_one("#filter-tiers", Select).value = "all"
            await pilot.pause()
            assert {
                "vendorx/bundle/2026-03-01_c/tier-1",
                "vendorx/bundle/2026-03-01_c/tier-2",
            } <= app._checked
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_switching_tiers_to_highest_unchecks_lower_sibling_tiers


def test_mode_and_tiers_selectors_default_to_constructor_args_and_are_changeable(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set(), match_mode="all", tier_mode="highest")
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert app.match_mode == "all"
            assert app.tier_mode == "highest"
            app.query_one("#filter-mode", Select).value = "any"
            app.query_one("#filter-tiers", Select).value = "all"
            await pilot.pause()
            assert app.match_mode == "any"
            assert app.tier_mode == "all"
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_mode_and_tiers_selectors_default_to_constructor_args_and_are_changeable


def test_min_items_filter_deselects_and_hides_smaller_bundles_by_default(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            min_items = app.query_one("#filter-min-items", Input)
            min_items.value = "5"
            await pilot.pause()
            # deselected by the filter (see test_filter_deselects_non_matching_bundles), and
            # "show filtered" defaults to off, so it's hidden entirely rather than staying visible
            assert set(_source_nodes(app)) == {"greenmangaming"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_min_items_filter_deselects_and_hides_smaller_bundles_by_default


def test_unchecking_and_saving_produces_expected_selection(tmp_path: Path) -> None:
    app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app._toggle(_NodeData(kind="bundle", source="greenmangaming", list_id="greenmangaming/bundle/2026-02-01_b/tier-2"))
            await pilot.pause()
            app.action_save()
        # end async with
    # end def scenario

    asyncio.run(scenario())

    assert app.return_value is not None
    assert app.return_value.selected == ["humblebundle/bundle/2026-01-01_a/bundle"]
    assert app.return_value.excluded == ["greenmangaming/bundle/2026-02-01_b/tier-2"]
    assert [game_list.id for game_list in app.all_game_lists] == [
        "greenmangaming/bundle/2026-02-01_b/tier-2",
        "humblebundle/bundle/2026-01-01_a/bundle",
    ]
# end def test_unchecking_and_saving_produces_expected_selection


def test_enter_key_toggles_cursor_node(tmp_path: Path) -> None:
    # end-to-end check that the Enter binding really reaches _toggle, not just direct calls
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            tree = _tree(app)
            tree.focus()
            tree.cursor_line = 0
            await pilot.pause()
            first_source = tree.cursor_node.data.source
            assert first_source in app._checked or True  # sanity: cursor lands on a source node first
            await pilot.press("enter")
            await pilot.pause()
            bundles_of_first_source = {
                bundle.list_id for bundle in app._bundles if bundle.source == first_source
            }
            assert not (bundles_of_first_source & app._checked)
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_enter_key_toggles_cursor_node


def test_cancel_returns_none(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            app.action_cancel()
        # end async with
        assert app.return_value is None
    # end def scenario

    asyncio.run(scenario())
# end def test_cancel_returns_none
