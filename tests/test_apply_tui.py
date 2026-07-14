from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

pytest.importorskip("textual", reason="requires the optional `tui` extra: uv sync --extra tui")

from textual.widgets import Input, Select, SelectionList

from game_collections.apply.tui import ApplyPickerApp


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


def _rows(app: ApplyPickerApp) -> SelectionList[str]:
    return app.query_one("#rows", SelectionList)
# end def _rows


def _visible_values(app: ApplyPickerApp) -> list[str]:
    rows = _rows(app)
    return [rows.get_option_at_index(index).value for index in range(rows.option_count)]
# end def _visible_values


def test_mounts_one_option_per_bundle_pre_checked(tmp_path: Path) -> None:
    # discover_game_lists sorts by path, so greenmangaming sorts before humblebundle
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            rows = _rows(app)
            assert set(rows.selected) == {
                "greenmangaming/bundle/2026-02-01_b/tier-2",
                "humblebundle/bundle/2026-01-01_a/bundle",
            }
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_mounts_one_option_per_bundle_pre_checked


def test_previously_excluded_bundle_starts_unchecked(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded={"greenmangaming/bundle/2026-02-01_b/tier-2"})
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            assert set(_rows(app).selected) == {"humblebundle/bundle/2026-01-01_a/bundle"}
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_previously_excluded_bundle_starts_unchecked


def test_source_filter_hides_non_matching_rows(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            select = app.query_one("#filter-source", Select)
            select.value = "humblebundle"
            await pilot.pause()
            assert _visible_values(app) == ["humblebundle/bundle/2026-01-01_a/bundle"]
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_source_filter_hides_non_matching_rows


def test_min_items_filter_hides_smaller_bundles(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            min_items = app.query_one("#filter-min-items", Input)
            min_items.value = "5"
            await pilot.pause()
            assert _visible_values(app) == ["greenmangaming/bundle/2026-02-01_b/tier-2"]
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_min_items_filter_hides_smaller_bundles


def test_unchecking_and_saving_produces_expected_selection(tmp_path: Path) -> None:
    app = ApplyPickerApp(_make_lists_root(tmp_path), excluded=set())

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await _run_until_loaded(app, pilot)
            _rows(app).toggle("greenmangaming/bundle/2026-02-01_b/tier-2")
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
