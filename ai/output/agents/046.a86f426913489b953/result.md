# Research Report: Bundle "Variation" Files Under `lists/`

## 1. What "variation" means in this codebase

`variation` is **not an existing term in the code** — it does not appear anywhere in `src/`, `lists/*.yml`, or any tracked `*.md` file (confirmed via `grep -rni "variation" src/ lists/ *.md`; the only hits are in `.claude/worktrees/*` scratch files and `ai/query.md`, which is your own planning note: *"I want to merge the bundle variation files into one, grouping the apps inside, flattening the folder structure by a level and D.R.Y.ing duplicated data into a single file..."*).

The actual codebase concept for what you're calling "variation" is **`tier`**. A "bundle" is a `lists/<provider>/bundle/<key>/` directory, and when a bundle has multiple purchase tiers ("Pay $1 for tier 1", "Beat the average for tier 2", "GMG Bronze/Silver/Gold", etc.), each tier gets its own sibling YAML file in that directory: `tier-1.yml`, `tier-2.yml`, ... Single-tier bundles get one `bundle.yml` file instead (no `tier` field). This renaming/normalization is exactly what `migrate_tiers.py` performs (see §4) — it's the prior "flatten/rename" migration, and its docstring literally frames the convention: *"a lone tier becomes `bundle.yml` with no `tier` field; sibling tiers become `tier-<rank>.yml` with an explicit `tier: <rank>` field"*.

There is a second, structurally different kind of "variation" that is **not** file-per-variation: `lists/humblebundle/choice/YYYY-MM.yml` (Humble Choice picks) is a single flat file per month, no tier files — not in scope for this migration.

## 2. Example bundle folders with multiple tier files

Tiers are **cumulative** (each higher tier is a strict superset of games from lower tiers) and each file duplicates the bundle's `name` prefix, full `references` block, and `crawlers` list.

### a) `lists/stacksocial/bundle/2017-04-14_the-nyop-gamer-bundle-3-0/` (2 tiers)
```
tier-1.yml
tier-2.yml
```
`tier-1.yml`:
```yaml
schema: 1
name: The Race Against Time Gamer Bundle — Tier 1
tier: 1
references:
- name: isthereanydeal.com bundle
  url: https://isthereanydeal.com/bundles/5002/
- name: Crawl metadata
  path: ../../../../archives/isthereanydeal/bundle/5002/metadata.json
- name: Crawl source
  path: ../../../../archives/isthereanydeal/bundle/5002/source.json
games:
- name: Little Things Forever
  ids: [unresolved:source:isthereanydeal:5002:little-things-forever]
- name: Dungeon Hearts
  ids: [steam:229520]
```
`tier-2.yml` (same `references` verbatim, cumulative games — adds 4 more on top of tier 1's 2, `tier: 2`).

### b) `lists/indie-royale/bundle/2015-08-17_thy-rewards/` (5 tiers)
```
tier-1.yml … tier-5.yml
```
`tier-1.yml`: `name: Thy Rewards — 10 Bundles Purchased`, `tier: 1`, 1 game.
`tier-5.yml`: `name: Thy Rewards — 30 Bundles Purchased`, `tier: 5`, same `references` block byte-identical to tier-1's, 5 games (cumulative superset including tier-1's game).

### c) `lists/greenmangaming/bundle/2025-10-15_destiny-2-expansion-bundle-2025/` (4 tiers)
```
tier-1.yml … tier-4.yml
```
`tier-1.yml`: `name: 'Destiny 2: Expansion Bundle 2025 — Ghost'`, `tier: 1`, 3 games.
`tier-4.yml`: `name: 'Destiny 2: Expansion Bundle 2025 — Legend'`, `tier: 4`, same `references` (identical ITAD bundle 15489 URLs/paths), 9 games — the first 3 are byte-identical entries to tier-1's.

**Duplication observed across all examples:** entire `references` array (3 entries: bundle URL + 2 archive paths) repeated verbatim per tier file; `name` repeats a common prefix + tier-specific suffix; `crawlers` list repeated; and every lower tier's `games` entries are word-for-word duplicated into every higher tier (cumulative membership), so a game present in all N tiers is written out N times across the directory.

Other providers with the same pattern: `lists/vodo/bundle/2013-10-30_bigbrother/` (tier-1/2), `lists/bundle-dragon/bundle/2013-10-02_bigbad/` (tier-1..3), `lists/indie-bundle/bundle/*/tier-1.yml,tier-2.yml` (many), `lists/wingamestore`, `lists/itch-io`, `lists/humble-weekly-bundle`, etc. — dozens of bundle directories repo-wide follow this exact shape.

