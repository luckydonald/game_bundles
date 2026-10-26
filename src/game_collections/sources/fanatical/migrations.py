"""Version-step list migrating archived Fanatical `metadata.json`/`source.json` to the current shape."""

from __future__ import annotations

from game_collections.versioning import MigrationStep


# `FANATICAL_V1` is the first shape; nothing to migrate from yet.
METADATA_MIGRATIONS: list[MigrationStep] = []

SOURCE_MIGRATIONS: list[MigrationStep] = []
