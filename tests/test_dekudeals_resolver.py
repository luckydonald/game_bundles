from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from game_collections.sources.dekudeals.resolver import (
    DekuResolutionMap,
    load_resolution_map,
    render_resolution_map,
    write_resolution_map,
)


def test_load_resolution_map_returns_empty_when_absent(tmp_path: Path) -> None:
    mapping = load_resolution_map(tmp_path / "missing.yml")

    assert mapping.games == {}
# end def test_load_resolution_map_returns_empty_when_absent


def test_write_then_load_round_trips_and_sorts_keys(tmp_path: Path) -> None:
    path = tmp_path / "dekudeals-store-ids.yml"
    mapping = DekuResolutionMap(schema=1, games={"zeta": ["steam:2"], "alpha": ["steam:1"]})

    write_resolution_map(path, mapping)
    rendered = path.read_text(encoding="utf-8")

    assert rendered.index("alpha") < rendered.index("zeta")
    loaded = load_resolution_map(path)
    assert loaded.games == {"alpha": ["steam:1"], "zeta": ["steam:2"]}
# end def test_write_then_load_round_trips_and_sorts_keys


def test_resolution_map_rejects_empty_id_list() -> None:
    with pytest.raises(ValidationError):
        DekuResolutionMap(schema=1, games={"crawl": []})
    # end with
# end def test_resolution_map_rejects_empty_id_list


def test_resolution_map_rejects_duplicate_ids() -> None:
    with pytest.raises(ValidationError):
        DekuResolutionMap(schema=1, games={"crawl": ["steam:1", "steam:1"]})
    # end with
# end def test_resolution_map_rejects_duplicate_ids
