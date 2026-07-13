# Tier naming/field, `apply` TUI, and BYOB support

## Context

Four related asks against `game_collections`:

1. Single-tier bundles currently get a pointless `tier-1.yml`/`entire-N-item-bundle.yml` name — rename to `bundle.yml` when a bundle has only one tier.
2. Tier order is currently 100% derived from filename (via regex in the Steam adapter). Bundle downloaders should instead write an explicit `tier: int` field into the list YAML, and the adapter should read that field instead of parsing filenames.
3. Add a `game-collections apply` TUI (Textual-based) — a graphical variant of `sync` letting the user pick which bundles to sync, with filters (source/type, item-count range, date range, manual per-entry toggle). Selection is saved to a committed config file and copied into the `--apply` staging/backup folder.
4. Support BYOB ("build your own bundle": pick N of M games) bundles properly instead of dumping the whole pool as one all-or-nothing list — affects Humble Choice and ITAD `byob` bundles, plus Steam sync ownership matching.

Confirmed scope decisions (already asked/answered, do not re-ask):
- Migrate **every already-generated list file now** (not forward-only) to the new naming/`tier` field.
- Use **Textual** for the `apply` picker, added as an **optional extra** (`uv sync --extra tui`), not a core dependency.
- BYOB: full implementation plan (schema + scraper + adapter changes), executed as sequential phases — the two scraper sub-phases (Humble Choice, ITAD) are gated on live-verifying their real embedded-JSON shapes first (repo convention: verify, don't guess external shapes), so they may land later than the rest.
- Selection config tracks **both `selected` and `excluded` lists** explicitly (not excluded-only). Undecided bundles (absent from both lists) default to **included** — matches today's no-config full-sync behavior, and the TUI pre-checks any bundle not already in `excluded`.

## Phase 0 — `tier` field on `GameList` (foundation)

- `src/game_collections/models.py`: add `tier: Annotated[int, Field(ge=1)] | None = None` to `GameList` (after `name`). Omit (`None`) for single-tier/no-tier bundles — never write a tautological `tier: 1`. Only set (1-based) when a bundle directory has ≥2 sibling tiers.
- Regenerate `schemas/game-list.schema.json` via `game-collections schema`; `tests/test_schema.py` must pass with no drift.
- `tests/test_lists.py`: add a `GameList` construction case with `tier` set and one with it omitted (round-trip through strict model).

## Phase 1 — Crawlers write `bundle.yml` / `tier-N.yml` + populate `tier`

Per source, in the offer-writing function that currently picks the tier filename:

- **Humble** (`src/game_collections/sources/humblebundle/crawler.py`, `write_humble_offer`, ~lines 247-306): `kind="choice"` unaffected (always single `{key}.yml`, no tier). For `kind="bundle"`: if `len(archive.tiers) == 1` → `bundle.yml`, `tier=None`; else → `tier-{index+1}.yml` (1-based enumerate index, replacing the old cumulative-item-count-based naming) and `tier=index+1` on the constructed `GameList`.
- **GreenManGaming** (`src/game_collections/sources/greenmangaming/crawler.py`, `write_gmg_offer`, ~lines 233-275): stop using the scraped `tier.identifier` for the filename. Single tier → `bundle.yml`, `tier=None`; else → `tier-{index+1}.yml`, `tier=index+1` (code-constructed ordinal, not scraped text). Keep `identifier` in the archive JSON only, for debugging.
- **ITAD** (`src/game_collections/sources/isthereanydeal/crawler.py`, `write_itad_offer`, ~lines 412-464): same pattern. Before implementing, verify in a quick fixture/unit check that `enumerate(archive.tiers)` order matches `tier.identifier`'s existing `f"tier-{len(tiers)+1}"` numbering (should coincide since both are built by appending in order).
- **dailyindiegame**: no change (no tier concept).

Update `tests/test_humblebundle_crawler.py`, `tests/test_greenmangaming_crawler.py`, `tests/test_isthereanydeal_crawler.py`: expected filenames and `GameList.tier` values for single- and multi-tier fixtures.

Commit per source (3 commits) — each independently testable.

## Phase 2 — Adapter reads `tier` field, retires filename regex

- `src/game_collections/launchers/base.py`: add `tier: int | None = None` to `CollectionEligibility`.
- `src/game_collections/launchers/steam/adapter.py`:
  - Delete `TIER_STEM_PATTERN`, `ITEM_BUNDLE_STEM_PATTERN`, `_tier_identity()`.
  - In `evaluate()`, populate the new `CollectionEligibility.tier` from `game_list.data.tier`.
  - In `_selected_list_ids()` (~lines 183-217): keep grouping siblings by parent directory (`list_id.rpartition("/")[0]`) — that grouping concept is still needed since a bare `tier` int doesn't encode which bundle it belongs to — but read `rank = result.tier` directly instead of parsing it from the filename. `tier is None` still means tier-less/always-included, exactly as today's "regex didn't match" case.
- `tests/test_steam_adapter.py`: replace filename-based tier fixtures with `tier=` set directly on `GameList`; keep regression coverage for tier-less lists and duplicate-rank-within-directory raising `ValueError`. Grep test fixtures for hardcoded old filenames and update.

## Phase 3 — Migration script for existing `lists/**/*.yml`

- New CLI subcommand `game-collections migrate-tiers` (in `cli.py`, alongside `schema`/`validate`) with a `--apply` flag (dry-run by default) — keeps one CLI entrypoint rather than a standalone script.
- Per bundle directory, per source:
  - **Humble**: glob `entire-*-item-bundle.yml` / `*-item-bundle.yml` (current scheme) and legacy `tier-1.yml`/`tier-2.yml` (old scheme, already superseded in code but still on disk). Exactly one match → rename to `bundle.yml`, no field. Multiple → order by cumulative item count (the `entire-` file is always rank 1), rename to `tier-1.yml`, `tier-2.yml`, ... and inject `tier: N`.
  - **GMG / ITAD**: glob `tier-*.yml`. Exactly one → rename to `bundle.yml`, no field. Multiple → numeric suffix is already the rank (verify contiguity from 1 first) → keep names, inject `tier: N`.
- Directory doesn't move, only the leaf filename changes, so each list's `Reference` path to its archive JSON needs no recomputation.
- Before running for real: grep `lists/**/*.yml` and `archives/**/*.json` for any cross-references to old tier filenames (unlikely, but confirm none exist).
- Use the existing `atomic_write` helper; after each rewrite, re-parse and validate against `GameList` before considering that file migrated; abort the whole batch on any single validation failure.
- New `tests/test_migrate_tiers.py`: build a temp tree mimicking each source's real pre-migration layout (single- and multi-tier, plus a legacy Humble `tier-N.yml` case), run the migration, assert final filenames/fields, and assert `discover_game_lists()` + adapter `_selected_list_ids()` produce the same effective selection before and after (migration must not change sync behavior, only representation).
- Commit the script+tests separately from the commit that applies it and checks in the resulting `lists/**` diff.

## Phase 4 — `game-collections apply` Textual TUI

- `pyproject.toml`: add `[project.optional-dependencies] tui = ["textual"]`. `apply` command gives an install hint (`uv sync --extra tui`) if textual isn't importable.
- New package `src/game_collections/apply/` (launcher-neutral — wraps `SteamAdapter` but the picker/filter/config concepts aren't Steam-specific):
  - `metadata.py`: `BundleMetadata` dataclass (`list_id`, `source`, `bundle_kind`, `item_count` = `len(game_list.games)`, `date` parsed from the existing `YYYY-MM-DD_slug`/`YYYY-MM` directory-name convention already used by crawlers, `tier` from `GameList.tier`) and `load_bundle_metadata(game_lists: list[LoadedGameList]) -> list[BundleMetadata]`, a pure function needing no archive JSON access (source/date/item-count/tier are all derivable from `list_id` + already-loaded `GameList` fields).
  - `config.py`: new Pydantic model
    ```python
    class ApplySelection(StrictModel):
        schema_version: Literal[1] = Field(1, alias="schema")
        selected: list[str] = Field(default_factory=list)
        excluded: list[str] = Field(default_factory=list)
        updated_at: datetime
    ```
    committed at `config/apply-selection.yml` (matches existing `config/*.yml` naming). A `list_id` absent from both `selected` and `excluded` is treated as included by default (matches today's no-config full-sync behavior).
  - `tui.py`: Textual `App` (`ApplyPickerApp`) — scrollable `Checkbox` row per bundle (pre-checked unless in `excluded`), filter bar (`Select` for source, `Input` fields for min/max item-count and date-after/date-before with `YYYY-MM-DD` parsing — Textual has no built-in date picker, plain validated `Input` is the pragmatic choice). Filters only affect visibility, never mutate checkbox state. On save: write `ApplySelection` via `atomic_write`.
- `cli.py`: new `apply` command mirroring `sync_command`'s options (`--source`, `--steam-root`, `--steam-id`, `--api-key`, `--mode`, `--tiers`, `--lists-root`). Flow: `discover_game_lists()` → `load_bundle_metadata()` → run `ApplyPickerApp` → on save, filter `game_lists` by the resulting selection → reuse the exact same `_steam_adapter()` / `adapter.plan()` / `_print_plan` / `stage()` / confirm / `apply()` flow `sync_command` already uses (only the list-discovery step differs). After `stage()` returns `staged_dir`, also copy `config/apply-selection.yml` into `staged_dir` for an auditable, self-contained backup.
- `sync_command`/`eligible_command` also gain a `--selection-config` option (default `config/apply-selection.yml`, silently ignored if absent) so a saved selection also affects plain `sync`/`eligible`, not just `apply`.
- New tests: `tests/test_apply_config.py` (round-trip `ApplySelection`), `tests/test_apply_metadata.py` (`load_bundle_metadata()` against representative `list_id` shapes per source), a Textual smoke test (mount, filter narrows rows, toggle+save produces expected `ApplySelection` — via Textual's headless `Pilot` testing), and `tests/test_cli.py` coverage for the filter-application boundary (stub the TUI run to return a fixed selection).

## Phase 5 — BYOB ("pick N of M")

### 5a. Model the quota
- `src/game_collections/models.py`: add `pick_quota: Annotated[int, Field(ge=1)] | None = None` to `GameList`. `None` = today's own-everything semantics (fully backward compatible). Add a validator: `pick_quota is None or pick_quota <= len(games)`.
- Regenerate schema, extend `tests/test_lists.py`/`test_schema.py`.

### 5b. ITAD `byob` bundles (gated on live verification)
- **Before writing any model**: fetch a real ITAD bundle detail page flagged `byob: true` and inspect the embedded `liveData.byob` JSON shape (field names, price format, whether counts overlap with `tiers`) — this is explicitly unverified today (per `ai/plans/011_...md`); do not guess the shape.
- Once verified: add `ItadByobTier` (`count: int`, price field reusing whatever price model ITAD already has) and `ItadArchive.byob_tiers: list[ItadByobTier]`. Update `parser.py`'s BYOB handling (currently collapses to one synthetic tier) to parse real per-count tiers. `write_itad_offer` emits one `GameList` per byob count-tier, same pool, `pick_quota=<count>` set, plus `tier=<index+1>` if there are multiple byob tiers (single → `bundle.yml`).
- Update `tests/test_isthereanydeal_parser.py`/`test_isthereanydeal_crawler.py` with real-shape fixtures.

### 5c. Humble Choice pick-count (gated on live verification)
- **Before writing any model**: no existing field carries "how many picks allowed" — `HumbleTier.item_count` is pool size, not quota. Inspect a real/fixture Humble Choice page's embedded JSON (`data-content-choice-data`/marketing data, already read by `parse_choice_page`) for a pick-count-like field tied to subscription tier (Lite/Standard/Premium) before adding any model field — do not hardcode a guessed field name.
- Once verified: add a pick-options model (mirroring ITAD's byob-tiers shape) and emit one `GameList` per pick-option, same `bundle.yml`/`tier-N.yml` + `pick_quota` convention as 5b.

### 5d. Sync ownership matching for quota lists
- `src/game_collections/launchers/steam/adapter.py`, `evaluate()`: when `game_list.data.pick_quota is not None`, override the `--mode all/any` comparison — eligible iff the count of *games* with at least one owned qualified id ≥ `pick_quota`, regardless of `--mode`. Keep `missing_ids` as informational only for quota lists (not a factor in `eligible`).
- Pool-changes-over-time concern (raised by user): each re-crawl of a bundle produces a new dated `list_id`/directory already, so a changed pool naturally becomes a different list — no extra reconciliation logic needed beyond this adapter change.
- `tests/test_steam_adapter.py`: quota met/not-met cases independent of `--mode`; quota combined with `--tiers highest` still works (orthogonal fields).

Commit order for Phase 5: 5a → 5d (ships right after 5a, only needs the field) → 5b (after ITAD live verification) → 5c (after Humble live verification, likely last).

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test` (and `--extra tui` once Phase 4 lands) then `uv run pytest` after each phase.
- `uv run game-collections schema` after every model change (Phases 0, 5a) — commit regenerated schema files, confirm `tests/test_schema.py` passes.
- After Phase 2/3: run `uv run game-collections eligible steam --source collection` (or `installed`) against real/fixture lists and confirm the printed eligible/skipped set is unchanged from before the migration (regression check that renaming + field-based tier selection doesn't change real sync behavior).
- After Phase 4: manually run `uv run game-collections apply` (with `--extra tui` installed) against the real `lists/` tree, exercise each filter, save a selection, confirm `config/apply-selection.yml` is written and that a subsequent `sync` respects it.
- Phase 5b/5c: do not implement until the live-page verification step confirms the real JSON shape; document findings inline in the eventual commit/PR description.

## Todos

- [x] Phase 0: add tier field to GameList model + schema
- [x] Phase 1: crawlers write bundle.yml/tier-N.yml + populate tier
- [x] Phase 2: adapter reads tier field, retires filename regex
- [x] Phase 3: migrate-tiers CLI subcommand + migrate lists/**
- [x] Phase 4: apply Textual TUI + selection config
- [x] Phase 5a+5d: pick_quota model field + adapter quota matching
- [ ] Phase 5b/5c: verify ITAD byob + Humble Choice pick-count live shapes (gated) *(in progress)*
