Design a detailed, stepwise implementation plan for four related features in the `game_collections` Python repo (Pydantic-validated YAML game lists + Steam launcher sync, described in CLAUDE.md). I already did deep exploration; here's everything you need — do not re-explore unless something below is unclear from a quick file check.

## Context already gathered

**Tier file naming today** (four sources under `src/game_collections/sources/`):
- `humblebundle/crawler.py:247-306` `write_humble_offer`: for `kind="choice"` writes single `{key}.yml` (no tiers). For `kind="bundle"`, writes `entire-{item_count}-item-bundle.yml` for tier index 0, else `{item_count}-item-bundle.yml` (item_count = cumulative count, not a small index).
- `greenmangaming/crawler.py:233-275` `write_gmg_offer`: filename = `{tier.identifier}.yml`, where `identifier` is scraped verbatim off GMG's HTML `data-upgrade-tier-id` attribute (parser.py:213-253) — happens to already look like `tier-1`, `tier-2`, etc. on the live site, but that's not code-constructed.
- `isthereanydeal/crawler.py:412-464` `write_itad_offer`: filename = `{tier.identifier}.yml`, where identifier is code-constructed as `f"tier-{len(tiers) + 1}"` in `parser.py` (`parse_bundle_detail_json` line ~442, `parse_bundle_detail_page` line ~618) — always `tier-1`, `tier-2`, ... 1-based, single or multi-tier alike.
- `dailyindiegame/crawler.py:253-289`: no tier concept at all, one list per bundle named by `machine_name`.
- Legacy on-disk files also include old `tier-1.yml`/`tier-2.yml` Humble names from a prior naming scheme (already superseded in code, only lingering as committed files).

**Adapter tier-ordering parser** (`src/game_collections/launchers/steam/adapter.py`):
- `TIER_STEM_PATTERN = re.compile(r"^tier-(?P<rank>[0-9]+)$")`
- `ITEM_BUNDLE_STEM_PATTERN = re.compile(r"^(?:entire-)?(?P<rank>[0-9]+)-item-bundle$")`
- `_tier_identity(list_id)` (lines 299-309) splits `list_id` on last `/` into `(parent, stem)`, matches stem against those two regexes, returns `(parent, rank)` or `None` (tier-less, always included).
- `_selected_list_ids()` (lines 183-217) groups eligible lists by `parent`, and for `--tiers highest` keeps only the highest-rank sibling per parent group; raises on duplicate `(parent, rank)`. This is currently the *only* consumer of tier ordering, and it's 100% filename-derived.

**Public schema** (`src/game_collections/models.py`, ~132 lines):
- `GameList(StrictModel)`: `schema_version` (aliased `schema`, `Literal[1]`), `name`, `references: list[Reference]`, `games: list[Game] (min_length=1)`. `StrictModel` has `extra="forbid"` — no field can be added without being explicitly declared.
- `Game(StrictModel)`: `name`, `ids: list[NonEmptyString]` (qualified `provider:value` strings), dedup validator.
- `Reference(StrictModel)`: `name`, optional `path`/`url`, validator requires at least one target.
- No `tier` field exists anywhere in this public model today. Each source's own *archive* model (e.g. `HumbleTier`, `GmgTier`, `ItadTier`, all with `identifier`/`name`/`item_count`) already tracks tier metadata, but only in `archives/<source>/.../metadata.json`, never denormalized into the list YAML.
- JSON Schema files (`schemas/game-list.schema.json` + one per source archive) are generated from these Pydantic models via `game-collections schema`; `tests/test_schema.py` detects drift — any model field change requires regenerating and committing the schema.

