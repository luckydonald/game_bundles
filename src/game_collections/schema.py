"""Deterministic JSON Schema generation for list files."""

from __future__ import annotations

import json
from pathlib import Path

from game_collections.models import GameList
from game_collections.sources.dailyindiegame.models import DigArchive
from game_collections.sources.greenmangaming.models import GmgArchive
from game_collections.sources.humblebundle.models import HumbleArchive


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


def generate_humblebundle_schema() -> dict[str, object]:
    """Generate the normalized Humble archive schema."""
    return HumbleArchive.model_json_schema(by_alias=True, mode="validation")
# end def generate_humblebundle_schema


def render_humblebundle_schema() -> str:
    """Render the Humble archive schema deterministically."""
    return json.dumps(
        generate_humblebundle_schema(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
# end def render_humblebundle_schema


def write_humblebundle_schema(path: Path) -> None:
    """Write the normalized Humble archive schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_humblebundle_schema(), encoding="utf-8")
# end def write_humblebundle_schema


def generate_dailyindiegame_schema() -> dict[str, object]:
    """Generate the normalized DailyIndieGame archive schema."""
    return DigArchive.model_json_schema(by_alias=True, mode="validation")
# end def generate_dailyindiegame_schema


def render_dailyindiegame_schema() -> str:
    """Render the DailyIndieGame archive schema deterministically."""
    return json.dumps(
        generate_dailyindiegame_schema(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
# end def render_dailyindiegame_schema


def write_dailyindiegame_schema(path: Path) -> None:
    """Write the normalized DailyIndieGame archive schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_dailyindiegame_schema(), encoding="utf-8")
# end def write_dailyindiegame_schema


def generate_greenmangaming_schema() -> dict[str, object]:
    """Generate the normalized Green Man Gaming archive schema."""
    return GmgArchive.model_json_schema(by_alias=True, mode="validation")
# end def generate_greenmangaming_schema


def render_greenmangaming_schema() -> str:
    """Render the Green Man Gaming archive schema deterministically."""
    return json.dumps(
        generate_greenmangaming_schema(),
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
    ) + "\n"
# end def render_greenmangaming_schema


def write_greenmangaming_schema(path: Path) -> None:
    """Write the normalized Green Man Gaming archive schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_greenmangaming_schema(), encoding="utf-8")
# end def write_greenmangaming_schema
