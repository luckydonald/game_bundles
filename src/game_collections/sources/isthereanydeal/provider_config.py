"""Reviewed mapping from ITAD's own provider pages to our `lists/<provider>/` slugs."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from game_collections.models import StrictModel
from game_collections.sources.isthereanydeal.models import ItadPageInfo


LogFn = Callable[[str], None]
_NO_LOG: LogFn = lambda _message: None  # noqa: E731


class ItadProviderMapping(StrictModel):
    """One reviewed `page.id` -> `lists/<slug>/` mapping."""

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)

# end class ItadProviderMapping


class ItadProviderConfig(StrictModel):
    """Reviewed mappings from ITAD provider page IDs to our list-directory slugs."""

    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    providers: dict[str, ItadProviderMapping] = Field(default_factory=dict)

# end class ItadProviderConfig


def load_provider_config(path: Path) -> ItadProviderConfig:
    """Load the reviewed provider mapping, or an empty one if absent."""
    if not path.exists():
        return ItadProviderConfig(schema=1, providers={})
    # end if
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ItadProviderConfig.model_validate(raw)
# end def load_provider_config


def slugify_provider_name(name: str) -> str:
    """Best-effort kebab-case fallback for a provider with no reviewed mapping."""
    lowered = name.strip().casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not slug:
        raise ValueError(f"could not derive a slug from provider name: {name!r}")
    # end if
    return slug
# end def slugify_provider_name


def resolve_provider_slug(page: ItadPageInfo, config: ItadProviderConfig, log: LogFn = _NO_LOG) -> str:
    """Return the `lists/<slug>/` directory name for one bundle's origin platform."""
    entry = config.providers.get(str(page.id))
    if entry is not None:
        if entry.name != page.name:
            log(
                f"warning: ITAD provider {page.id} display name changed "
                f"({entry.name!r} -> {page.name!r}); config/isthereanydeal-providers.yml is stale"
            )
        # end if
        return entry.slug
    # end if
    fallback = slugify_provider_name(page.name)
    log(
        f"warning: unreviewed ITAD provider page.id={page.id} name={page.name!r}; "
        f"guessed slug {fallback!r} - add it to config/isthereanydeal-providers.yml"
    )
    return fallback
# end def resolve_provider_slug