**Sync/apply CLI flow** (`src/game_collections/cli.py`, `src/game_collections/launchers/base.py`, `src/game_collections/launchers/steam/adapter.py`, `src/game_collections/launchers/steam/io.py`):
- `sync_command` (cli.py:790-847): builds `SteamAdapter` via `_steam_adapter()` helper (cli.py:659-717, resolves `--source api|installed|collection`), calls `adapter.plan(discover_game_lists(...))` → `SyncPlan`, prints via `_print_plan`, then if `--apply`: `adapter.stage(plan, output_dir)` (writes candidates/backups/manifest to a timestamped dir, never touches real Steam files) → `typer.confirm(...)` → `adapter.apply(staged, confirm_callback)` (re-validates everything, requires Steam stopped, requires typed `REPLACE`, atomic replace + rollback + verification).
- `SyncPlan` (base.py:53-61): `launcher`, `account`, `eligibility: list[CollectionEligibility]`, `changes: list[PlannedCollectionChange]`. `CollectionEligibility` (base.py:16-26): `list_id`, `name`, `eligible`, `owned_ids`, `missing_ids`, `unsupported_ids`. **No bundle source/date/item-count/tier metadata anywhere in this plan** — a picker UI needs that, and today it's only derivable from (a) the `list_id` path convention, or (b) separately loading the linked archive `metadata.json` via each list's `Reference.path`.
- `LoadedGameList` (lists.py:21-29): `id`, `path`, `data: GameList` — same gap, no denormalized bundle metadata.
- No existing TUI/interactive-selection library in `pyproject.toml` (only `httpx`, `markdownify`, `patchright`, `pydantic`, `PyYAML`, `typer`, `vdf`). All existing interactivity is plain `typer.prompt`/`typer.confirm` (e.g. `_choose_store_candidate` cli.py:171-198 — numbered list + prompt loop, no arrow-key menus).
- `steam_collection_id()` (io.py:786-791) derives a stable Steam collection id from `list_id` via `uc-<base64(sha256(list_id)[:9])>` — relevant since a future config file selecting/deselecting bundles by `list_id` would key off this same stable id space.

**BYOB ("build your own bundle", pick N of M) — current state**:
- Humble Choice (`humblebundle/parser.py:468-577` `parse_choice_page`) always builds **one tier covering the whole monthly pool**, `item_count=len(items)`; there is no "how many you're allowed to pick" field parsed or modeled anywhere (`HumbleTier` in `humblebundle/models.py:68-85` only has cumulative `item_count`+`items`, no pick-quota). Tests (`test_humblebundle_parser.py`, `test_humblebundle_crawler.py`) confirm this pool-as-one-list assumption.
- ITAD (`isthereanydeal/models.py`) already has `ItadListSummary.byob: bool` (line ~165, stored but unused) and `ItadTier` docstring explicitly says BYOB bundles render as "a single synthetic tier covering every game... with no fixed price... the per-game marginal pricing table isn't modeled." `isthereanydeal/parser.py:528-534` docstring says BYOB and flat-price bundles are deliberately collapsed to one tier the same way.
- `ai/plans/011_isthereanydeal-parse-the-embedded-var-page-json-instead-of-r.md:44-49` documents the real upstream shape that would be needed: ITAD's embedded JSON has `liveData.byob: [{"count": N, "price": [amount_cents, "CUR"]}, ...]` — i.e. real "pick N games for $price" tiers — and explicitly flags this as "already intentionally unmodeled today."
- User's own backlog note (`ai/query.md:1005`): "We need to add support for BYOB... where those would allow for the usual 3-4 game selections to match. Ideas?"
- Nothing in the repo models "own N of M" ownership; `sync steam --mode any/all` (adapter.py `evaluate()`) is the closest existing quantity-adjacent concept but is list-wide all-or-any per game, not a quota/threshold.
- Real example on disk: `lists/fanatical/bundle/2025-06-25_build-your-own-point-and-click-collection/tier-1.yml` — 14 games flat, no pick-count metadata, matches today's pool-only representation.

## User's actual request (verbatim, 4 asks)

