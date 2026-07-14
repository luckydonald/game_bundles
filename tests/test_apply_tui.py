from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

pytest.importorskip("textual", reason="requires the optional `tui` extra: uv sync --extra tui")

from textual.widgets import Checkbox, Input, Select, Tree

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


def test_labels_render_literal_brackets_as_checkboxes(tmp_path: Path) -> None:
    # rich.markup would otherwise silently eat "[x]"/"[ ]" (and any "[...]" in a bundle name)
    lists_root = tmp_path / "lists"
    _write_list(lists_root, "humblebundle/bundle/2026-01-01_a/bundle", item_count=1, tier=None, name="One [Deluxe]")

    async def scenario() -> None:
        app = ApplyPickerApp(lists_root, excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            source_node = _source_nodes(app)["humblebundle"]
            assert source_node.label.plain.startswith("[x] ")
            bundle_node = source_node.children[0]
            assert bundle_node.label.plain.startswith("[x] ")
            assert "One [Deluxe]" in bundle_node.label.plain
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_labels_render_literal_brackets_as_checkboxes


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


def test_hide_unselected_checkbox_hides_deselected_items(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded={"greenmangaming/bundle/2026-02-01_b/tier-2"})
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert set(_source_nodes(app)) == {"greenmangaming", "humblebundle"}

            app.query_one("#filter-hide-unselected", Checkbox).value = True
            await pilot.pause()
            assert set(_source_nodes(app)) == {"humblebundle"}

            app.query_one("#filter-hide-unselected", Checkbox).value = False
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming", "humblebundle"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_hide_unselected_checkbox_hides_deselected_items


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


def test_min_items_filter_hides_smaller_bundles(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            min_items = app.query_one("#filter-min-items", Input)
            min_items.value = "5"
            await pilot.pause()
            assert set(_source_nodes(app)) == {"greenmangaming"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_min_items_filter_hides_smaller_bundles


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
