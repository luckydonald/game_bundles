from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from game_collections.apply.config import (
    ApplySelection,
    SelectionLoadError,
    excluded_list_ids,
    load_selection,
    save_selection,
)


def test_load_selection_returns_none_when_absent(tmp_path: Path) -> None:
    assert load_selection(tmp_path / "missing.yml") is None
# end def test_load_selection_returns_none_when_absent


def test_save_and_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "config/apply-selection.yml"
    selection = ApplySelection(
        schema=1,
        selected=["a/bundle/x"],
        excluded=["b/bundle/y"],
        updated_at=datetime(2026, 7, 13, tzinfo=UTC),
    )

    save_selection(selection, path)
    loaded = load_selection(path)

    assert loaded is not None
    assert loaded.selected == ["a/bundle/x"]
    assert loaded.excluded == ["b/bundle/y"]
# end def test_save_and_load_round_trips


def test_excluded_list_ids_empty_for_none_selection() -> None:
    assert excluded_list_ids(None) == set()
# end def test_excluded_list_ids_empty_for_none_selection


def test_excluded_list_ids_reads_excluded_field() -> None:
    selection = ApplySelection(schema=1, selected=[], excluded=["a", "b"], updated_at=datetime.now(UTC))
    assert excluded_list_ids(selection) == {"a", "b"}
# end def test_excluded_list_ids_reads_excluded_field


def test_invalid_selection_config_raises(tmp_path: Path) -> None:
    path = tmp_path / "apply-selection.yml"
    path.write_text("schema: 1\nselected: []\nexcluded: []\nextra: true\n", encoding="utf-8")

    with pytest.raises(SelectionLoadError):
        load_selection(path)
    # end with
# end def test_invalid_selection_config_raises
