"""Deterministic JSON Schema generation for list files."""

from __future__ import annotations

import json
from pathlib import Path

from game_collections.models import GameList


def generate_schema() -> dict[str, object]:
    """Generate the schema directly from the runtime Pydantic model."""
    return GameList.model_json_schema(by_alias=True, mode="validation")
# end def generate_schema


def render_schema() -> str:
    """Render the committed schema deterministically."""
    return json.dumps(generate_schema(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
# end def render_schema


def write_schema(path: Path) -> None:
    """Write the generated schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_schema(), encoding="utf-8")
# end def write_schema

