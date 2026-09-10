# Merge bundle variation files into one, DRY'd, flattened list

## Context

Bundle directories under `lists/<provider>/bundle/<key>/` currently hold one YAML file per purchase tier ("variation") — `tier-1.yml`, `tier-2.yml`, ... (or a lone `bundle.yml` for single-tier bundles). Every sibling file repeats the same `references`, `crawlers`, and a shared bundle-name prefix, and cumulative tiers duplicate every lower tier's `games` entries verbatim into each higher tier's file (confirmed across Humble, GreenManGaming, isthereanydeal, StackSocial, Indie Royale examples — writer code in `write_humble_offer`/`write_gmg_offer`/`write_itad_offer` builds each tier's game list by extending a `seen_ids`-deduped pool, so higher-rank tiers are always supersets of lower ones, except isthereanydeal's BYOB (build-your-own-bundle) tiers, which instead share one identical game pool across all ranks and vary only `pick_quota`).

Goal: one file per bundle directory (`lists/<provider>/bundle/<key>.yml`, folder flattened by one level), holding the bundle's `games` once, each `Game` recording which tier rank(s) it belongs to, and the bundle's `references`/`crawlers` recorded once. This removes duplication and lets tooling show "how close to the top variation" a bundle is.

Confirmed with user:
- Per-game field is a **full list of tier ranks** (`tiers: list[int]`), not just the lowest — defensive against a future non-cumulative bundle (BYOB already isn't cumulative) and lets UI show the "most complete" owned variation directly.
- **All** bundle directories flatten, including already-single-file ones (`bundle.yml` → `<key>.yml`), for a uniform on-disk shape.
- Steam sync's tier selection changes from a `--tiers {all,highest}` choice to `--include-lower-tiers` (bool flag), with `highest`-only remaining the default (already true) — internal `SteamTierMode` enum can stay, only the CLI-facing option changes shape.

## Schema changes (`src/game_collections/models.py`)

- Add `TierDefinition(StrictModel)`: `rank: Annotated[int, Field(ge=1)]`, `name: NonEmptyString`, `pick_quota: Annotated[int, Field(ge=1)] | None = None`.
- `GameList`: replace the singular `tier: int | None` field with `tiers: list[TierDefinition] = Field(default_factory=list)` (empty for non-bundle lists and single-tier bundles, matching today's `tier=None` convention). Keep the existing list-level `pick_quota` field untouched — it's still used by Humble Choice pool files (`choice/YYYY-MM.yml`), which are out of scope (not under a `bundle/` directory, not "variations").
- `Game`: add `tiers: list[int] = Field(default_factory=list)` (ranks this game belongs to; empty when the list has no `tiers`).
- New `GameList` model validator: every `Game.tiers` value must be a rank present in `self.tiers`; `TierDefinition.rank` values must be unique and consistent with existing duplicate-checking style validators already in the file (`duplicate_qualified_ids`, group-name consistency).
- Regenerate `schemas/game-list.schema.json` via `uv run game-collections schema` once models land.

## Migration: `src/game_collections/merge_bundle_variations.py`

New module mirroring `migrate_tiers.py`'s discover → plan → apply shape (reuse `discover_bundle_directories` from `migrate_tiers.py` rather than reimplementing bundle-dir discovery):

- **Single-file directories** (`bundle.yml` only): pure rename/flatten, `<key>/bundle.yml` → `<key>.yml`, no schema change to the file's content (`tiers`/game `tiers` stay empty).
- **Multi-file directories** (`tier-1.yml..tier-N.yml`, already-migrated convention from `migrate_tiers.py`): for each sibling file, load and validate via `load_game_list`; build one `TierDefinition` per file (`rank` from the existing `tier` field, `name` = the suffix after the bundle's common `" — "`-separated name prefix, else `f"Tier {rank}"`, `pick_quota` carried over from the file's list-level `pick_quota`); merge `games` by matching entries across files the same way `sources/common.py`'s existing merge logic matches games (qualified-ID overlap, falling back to casefolded name) — for each matched game, union the ranks of every file it appears in into `Game.tiers`; merge `references`/`crawlers` with the existing `merge_references`/`merge_crawlers` helpers (`sources/common.py`) instead of reimplementing dedup; derive the merged list's own `name` from the common prefix (or the highest tier's base name when no shared `" — "` prefix exists).
- `TierMigrationError`-style exception + a `step_would_change`-equivalent idempotency check, atomic write via `atomic_write`/`render_game_list_yaml`, re-validate the written file, `unlink()` old sibling files, then remove the now-empty bundle-key directory.
- CLI command `migrate-bundle-variations` in `cli.py` (dry-run by default, `--apply` to write), following `migrate_tiers_command`'s existing structure/output format (`would migrate: ... -> ...` vs `migrated: ...`).
- New test module `tests/test_merge_bundle_variations.py` mirroring `tests/test_migrate_tiers.py`'s fixture/assertion style: single-file flatten, cumulative multi-tier merge (games dedup + `tiers` union correctness), BYOB-style merge (identical pool, differing `pick_quota` per `TierDefinition`), idempotency (re-run is a no-op), and an end-to-end check that the Steam adapter's highest-tier selection still works against the merged shape.

## Writer updates (so future crawls emit the merged shape directly)

Update `write_humble_offer` (`sources/humblebundle/crawler.py`, tier branch ~L347-401), `write_itad_offer` (`sources/isthereanydeal/crawler.py`, both the BYOB branch ~L565-591 and the plain-tier branch ~L594-632), and `write_gmg_offer` (`sources/greenmangaming/crawler.py`) to each build **one** `GameList` per bundle (not one per tier): accumulate `TierDefinition`s and per-game `tiers` membership while walking the source tiers, write a single path `list_directory.parent / f"{key}.yml"` (no `bundle/<key>/` subdirectory), and merge against a pre-existing on-disk list via `sources/common.py`'s `merge_game_list` — which also needs updating so its authoritative/non-authoritative reconciliation understands per-game `tiers` membership instead of assuming one tier per file (it currently merges `GameList.tier`/`pick_quota` as flat scalars; needs to reconcile `GameList.tiers` and each matched `Game.tiers` the same union-based way the migration does). Since dead code paths writing `tier-N.yml`/`bundle.yml` inside a bundle-key directory are being fully retired, remove them rather than leaving them unreachable.

## Steam adapter changes (`src/game_collections/launchers/steam/adapter.py`)

This is the highest-risk part: today one `LoadedGameList` → exactly one `CollectionEligibility` → exactly one Steam collection (`steam_collection_id(list_id)`, a straight hash of the file's list ID). A merged bundle file can represent several variations, and the existing UX (separate Bronze/Gold Steam collections, "highest owned" selection) needs to keep working from one file instead of several sibling files.

- `evaluate()`: for a `game_list.data.tiers`-empty list, behave exactly as today (one `CollectionEligibility`, `tier=None`). For a list with `tiers`, emit **one `CollectionEligibility` per `TierDefinition`**: filter `game_list.data.games` to those whose `.tiers` contains that rank, compute completion/`pick_quota` eligibility against just that subset (reusing `evaluate_completion`), and give each result a synthetic but stable `list_id` derived from the base id and rank (e.g. `f"{game_list.id}#tier-{rank}"`) — `steam_collection_id()` is a pure hash of this string, so distinct synthetic IDs naturally produce distinct, stable Steam collection IDs with no changes needed there. Carry `tier=rank` on each result as today.
- `_selected_list_ids()`: simplify now that same-bundle tier results share a `list_id` prefix instead of a `rpartition("/")`-derived parent folder — group by the base id (strip the `#tier-N` suffix) to find "highest eligible tier" per bundle; `tier_mode="all"` keeps every eligible tier's synthetic id as before.
- `_managed_deletions()`: currently assumes one `steam_collection_id(game_list.id)` per loaded list (line ~290) and raises on collision — must instead enumerate the same per-tier synthetic IDs `evaluate()` produces (share one helper between the two) so reconciliation/deletion tracks every synthetic collection, not just the file-level one.
- `PlannedCollectionChange.list_id` stays the synthetic per-tier id; `target_id`/`name` derivation (`plan()` ~L221-231) is unchanged in shape.

## CLI surface changes (`src/game_collections/cli.py`)

- `sync steam` (~L1330) and `apply steam` (~L1431): replace the `--tiers {all,highest}` `typer.Option` with `--include-lower-tiers` (boolean flag, default `False`). Translate internally: `False → tier_mode="highest"`, `True → tier_mode="all"`. Keep `SteamTierMode`/`tier_mode` as the internal representation passed to `SteamSyncOptions` to minimize churn elsewhere (adapter, `apply/config.py`'s persisted `ApplySelection.tier_mode`, the Textual picker) — only the two CLI `Option` definitions and their help text change shape; `apply`'s saved-selection fallback logic (~L1466) keeps working against the same internal enum.
- Add `migrate-bundle-variations` command (see above), registered alongside the existing `migrate-tiers` command.

## Docs

- `lists/README.md`: replace the "Tier counts and names follow Humble's advertised cumulative tiers..." paragraph and the general tier-file convention description with the new single-file-per-bundle shape (`tiers:`/`Game.tiers` fields, one file per bundle key).
- Root `README.md`: update the `sync steam`/`apply steam` CLI surface docs for `--include-lower-tiers`, and mention `migrate-bundle-variations` alongside `migrate-tiers`.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` — full suite, including new `tests/test_merge_bundle_variations.py` and updated `tests/test_migrate_tiers.py`/adapter/CLI/writer tests (these will need fixture updates wherever they assert on the old per-tier-file shape or `--tiers all|highest`).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` then check `git diff schemas/` matches the model changes; `tests/test_schema.py` also catches drift.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` over the full `lists/` tree after running `migrate-bundle-variations --apply` on a scratch copy (or dry-run first, inspect output, then `--apply` for real once satisfied).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections sync steam` (dry-run only) against real lists post-migration to confirm the same set of eligible/highest-tier Steam collections is produced as before the migration (spot-check a known multi-tier bundle's dry-run output before/after).
