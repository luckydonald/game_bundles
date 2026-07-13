from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from game_collections.sources.isthereanydeal.game_alias_config import (
    ItadGameAliasConfig,
    load_game_alias_config,
)


def test_load_game_alias_config_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_game_alias_config(tmp_path / "missing.yml") == {}
# end def test_load_game_alias_config_missing_file_returns_empty


def test_load_game_alias_config_valid_group(tmp_path: Path) -> None:
    path = tmp_path / "isthereanydeal-game-aliases.yml"
    path.write_text(
        "schema: 1\naliases:\n  - [pinball-fx-my-little-pony-pinball, my-little-pony-pinball]\n",
        encoding="utf-8",
    )
    groups = load_game_alias_config(path)
    expected = frozenset({"pinball-fx-my-little-pony-pinball", "my-little-pony-pinball"})
    assert groups == {
        "pinball-fx-my-little-pony-pinball": expected,
        "my-little-pony-pinball": expected,
    }
# end def test_load_game_alias_config_valid_group


def test_duplicate_slug_across_groups_rejected() -> None:
    with pytest.raises(ValidationError, match="more than one alias group"):
        ItadGameAliasConfig.model_validate(
            {"schema": 1, "aliases": [["a", "b"], ["b", "c"]]}
        )
    # end with
# end def test_duplicate_slug_across_groups_rejected


def test_single_slug_group_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 2 distinct slugs"):
        ItadGameAliasConfig.model_validate({"schema": 1, "aliases": [["a"]]})
    # end with
# end def test_single_slug_group_rejected
