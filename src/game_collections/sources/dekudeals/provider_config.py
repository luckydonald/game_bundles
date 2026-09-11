"""Reviewed mapping from a DekuDeals bundle's own `store_name` to our `lists/<slug>/` directory."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from game_collections.models import StrictModel
from game_collections.sources.storefronts import slugify_provider_name


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class DekuProviderConfig(StrictModel):
    """Reviewed mappings from a DekuDeals `store_name` to our list-directory slug."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    providers: dict[str, str] = Field(default_factory=dict)

# end class DekuProviderConfig


def load_provider_config(path: Path) -> DekuProviderConfig:
    """Load the reviewed provider mapping, or an empty one if absent."""
    if not path.exists():
        return DekuProviderConfig(schema=1, providers={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DekuProviderConfig.model_validate(raw)
# end def load_provider_config


def resolve_provider_slug(store_name: str, config: DekuProviderConfig, log: LogFn = _NO_LOG) -> str:
    """Return the `lists/<slug>/` directory name for one bundle's `store_name`."""
    slug = config.providers.get(store_name)
    if slug is not None:
        return slug
    # end if
    fallback = slugify_provider_name(store_name)
    log(
        f"warning: unreviewed DekuDeals store_name {store_name!r}; "
        f"guessed slug {fallback!r} - add it to config/dekudeals-providers.yml"
    )
    return fallback
# end def resolve_provider_slug