## 3. `src/game_collections/models.py` (full, 202 lines)

Key models:
- `QualifiedGameId` — `provider:value` pair, parsed/rendered via `parse()`/`compact()`.
- `GameGroup(id, name)` — provenance link when one source item splits into several `Game`s.
- `Game(StrictModel)`:
  ```python
  class Game(StrictModel):
      name: NonEmptyString
      ids: list[NonEmptyString] = Field(min_length=1)
      group: GameGroup | None = None
      requires: list[NonEmptyString] = Field(default_factory=list)
  ```
  No `tier` field on `Game` — tier currently lives only at the list level.
- `Reference(name, path, url)` — a source/archive pointer; requires at least one of `path`/`url`.
- `duplicate_qualified_ids(games)` — helper flagging IDs reused across `Game`s in a list.
- `GameList(StrictModel)` — the whole-file schema:
  ```python
  class GameList(StrictModel):
      schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
      name: NonEmptyString
      tier: Annotated[int, Field(ge=1)] | None = None
      pick_quota: Annotated[int, Field(ge=1)] | None = None
      references: list[Reference] = Field(default_factory=list)
      crawlers: list[NonEmptyString] = Field(default_factory=list)
      games: list[Game] = Field(min_length=1)
      invalid: list[Game] = Field(default_factory=list)
  ```
  Validators enforce: no duplicate game names (casefolded), no duplicate qualified IDs across `games`, consistent `group.name` per `group.id`, and `pick_quota <= len(games)`.
- `validate_list_id(value)` — regex-validates the path-derived logical ID (`LIST_ID_PATTERN`).

**Implication for a merge migration:** `tier` is currently a single optional int on the *list*, not on `Game`. To DRY variations into one file per bundle while still recording "which variation(s) a game belongs to," you'd need either a new per-`Game` field (e.g. `tiers: list[int]` or `variations: list[str]`) or a restructured `GameList` schema — `Game` and `GameList` as they stand have no field for "membership in a subset of the list."

## 4. `src/game_collections/migrate_tiers.py` (full, 170 lines) — the precedent migration

Docstring: *"One-time migration: rename tier-shaped bundle lists and populate `tier`. Renames every already-generated `lists/<provider>/bundle/<key>/*.yml` bundle directory to the current writer convention... so on-disk lists match what the crawlers in `sources/*/crawler.py` write going forward and the Steam adapter's tier selection no longer depends on any file predating that convention."*

Structure/logic (this is the template a "merge variations" migration should mirror):
- `TIER_STEM_PATTERN` / `ITEM_BUNDLE_STEM_PATTERN` regexes recognize current/legacy filename shapes.
- `TierMigrationError(ValueError)` — raised when a directory can't be unambiguously migrated.
- `TierMigrationStep` dataclass — `old_path`, `new_path`, `tier` (the per-file plan unit).
- `step_would_change(step, lists_root)` — idempotency check (load current file, compare to planned tier/path).
- `discover_bundle_directories(lists_root)` — walks `<provider>/bundle/<key>/` dirs (only under a literal `bundle/` folder; skips flat per-offer sources with no subdirectory, e.g. `dailyindiegame`).
- `_identifier_order_from_metadata(sample_path, lists_root)` — for legacy files without numeric ordering (e.g. GMG's old `bronze.yml`/`gold.yml`), resolves the ordering by reading the linked archive's `metadata.json` `tiers` array via the file's own `Crawl metadata` reference.
- `plan_bundle_directory(bundle_dir, lists_root)` — core decision tree:
  1. 1 file → rename to `bundle.yml`, `tier=None`.
  2. All files match `tier-N.yml` → keep names, just set `tier=N` field.
  3. All files match legacy `(entire-)?N-item-bundle.yml` → rename to `tier-N.yml`, ranked by item count (entire treated with highest count semantics).
  4. Otherwise (arbitrary names) → resolve rank via archive metadata's `tiers` order, rename to `tier-<rank>.yml`.
- `plan_migration(lists_root)` — flattens `plan_bundle_directory` across every discovered bundle dir into a `list[TierMigrationStep]`.
- `apply_migration_step(step, lists_root, repository_root)` — loads+validates via `load_game_list`, no-ops if nothing changes, otherwise `model_copy(update={"tier": step.tier})`, renders via `render_game_list_yaml`, `atomic_write`s to `new_path`, re-validates the written file, and `unlink()`s the old path if renamed.

Tests (`tests/test_migrate_tiers.py`, 175 lines) cover: single→`bundle.yml`; multi numeric passthrough; legacy Humble `N-item-bundle` renumbering; legacy GMG identifier renumbering via archive metadata; unresolvable-without-metadata raises `TierMigrationError`; **idempotency** (re-running produces byte-identical output); and an end-to-end check that migration is what makes `SteamAdapter`'s `tier_mode="highest"` selection actually drop lower tiers (see §5's note on adapter tier semantics — this is the load-bearing consumer of the per-file `tier` field).

