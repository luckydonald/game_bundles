# Game Collections agent guidance

## Project

This repository maintains Pydantic-validated YAML game lists and launcher adapters which can synchronize ownership-matched lists into launcher collections. Python 3.14+ is required. Steam is the only implemented launcher, but core list loading and CLI orchestration must remain launcher-neutral.

`AGENTS.md` is intentionally a symlink to this file, so this content is the root guidance for both Codex and Claude.

## Commands

```console
env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema
```

Run focused tests with `uv run pytest tests/test_<area>.py -q` (fixtures live in `tests/fixtures/`). Regenerating `schemas/game-list.schema.json` and each source's `schemas/<source>-archive.schema.json` (humblebundle, dailyindiegame, greenmangaming, isthereanydeal, isthereanydeal-game) is required after changing public list or archive models; `tests/test_schema.py` detects drift.

## CLI surface

`src/game_collections/cli.py` is the single Typer entry point (`game-collections`). Verbs: `list`, `search NAME` (ranked matches across storefronts, `--provider`), `complete FILE` (fills draft `ids:`, `--store`/`--provider` incl. the special `isthereanydeal` provider, `--mode blank|missing|unresolved|refetch_all`), `schema`, `migrate-tiers` (`--apply`; dry-run by default, renames tier-shaped bundle lists to `bundle.yml`/`tier-N.yml` and populates `tier:`), `scrape humblebundle`/`scrape greenmangaming` (`--url` repeatable, `--non-interactive`, `--refresh`), `scrape dailyindiegame` (`--url` repeatable, `--refresh`; opens a real browser window, see below), `scrape isthereanydeal` (`--tab live|expired|pending`, `--refresh`), `eligible steam`, `sync steam` (dry-run, defaults to `--mode all --tiers highest`, `--source web|installed|collection`, `--selection-config`) / `sync steam --apply`, `apply steam` (interactive Textual picker variant of `sync`, needs the optional `tui` extra; saves `config/apply-selection.yml`), `restore steam <dir>`. All `scrape` commands log progress live ("Bundle/Offer x/y", "  Game x/y"), write each offer/bundle to disk as soon as it's ready, and resume from already-archived output by default (skipping re-fetch/re-resolution unless the archive schema changed or `--refresh` is passed). See root `README.md` for the full behavior of each verb and `lists/README.md` for the list-authoring workflow.

## Architecture

- `src/game_collections/models.py` and `lists.py`: launcher-neutral YAML contract, path-derived IDs, and discovery.
- `src/game_collections/search.py` and `sources/storefronts.py`: cross-storefront ranked search used by both `search` and `complete`.
- `src/game_collections/sources/common.py`: file-writing helpers (`atomic_write`, `dump_json`, `render_game_list_yaml`) shared by every source.
- `src/game_collections/sources/humblebundle/`: Humble Choice/Games HTML crawler, parser, and storefront resolver backing `scrape humblebundle`; writes `lists/humblebundle/...` and `archives/humblebundle/...`. `scripts/backfill_humble_choice.py` is a standalone historical backfill built on the same crawler internals.
- `src/game_collections/sources/greenmangaming/`: GreenManGaming bundle crawler, parser, and storefront resolver (title-search like Humble, but resolving off a free-text DRM label); writes `lists/greenmangaming/...` and `archives/greenmangaming/...`.
- `src/game_collections/sources/dailyindiegame/`: DailyIndieGame weekly-bundle HTML crawler and parser backing `scrape dailyindiegame`; writes `lists/dailyindiegame/...` and `archives/dailyindiegame/...`. No resolver - bundle pages already link directly to `steam:<appid>`. The site's Cloudflare challenge requires a real (non-headless) `patchright` browser session to fetch pages; see the source README before assuming this can run unattended/in CI.
- `src/game_collections/sources/isthereanydeal/`: isthereanydeal.com bundle-aggregator crawler; resolves storefront IDs directly from each bundle's own detail page (no title-search resolver) and writes into **every** provider's own `lists/<provider>/...` directory, skipping bundles an existing dedicated scraper already covers. Also backs the `complete --provider isthereanydeal` per-game detail-page solver for `unresolved:source:isthereanydeal:...` markers, driven by reviewed `config/isthereanydeal-shops.yml`/`isthereanydeal-providers.yml`/`isthereanydeal-game-aliases.yml`.
- See `src/game_collections/sources/README.md` for the crawler/parser/(resolver) pipeline of each source and the scheduled GitHub Actions scrape (Humble only).
- `src/game_collections/launchers/base.py`: adapter registry and shared semantic plan types.
- `src/game_collections/launchers/steam/models.py`: strict models for every important Steam file envelope and relevant payload.
- `src/game_collections/launchers/steam/io.py`: the sole Steam file IO and replacement boundary (`SteamFileGateway`).
- `src/game_collections/launchers/steam/local_ownership.py` and `discovery.py`: the `--source installed` (local `libraryfolders.vdf`/`appmanifest_*.acf`) and `--source collection` (manually curated Steam collection) ownership fallbacks used instead of the Web API.
- `src/game_collections/migrate_tiers.py`: the one-time `migrate-tiers` migration that renames legacy tier-shaped list files onto the current `bundle.yml`/`tier-N.yml` + `tier:` convention.
- `src/game_collections/apply/`: launcher-neutral picker package backing `apply steam` — `metadata.py` derives display facts from already-loaded lists (no archive access), `config.py` is the `ApplySelection` model persisted to `config/apply-selection.yml`, `tui.py` is the Textual app (optional `tui` extra).
- `lists/`: public collection data. IDs are relative paths without `.yml`.
- `archives/`: normalized metadata + raw source archives for scraped/imported lists (per-source subdirectory), referenced from the matching list's `references` field.
- `schemas/`: `game-list.schema.json` plus one `<source>-archive.schema.json` per source, all generated from Pydantic; never hand-edit.

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
- Preserve unrelated namespace entries and opaque values. Reconcile only static `🗃️ `-prefixed managed collections (plus recognized legacy deterministic collections), protect the ownership-source collection, and preserve manually added games in retained collections.
- Keep namespace and modified-key replacement paired, atomic per file, verified, and rollback-capable.
- Tests must use sanitized temporary fixtures, never copied personal account data.

## Documentation and commits

Update the root README and `lists/README.md` when public behavior or the list format changes. The `commit-with-lplp-style` skill is active for this repo: commit each completed task, stage explicit paths only, and write messages through `ai/git/pending-commit.md`.
