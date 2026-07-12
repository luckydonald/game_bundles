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

Run focused tests with `uv run pytest tests/test_<area>.py -q` (fixtures live in `tests/fixtures/`). Regenerating `schemas/game-list.schema.json`, `schemas/humblebundle-archive.schema.json`, and `schemas/dailyindiegame-archive.schema.json` is required after changing public list or archive models; `tests/test_schema.py` detects drift.

## CLI surface

`src/game_collections/cli.py` is the single Typer entry point (`game-collections`). Verbs: `list`, `search NAME` (ranked matches across storefronts, `--provider`), `complete FILE` (fills draft `ids:`, `--store`/`--provider`, `--mode blank|missing|unresolved|refetch_all`), `schema`, `scrape humblebundle` (`--url` repeatable, `--non-interactive`, `--refresh`), `scrape dailyindiegame` (`--url` repeatable, `--refresh`; opens a real browser window, see below), `eligible steam`, `sync steam` (dry-run) / `sync steam --apply`, `restore steam <dir>`. Both `scrape` commands log progress live ("Bundle/Offer x/y", "  Game x/y"), write each offer to disk as soon as it's ready, and resume from already-archived output by default (skipping re-fetch/re-resolution unless the archive schema changed or `--refresh` is passed). See root `README.md` for the full behavior of each verb and `lists/README.md` for the list-authoring workflow.

## Architecture

- `src/game_collections/models.py` and `lists.py`: launcher-neutral YAML contract, path-derived IDs, and discovery.
- `src/game_collections/search.py`: cross-storefront ranked search used by both `search` and `complete`.
- `src/game_collections/sources/common.py`: file-writing helpers (`atomic_write`, `dump_json`, `render_game_list_yaml`) shared by every source.
- `src/game_collections/sources/humblebundle/`: Humble Choice/Games HTML crawler, parser, and storefront resolver backing `scrape humblebundle`; writes `lists/humblebundle/...` and `archives/humblebundle/...`. `scripts/backfill_humble_choice.py` is a standalone historical backfill built on the same crawler internals.
- `src/game_collections/sources/dailyindiegame/`: DailyIndieGame weekly-bundle HTML crawler and parser backing `scrape dailyindiegame`; writes `lists/dailyindiegame/...` and `archives/dailyindiegame/...`. No resolver - bundle pages already link directly to `steam:<appid>`. The site's Cloudflare challenge requires a real (non-headless) `patchright` browser session to fetch pages; see the source README before assuming this can run unattended/in CI.
- See `src/game_collections/sources/README.md` for the crawler/parser/(resolver) pipeline of each source and the scheduled GitHub Actions scrape (Humble only).
- `src/game_collections/launchers/base.py`: adapter registry and shared semantic plan types.
- `src/game_collections/launchers/steam/models.py`: strict models for every important Steam file envelope and relevant payload.
- `src/game_collections/launchers/steam/io.py`: the sole Steam file IO and replacement boundary (`SteamFileGateway`).
- `lists/`: public collection data. IDs are relative paths without `.yml`.
- `archives/`: normalized metadata + raw source archives for scraped/imported lists (Humble, DailyIndieGame), referenced from the matching list's `references` field.
- `schemas/`: `game-list.schema.json`, `humblebundle-archive.schema.json`, and `dailyindiegame-archive.schema.json`, all generated from Pydantic; never hand-edit.

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

Update the root README and `lists/README.md` when public behavior or the list format changes. The `commit-with-lplp-style` skill is active for this repo: commit each completed task, stage explicit paths only, and write messages through `ai/git/pending-commit.md`.