## 5. `src/game_collections/lists.py` (full, 102 lines) — path-derived ID & discovery

- `derive_list_id(path, lists_root)` — the list's logical ID is `relative_to(lists_root)` with `.yml` suffix stripped, POSIX-ified, validated via `validate_list_id`. So `lists/greenmangaming/bundle/2025-10-15_destiny-2-expansion-bundle-2025/tier-1.yml` → id `greenmangaming/bundle/2025-10-15_destiny-2-expansion-bundle-2025/tier-1`. **Flattening a folder level will directly change every affected list's ID** (e.g. to `greenmangaming/bundle/2025-10-15_destiny-2-expansion-bundle-2025`), which matters for anything that persists/references list IDs elsewhere (Steam collection naming, `apply/config.py` selections, etc. — worth checking those consumers before merging).
- `load_game_list(path, lists_root)` — reads YAML via `yaml.safe_load`, requires a top-level dict, validates through `GameList.model_validate`, wraps into `LoadedGameList(id, path, data)`.
- `discover_game_lists(lists_root, on_progress=None)` — `lists_root.rglob("*.yml")` sorted, loads every file, then rejects case-insensitive/logical ID collisions.

**Important downstream coupling found while investigating (`src/game_collections/launchers/steam/adapter.py`, `_selected_list_ids`, lines ~243–269):** `tier_mode="highest"` groups eligibility results by `parent = result.list_id.rpartition("/")[0]` (i.e., the *bundle directory*) and `rank = result.tier`, keeping only the highest-tier list ID that's still eligible per `(parent, rank)` bucket; it raises `ValueError` on an "ambiguous tier rank" collision. **This is the load-bearing reason the current design keeps one list/eligibility-evaluation per tier file** — each tier's `games` list is evaluated independently for ownership completion, and "highest owned tier" selection depends on there being multiple sibling list IDs sharing a parent. Any merge-into-one-file migration needs to either preserve equivalent per-variation eligibility semantics inside the new single-file schema, or the Steam adapter's tier logic (and `CollectionEligibility.tier`, `PlannedCollectionChange`, `steam_collection_id(result.list_id)`) needs a companion redesign — this is the crux of the "make it work" side of your `/plan` note (*"a game shall list in which variation the game is included in"*), since eligibility today is computed per-file/per-tier, not per-game-within-a-merged-file.

## 6. `sources/README.md` and source writers producing tier folders

`grep -rn "tier" src/game_collections/sources/README.md` shows tier-file writing is documented per source:
- **Humble** (`sources/humblebundle/crawler.py`): *"`write_humble_offer(...)` ... and one `lists/humblebundle/...` YAML per advertised cumulative tier (`choice/YYYY-MM.yml`, or `bundle/<key>/<n>-item-bundle.yml` with `entire-<n>-item-bundle.yml` for tier 0)."* — writer code (lines ~304–383) builds `tiers_with_games: list[tuple[HumbleTier, list[Game]]]`, sorts ascending by item count, and for each writes `tier-<rank>.yml` (or `bundle.yml`/`None` tier when only one non-empty tier), each with its own full `references`/`crawlers`/`games`.
- **GreenManGaming** (`sources/greenmangaming/crawler.py`, `write_gmg_offer`, lines 252–304, read in full): builds `tiers_with_games` by deduping items already seen in a lower tier (`seen_ids`) then extending — i.e. the *crawler* already computes tier-exclusive vs. cumulative at write time — then for each tier writes either `bundle.yml` (single tier) or `tier-<rank>.yml`, each `GameList` re-declaring `name=f"{archive.name} — {tier.name}"`, the same 3 `references` (bundle URL + metadata path + source path, only the relative `path` differs per-file location but content is identical), `crawlers=["greenmangaming"]`, and the full cumulative `games` list per tier.
- **isthereanydeal** (`sources/isthereanydeal/crawler.py`, `write_itad_offer`): *"one `lists/<provider>/bundle/<date>_<slug>/<tier-id>.yml` per cumulative tier"* — same shape, tier display names from `tier.note` (e.g. "Bronze"/"Silver"/"Gold") or `entire-{n}-item-bundle` convention or generic `Tier N`.
- **DailyIndieGame**: explicitly *not* tiered ("flatter than Humble's shape since there's one flat price tier per bundle... and no resolver-produced fields") — flat `bundle/<machine_name>.yml`, no subdirectory, so `migrate_tiers.discover_bundle_directories` correctly skips it (requires a literal `bundle/` folder with siblings).

