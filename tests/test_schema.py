from __future__ import annotations

from pathlib import Path

from game_collections.schema import (
    render_dailyindiegame_schema,
    render_greenmangaming_schema,
    render_humblebundle_schema,
    render_isthereanydeal_schema,
    render_schema,
)


REPO_ROOT = Path(__file__).parents[1]


def test_committed_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/game-list.schema.json").read_text(encoding="utf-8")
    assert committed == render_schema()
# end def test_committed_schema_matches_pydantic_models


def test_committed_humblebundle_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/humblebundle-archive.schema.json").read_text(encoding="utf-8")
    assert committed == render_humblebundle_schema()
# end def test_committed_humblebundle_schema_matches_pydantic_models


def test_committed_dailyindiegame_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/dailyindiegame-archive.schema.json").read_text(encoding="utf-8")
    assert committed == render_dailyindiegame_schema()
# end def test_committed_dailyindiegame_schema_matches_pydantic_models


def test_committed_greenmangaming_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/greenmangaming-archive.schema.json").read_text(encoding="utf-8")
    assert committed == render_greenmangaming_schema()
# end def test_committed_greenmangaming_schema_matches_pydantic_models


def test_committed_isthereanydeal_schema_matches_pydantic_models() -> None:
    committed = (REPO_ROOT / "schemas/isthereanydeal-archive.schema.json").read_text(encoding="utf-8")
    assert committed == render_isthereanydeal_schema()
# end def test_committed_isthereanydeal_schema_matches_pydantic_models
