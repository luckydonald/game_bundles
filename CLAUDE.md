# Game Collections agent guidance

## Project

This repository maintains Pydantic-validated YAML game lists and launcher adapters which can synchronize fully owned lists into launcher collections. Python 3.14+ is required. Steam is the only implemented launcher, but core list loading and CLI orchestration must remain launcher-neutral.

`AGENTS.md` is intentionally a symlink to this file, so this content is the root guidance for both Codex and Claude.

## Commands

```console
env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema
```

Run focused tests with `uv run pytest tests/test_<area>.py -q`. Regenerating `schemas/game-list.schema.json` is required after changing public list models; `tests/test_schema.py` detects drift.

## Architecture

- `src/game_collections/models.py` and `lists.py`: launcher-neutral YAML contract, path-derived IDs, and discovery.
- `src/game_collections/launchers/base.py`: adapter registry and shared semantic plan types.
- `src/game_collections/launchers/steam/models.py`: strict models for every important Steam file envelope and relevant payload.
- `src/game_collections/launchers/steam/io.py`: the sole Steam file IO and replacement boundary.
- `lists/`: public collection data. IDs are relative paths without `.yml`.
- `schemas/game-list.schema.json`: generated from Pydantic; never hand-edit.

Storefront identity and launcher synchronization are separate concepts. New GOG or Epic support belongs in its own launcher module implementing the existing contracts. Do not put launcher-specific behavior into YAML loading.

## Python style

- Use complete native type annotations and strict Pydantic models for structured external data.
- Prefer early returns and early `continue`/`break` over nested control flow.
- Close every Python indentation level with an `# end …` comment: `# end if`, `# end for`, `# end while`, `# end with`, `# end try`, `# end def`, and `# end class`.
- Treat unknown external fields and format changes as errors where data may be rewritten.
- Keep comments in code intact, never remove them. Add comments where they explain some bigger algorithm or difficult parts, and actually add value.

## Steam safety invariants

- Never access Steam configuration outside `SteamFileGateway`.
- Never run `sync steam --apply` or `restore steam` against a real account without explicit user permission for that exact operation.
- Dry-run remains read-only. `--apply` first stages candidates and backups outside Steam.
- Validate account mapping, paths, ownership, file type, link count, permissions, metadata, hashes, complete Pydantic models, and cross-file invariants before replacement.
- Require Steam to be stopped and typed confirmation before replacement or restore.
- Preserve unrelated namespace entries and opaque values. Steam synchronization is additive; never remove collections or manually added games.
- Keep namespace and modified-key replacement paired, atomic per file, verified, and rollback-capable.
- Tests must use sanitized temporary fixtures, never copied personal account data.

## Documentation and commits

Update the root README and `lists/README.md` when public behavior or the list format changes. When the user activates `commit-with-lplp-style`, follow the canonical skill: commit each completed task, stage explicit paths only, and write messages through `ai/git/pending-commit.md`.
