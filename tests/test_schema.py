from __future__ import annotations

from pathlib import Path

from game_collections.schema import render_schema


REPO_ROOT = Path(__file__).parents[1]


def test_committed_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/game-list.schema.json").read_text(encoding="utf-8")
    assert committed == render_schema()
# end def test_committed_schema_matches_pydantic_models

