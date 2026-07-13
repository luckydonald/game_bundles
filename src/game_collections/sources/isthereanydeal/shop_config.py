"""Reviewed shop table, used to corroborate resolved storefront IDs and as a slug reference."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from game_collections.models import NonEmptyString, StrictModel


class ItadShopEntry(StrictModel):
    """One reviewed ITAD shop.

    `id` is absent for the two entries ITAD itself has no shop id for (App
    Store, Google Play) - kept for completeness, not usable as a `keys`
    lookup. `slug` is absent for shops with no known qualified-id scheme yet
    - it's a human-facing reference for what `slug:...` prefixes exist or
    are planned, not something resolution code currently looks up by shop id
    (storefront URLs are matched by host, see `sources/storefronts.py`).
    """

    name: NonEmptyString
    id: int | None = None
    slug: NonEmptyString | None = None

# end class ItadShopEntry


class ItadShopConfig(StrictModel):
    """Reviewed table of ITAD shops."""

    schema_version: Literal[2] = Field(alias="schema", serialization_alias="schema")
    shops: list[ItadShopEntry] = Field(default_factory=list)

# end class ItadShopConfig


def load_shop_config(path: Path) -> dict[int, str]:
    """Load the reviewed shop-id->name table, or an empty one if absent.

    Entries with no `id` (App Store, Google Play) are omitted - nothing
    keys ITAD's `keys: list[int]` shop-key data by them.
    """
    if not path.exists():
        return {}
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    config = ItadShopConfig.model_validate(raw)
    return {entry.id: entry.name for entry in config.shops if entry.id is not None}
# end def load_shop_config