So: **the crawlers are the current source of the duplication** — they intentionally write one fully-self-contained `GameList` YAML per cumulative tier, with `references`/`crawlers`/`name`-prefix duplicated by construction. Any new "merge variations" migration will need a matching update to these `write_*_offer` functions (GMG's `write_gmg_offer`, Humble's `write_humble_offer`, ITAD's `write_itad_offer`) so future crawls don't re-introduce the split-file format the migration just collapsed — otherwise the migration is undone on the next `crawl` run, exactly the same "keep new crawls compatible" concern `migrate_tiers.py`'s docstring calls out.

## 7. Existing merge/combine tooling

`grep -rln "merge" src/` hits (excluding `.claude` worktrees):
- `src/game_collections/sources/common.py` — the real prior art for "merging" list content:
  - `merge_references(existing, fresh)` (line 75): unions two lists' `references`, preserving `existing`'s items first then appending any new ones from `fresh` not already present (equality-based dedup).
  - `merge_crawlers(existing, fresh)` (line 90): same pattern for the `crawlers: list[str]` field, mirroring `merge_references`.
  - `merge_game_list(existing, fresh, *, authoritative=False)` (line 184): the closest existing analog to a "combine lists" operation — used when re-crawling an already-written list file to combine an existing on-disk `GameList` with a freshly-scraped one. Merges `references`/`crawlers` via the two helpers above; when non-authoritative, keeps `fresh.games` order but prefers `existing`'s copy of each (by casefolded name) plus any `existing`-only games appended; when authoritative, does ID-based reconciliation into `merged_games`/`candidates` (asserts no duplicate qualified IDs post-merge, quarantines unmatched as `invalid`).
  - Used in `sources/isthereanydeal/crawler.py` (lines ~526–527: `merge_references(game_list, fresh_stub)`, `merge_crawlers(game_list, fresh_stub)`) for its dedup/re-crawl path.
- `git_ops.py` — unrelated, this is literal `git merge`/unmerged-path handling for the CLI's git integration (`_unmerged_paths`, conflict detection), not list-merging.
- `isthereanydeal/resolver.py` line 130–139 — `merged_ids` is local variable name for combining a game's own archive `ids` with newly resolved storefront IDs; not a list-file merge.
- **No existing tool merges *tier/variation sibling files within one bundle directory into one file*** — `merge_game_list`/`merge_references`/`merge_crawlers` operate on "existing on-disk list" vs. "freshly scraped list" (same file), not on "N sibling files → 1 file." These are still the right low-level primitives to reuse (especially `merge_references`/`merge_crawlers`'s dedup-by-equality pattern) for building a new `merge_bundle_variations.py` (or similar) migration module structured like `migrate_tiers.py`.

## Summary of concrete gaps to design around

1. `Game` (models.py) has no field to record "which variation(s) this game belongs to" — needs a new field (e.g. `tiers: list[int]` or `variations: list[str]`, non-empty, validated).
2. `GameList.tier` is currently list-level and singular; merging removes the 1-tier-per-file mapping it depends on.
3. `lists.py`'s path-derived IDs mean flattening a folder level changes every affected list's logical ID (`.../tier-1` → `.../<bundle-key>` or similar) — check all consumers of list IDs (Steam collection naming `steam_collection_id`, `apply/config.py` selection state, any persisted references to old IDs).
4. `SteamAdapter._selected_list_ids`'s `tier_mode="highest"` logic (adapter.py ~243-269) is built entirely around one-list-id-per-tier + `rpartition("/")` parent grouping; this needs a redesign to work against a merged single-file-per-bundle model (e.g., per-game highest-variation-owned logic instead of per-file).
5. The three writer functions (`write_gmg_offer`, `write_humble_offer`, `write_itad_offer`) currently emit the very split-file/duplicated-reference format you want migrated away from — they'll need updating in lockstep, or every future crawl will regenerate the old fragmented shape.
6. `migrate_tiers.py` + `tests/test_migrate_tiers.py` (§4) is the closest and most directly reusable template for structure (discover → plan → `TierMigrationError` → apply with idempotency/no-op checks via `step_would_change`-style logic, atomic write + re-validate + unlink old files).
7. `sources/common.py`'s `merge_references`/`merge_crawlers` (dedup-by-equality union) are directly reusable for combining the duplicated `references`/`crawlers` arrays across a bundle's variation files into one.