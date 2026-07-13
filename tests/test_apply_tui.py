from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual", reason="requires the optional `tui` extra: uv sync --extra tui")

from textual.widgets import Checkbox, Input, Select

from game_collections.apply.metadata import BundleMetadata
from game_collections.apply.tui import ApplyPickerApp


def _bundles() -> list[BundleMetadata]:
    return [
        BundleMetadata(
            list_id="humblebundle/bundle/a/bundle",
            source="humblebundle",
            bundle_kind="bundle",
            item_count=3,
            date="2026-01-01",
            tier=None,
            name="Small Bundle",
        ),
        BundleMetadata(
            list_id="greenmangaming/bundle/b/tier-2",
            source="greenmangaming",
            bundle_kind="bundle",
            item_count=10,
            date="2026-02-01",
            tier=2,
            name="Big Bundle",
        ),
    ]
# end def _bundles


def test_mounts_one_checkbox_per_bundle_pre_checked() -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_bundles(), excluded=set())
        async with app.run_test():
            assert app.query_one("#row-0", Checkbox).value is True
            assert app.query_one("#row-1", Checkbox).value is True
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_mounts_one_checkbox_per_bundle_pre_checked


def test_previously_excluded_bundle_starts_unchecked() -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_bundles(), excluded={"greenmangaming/bundle/b/tier-2"})
        async with app.run_test():
            assert app.query_one("#row-0", Checkbox).value is True
            assert app.query_one("#row-1", Checkbox).value is False
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_previously_excluded_bundle_starts_unchecked


def test_source_filter_hides_non_matching_rows() -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_bundles(), excluded=set())
        async with app.run_test() as pilot:
            select = app.query_one("#filter-source", Select)
            select.value = "humblebundle"
            await pilot.pause()
            assert app.query_one("#row-0", Checkbox).display is True
            assert app.query_one("#row-1", Checkbox).display is False
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_source_filter_hides_non_matching_rows


def test_min_items_filter_hides_smaller_bundles() -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_bundles(), excluded=set())
        async with app.run_test() as pilot:
            min_items = app.query_one("#filter-min-items", Input)
            min_items.value = "5"
            await pilot.pause()
            assert app.query_one("#row-0", Checkbox).display is False
            assert app.query_one("#row-1", Checkbox).display is True
        # end async with
    # end def scenario

    asyncio.run(scenario())
# end def test_min_items_filter_hides_smaller_bundles


def test_unchecking_and_saving_produces_expected_selection() -> None:
    app = ApplyPickerApp(_bundles(), excluded=set())

    async def scenario() -> None:
        async with app.run_test():
            app.query_one("#row-1", Checkbox).value = False
            app.action_save()
        # end async with
    # end def scenario

    asyncio.run(scenario())

    assert app.return_value is not None
    assert app.return_value.selected == ["humblebundle/bundle/a/bundle"]
    assert app.return_value.excluded == ["greenmangaming/bundle/b/tier-2"]
# end def test_unchecking_and_saving_produces_expected_selection


def test_cancel_returns_none() -> None:
    async def scenario() -> None:
        app = ApplyPickerApp(_bundles(), excluded=set())
        async with app.run_test():
            app.action_cancel()
        # end async with
        assert app.return_value is None
    # end def scenario

    asyncio.run(scenario())
# end def test_cancel_returns_none
