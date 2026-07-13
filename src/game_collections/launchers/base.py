"""Launcher-neutral synchronization interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from game_collections.lists import LoadedGameList
from game_collections.models import StrictModel


class CollectionEligibility(StrictModel):
    """Ownership result for one logical list."""

    list_id: str
    name: str
    eligible: bool
    owned_ids: list[str]
    missing_ids: list[str]
    unsupported_ids: list[str]

# end class CollectionEligibility


class PlannedCollectionChange(StrictModel):
    """A launcher-neutral collection change."""

    list_id: str | None = None
    target_id: str
    name: str
    action: Literal["create-or-update", "delete"]
    added_ids: list[str] = Field(default_factory=list)
    preserved_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        if self.action == "create-or-update" and self.list_id is None:
            raise ValueError("create-or-update collection change requires a list ID")
        # end if
        if self.action == "delete" and (self.added_ids or self.preserved_ids):
            raise ValueError("delete collection change must not contain game IDs")
        # end if
        return self
    # end def validate_action

# end class PlannedCollectionChange


class SyncPlan(StrictModel):
    """The complete semantic result before external files are staged."""

    launcher: str
    account: str
    eligibility: list[CollectionEligibility]
    changes: list[PlannedCollectionChange]

# end class SyncPlan


class LauncherAdapter(ABC):
    """Contract implemented independently by Steam, GOG, Epic, and others."""

    name: str

    @abstractmethod
    def evaluate(self, game_lists: list[LoadedGameList]) -> list[CollectionEligibility]:
        """Resolve launcher ownership for every list."""
    # end def evaluate

    @abstractmethod
    def plan(self, game_lists: list[LoadedGameList]) -> SyncPlan:
        """Produce a read-only semantic synchronization plan."""
    # end def plan

    @abstractmethod
    def stage(self, plan: SyncPlan, output_dir: Path) -> Path:
        """Create inspectable candidates outside the launcher directory."""
    # end def stage

    @abstractmethod
    def apply(self, staged_dir: Path, confirm: Callable[[str], str]) -> None:
        """Apply a previously staged and revalidated synchronization."""
    # end def apply

# end class LauncherAdapter


class LauncherRegistry:
    """Explicit registry whose contract can later back entry-point discovery."""

    def __init__(self) -> None:
        self._adapters: dict[str, LauncherAdapter] = {}
    # end def __init__

    def register(self, adapter: LauncherAdapter) -> None:
        if adapter.name in self._adapters:
            raise ValueError(f"launcher already registered: {adapter.name}")
        # end if
        self._adapters[adapter.name] = adapter
    # end def register

    def get(self, name: str) -> LauncherAdapter:
        try:
            return self._adapters[name]
        except KeyError as error:
            available = ", ".join(sorted(self._adapters)) or "none"
            raise ValueError(f"unknown launcher {name!r}; available: {available}") from error
        # end try
    # end def get

# end class LauncherRegistry
