"""Reviewed shop-id->name table, used only to corroborate resolved storefront IDs."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from game_collections.models import StrictModel


class ItadShopConfig(StrictModel):
    """Reviewed mapping from ITAD's numeric shop ids to their display names."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    shops: dict[str, str] = Field(default_factory=dict)

# end class ItadShopConfig


def load_shop_config(path: Path) -> dict[int, str]:
    """Load the reviewed shop-id->name table, or an empty one if absent."""
    if not path.exists():
        return {}
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = ItadShopConfig.model_validate(raw)
    return {int(shop_id): name for shop_id, name in config.shops.items()}
# end def load_shop_config