1. If a bundle only ever produces a single tier, name that file `bundle.yml` instead of `tier-1.yml`/`1-item-bundle.yml`/etc. (stop having a pointless "tier 1 of 1").
2. Bundle downloaders should add a `tier: int` field (1-based) to the list YAML itself, so tier ordering is explicit data, not filename-parsed. This must replace `adapter.py`'s current filename-regex tier-ordering logic (`_tier_identity`, `TIER_STEM_PATTERN`, `ITEM_BUNDLE_STEM_PATTERN`) as the source of truth going forward.
3. A new TUI command `game-collections apply` (graphical variant of `sync`) that lets the user interactively select which bundles to sync, with filters: by bundle-type/source (humble/fanatical/...), by item-count range (e.g. hide bundles with ≤2 items), by manual per-entry toggle, and by date (before/after/range). The result of that selection is written as a config file, committed into the repo, and also copied into the backup/staging folder used by `--apply`.
4. Support BYOB bundles properly — model the "pick N of M games" mechanic (not just dump the whole pool as one list) and figure out how ownership/sync matching should work for it (a buyer who picked N of M only owns N, but a fresh list-checkout later might have games added/removed from the pool).

## User's decisions on scope (already confirmed via AskUserQuestion — do not re-ask these)

- **Tier migration**: migrate every already-generated list file now (not forward-only) — a one-time migration script/step must add `tier:` (and rename to `bundle.yml` where applicable) to every existing list file across all sources, updating any archive `references` that point at renamed paths if applicable.
- **TUI library**: use **Textual** (new dependency) for the `apply` picker — full-screen checkboxes/scrollable list/filter inputs.
- **BYOB depth**: user said "all of the above, step after step" — meaning produce a full implementation plan (concrete schema changes, scraper changes for ITAD `byob` + Humble Choice pick-count, and sync/adapter matching changes), but structured as sequential steps/phases (this can be its own phase after the other 3, doesn't have to land in the same commit).

## What I need from you

Produce a concrete, stepwise implementation plan covering all 4 features, ordered so each phase is independently shippable/testable (this repo's CLAUDE.md requires a commit per completed task). For each phase, name:
- Exact files to modify/add, and the specific model/function changes (e.g. exact new Pydantic fields with types, exact regex/parsing replaced, exact CLI options added).
- How existing tests (`tests/test_<source>_crawler.py`, `test_schema.py`, `tests/test_steam_adapter.py`, etc.) need updating, and what new tests are needed.
- Migration script approach for existing `lists/**/*.yml` files (single script? per-source? how does it determine tier number and single-vs-multi-tier for already-committed bundles, given each source's current naming convention above?).
- For the Textual TUI (`apply`): what new module(s) it lives in, how it gets bundle metadata (source/date/item-count) it needs but that currently only lives in path convention + archive JSON — recommend either denormalizing onto `GameList`/`LoadedGameList` or building a lightweight loader that stitches list+archive metadata for the picker only, and how the selection config file schema should look and where it's read by `sync`/`apply` internals reusing `SteamAdapter.plan`/`stage`/`apply`.
- For BYOB: propose concrete new model field(s) (e.g. on `GameList` or a new type) representing a pick quota, how Humble Choice's parser/crawler would populate it (need it to actually parse the real "how many can be picked" count — investigate what field of the embedded Humble JSON would carry it, if you can infer it from existing HumbleTier/parser code, and flag if this needs live-verification against the real page before implementing per this repo's "verify, don't guess external shapes" convention), how ITAD's `byob` tiers list would populate it, and how `sync steam` ownership matching (`SteamAdapter.evaluate`) would need to change to treat these lists as "eligible if owned_count >= quota" instead of all/any.

Do not implement anything — output the plan as structured text (phases, files, changes) for me to fold into a final plan.md. Flag any open design questions or places where you'd want to verify live external data before committing to a schema, per this repo's existing convention (see CLAUDE.md memory: "Verify, don't guess external shapes").