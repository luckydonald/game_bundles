# Implementation Plan: Tier Naming, Explicit Tier Field, Textual `apply` TUI, and BYOB Support

## Phase 0 — Shared groundwork (schema + regex retirement prep)

Nothing user-visible yet; this phase adds the `tier` field to the public schema and updates the regenerated JSON Schema/tests, so every later phase can just consume it.

**Files:**
- `src/game_collections/models.py` — add to `GameList`:
  ```python
  tier: Annotated[int, Field(ge=1)] | None = None
  ```
  Placed after `name`, before `references` (or wherever field order convention favors — check existing declaration order in file). No validator needed beyond `ge=1`; multi-tier bundles get 1-based tier numbers, single-tier/no-tier lists get `None` (omitted key in YAML rather than `tier: 1` for every single-tier list — this matches "stop having a pointless tier 1 of 1" spirit for both filename *and* field). Confirm with user/self-consistency: **decision needed** — do single-tier bundles get `tier: 1` explicitly (simpler, uniform) or omit the field entirely (matches "no pointless tier of 1")? Given the ask #1 (`bundle.yml` for single tier) explicitly wants to eliminate the "1 of 1" concept, the field should also be omitted (`None`) for single-tier bundles and only present (starting at 1) when a bundle actually has ≥2 tiers. This keeps YAML clean and keeps `tier` semantically meaning "my rank among siblings," not "a tautological 1."
- `schemas/game-list.schema.json` — regenerate via `game-collections schema` after the model change (do this as part of the same commit; `tests/test_schema.py` enforces no drift).
- `tests/test_schema.py` — extend/verify it picks up the new field automatically (it diffs generated vs. committed schema, so likely just needs regeneration, not a code change — check its assertions to be sure it doesn't hardcode a field list).
- `tests/test_lists.py` / any `GameList`-construction fixtures — check for `extra="forbid"` strict round-trip tests that construct a `GameList` with a fixed field set; add a case with `tier` set and one with it omitted.

**Open design question:** should `tier` be an int rank (1, 2, 3…) or should it also carry `of` (total tier count), e.g. `tier: 2` alone vs. a small `TierInfo` object `{rank: 2, of: 3}`? The adapter only needs rank + a way to group siblings (currently the parent directory does that job via `list_id` grouping) and "highest" selection, so a bare `int` is sufficient and matches the ask literally ("add a `tier: int` field"). Recommend bare `int`.

---

## Phase 1 — Rename single-tier bundle files to `bundle.yml` (ask #1) + populate `tier:` going forward (ask #2, writer side)

This is the forward-looking crawler change. Do NOT touch the adapter's regex yet in this phase (keep `_tier_identity` as a fallback so existing already-migrated-by-Phase-3 files and not-yet-migrated legacy files both still resolve) — swapping the adapter to `tier`-field-only happens in Phase 2, after writers exist to populate it, but logically Phase 1 and Phase 2 should ship together since Phase 2 depends on Phase 1's output. Sequence as sub-steps of one phase, two commits:

**1a. Humble (`src/game_collections/sources/humblebundle/crawler.py`, `write_humble_offer` lines ~247-306):**
- Replace the `entire-{item_count}-item-bundle.yml` / `{item_count}-item-bundle.yml` naming with:
  - If `len(archive.tiers) == 1` (this only applies to `kind="bundle"`; `kind="choice"` already writes a single fixed `{key}.yml` and is unaffected): filename = `bundle.yml`, no `tier` field set on the `GameList`.
  - If `len(archive.tiers) > 1`: filename = `tier-{rank}.yml` where `rank = index + 1` (1-based enumerate index, NOT cumulative `item_count` — this also fixes the pre-existing oddity that the old filename used cumulative item count instead of a small ordinal), and set `tier=rank` on the constructed `GameList`.
- Concretely: replace
  ```python
  if archive.kind == "choice":
      path = list_directory / f"{key}.yml"
  else:
      prefix = "entire-" if index == 0 else ""
      path = list_directory / f"{prefix}{tier.item_count}-item-bundle.yml"
  ```
  with logic branching on `len(archive.tiers)` and passing `tier=index + 1 if len(archive.tiers) > 1 else None` into the `GameList(...)` constructor call just below.

**1b. GMG (`src/game_collections/sources/greenmangaming/crawler.py`, `write_gmg_offer` lines ~233-275):**
- Currently `path = list_directory / f"{tier.identifier}.yml"` where `identifier` is scraped HTML text (happens to look like `tier-1`). Replace with: if `len(archive.tiers) == 1`, filename `bundle.yml`, `tier=None`; else filename `tier-{index+1}.yml` (code-constructed ordinal, not the scraped `identifier` — stop trusting scraped text for the filename now that we have a first-class field) and `tier=index+1`.
- Note: `tier.identifier` (scraped) can still be kept in the archive JSON for reference/debug but should no longer drive the public list's filename.

**1c. ITAD (`src/game_collections/sources/isthereanydeal/crawler.py`, `write_itad_offer` lines ~412-464):**
- Currently `path = list_directory / f"{tier.identifier}.yml"` where identifier is code-built `f"tier-{len(tiers)+1}"` from parser.py. Same change: single tier → `bundle.yml` + `tier=None`; multi-tier → `tier-{index+1}.yml` + `tier=index+1`. (Here the ordinal already matches `tier.identifier`'s numbering, so this is mostly a rename-driving-condition change, not a numbering change — worth a quick check that `enumerate(archive.tiers)` order matches `tier.identifier` order, i.e. tiers are stored in ascending order already; grep confirms `parse_bundle_detail_json`/`parse_bundle_detail_page` build tiers in order and identifier is assigned via running length, so index and (identifier-1) should coincide — verify this specifically before implementing, cheap to check with an existing fixture test.)

**1d. dailyindiegame:** no tier concept, no change needed (confirmed: one list per bundle, no tiers array).

**Tests to update per source:**
- `tests/test_humblebundle_crawler.py` — update expected filenames (`entire-N-item-bundle.yml`/`N-item-bundle.yml` → `bundle.yml` or `tier-N.yml`), add assertion on `GameList.tier` value (None vs int) for both single- and multi-tier fixture bundles.
- `tests/test_greenmangaming_crawler.py` — same pattern.
- `tests/test_isthereanydeal_crawler.py` — same pattern, plus the ordering-assumption check above.
- No dailyindiegame crawler test change expected.

**Commit boundary:** one commit per source crawler change (3 commits) is reasonable given CLAUDE.md's "commit per completed task," or one combined commit if the team prefers atomic cross-source consistency — recommend 3 separate commits (one per source) since they're independently testable and this mirrors the existing per-source module boundary.

---

## Phase 2 — Adapter reads `tier` field, retires filename regexes (ask #2, reader side)

**Files:**
- `src/game_collections/lists.py` — `LoadedGameList` already exposes `.data: GameList`, so `game_list.data.tier` is directly available; no change needed here beyond confirming `GameList.tier` round-trips through `discover_game_lists`.
- `src/game_collections/launchers/steam/adapter.py`:
  - Delete `TIER_STEM_PATTERN`, `ITEM_BUNDLE_STEM_PATTERN`, and `_tier_identity()` (lines ~299-309 and the module-level regex constants near the top — grep their definitions to confirm exact line numbers before removal).
  - `_selected_list_ids()` (lines 183-217) currently calls `_tier_identity(result.list_id)` to get `(parent, rank)`. Since `CollectionEligibility` doesn't currently carry the list's `tier` value or its parent grouping, this method needs either (a) a new parameter carrying `dict[str, LoadedGameList]` keyed by `list_id` so it can look up `.data.tier`, or (b) `CollectionEligibility` gains an optional `tier: int | None` field populated in `evaluate()`. **Recommend (b)** — cleaner, keeps `_selected_list_ids` pure over `eligibility` alone like today.
    - `src/game_collections/launchers/base.py` `CollectionEligibility` — add `tier: int | None = None`.
    - `adapter.py` `evaluate()` (wherever `CollectionEligibility(...)` is constructed) — pass `tier=game_list.data.tier`.
    - Parent-grouping: today "parent" was derived from `list_id.rpartition("/")[0]` (i.e., the containing directory). With the field-based approach, the grouping key must still be "siblings within the same bundle directory" since `tier` alone (an int) doesn't encode which bundle it belongs to — a `tier: 2` in one bundle directory is unrelated to `tier: 2` in another. So `_selected_list_ids` still needs the directory-prefix of `list_id` as the grouping key, but ONLY uses it for grouping siblings — not for parsing the rank out of the filename. Replace the `_tier_identity()` call with: `parent = result.list_id.rpartition("/")[0]`, `rank = result.tier` (from the new field); if `rank is None`, treat as tier-less exactly as before (always included, no grouping).
  - Update `_managed_deletions` and anywhere else `_tier_identity` might be referenced — grep confirms it's only used in `_selected_list_ids`.

**Tests:**
- `tests/test_steam_adapter.py` — replace any fixtures that construct `LoadedGameList`/YAML with tier-bearing filenames (`tier-1.yml`, `N-item-bundle.yml`) to instead set `tier=` in the `GameList` data directly; add a regression test that a `bundle.yml`-named single-tier list (with `tier=None`) is still treated as "always eligible, no rank conflict" and a duplicate-rank-within-same-directory test still raises `ValueError` using the field instead of filename.
- Search test fixtures/dirs for hardcoded filenames referencing old tier naming (`grep -rn "tier-1.yml\|item-bundle" tests/`) and update.

**Commit boundary:** one commit for adapter+base changes, one for test updates (or combined — adapter change without tests updated will fail CI, so likely one commit is more practical given tests must pass).

---

## Phase 3 — Migration script for already-committed list files (ask #2/#1, backward migration)

Per the confirmed scope decision: migrate everything now, single pass across all sources.

**New file:** `scripts/migrate_tier_filenames.py` (or under an existing `scripts/`/`tools/` dir if one exists — check `ls scripts/ tools/` first; if none exists, `scripts/` is a reasonable new location, or as a hidden `game-collections` CLI subcommand `game-collections migrate-tiers` in `cli.py` if the repo prefers all tooling behind the single CLI entrypoint — **recommend the CLI-subcommand form** since `cli.py` already hosts `schema`, `validate`, `search`, etc., keeping one entrypoint, and it can be deleted/hidden after the one-time migration lands, or kept as an idempotent `--check` tool).

**Design of the migration logic**, per source directory convention:
- **Humble bundles** (`lists/humblebundle/bundle/<key>/`): glob `entire-*-item-bundle.yml` and `*-item-bundle.yml` within each bundle directory. If exactly one file matches (single tier) → rename to `bundle.yml`, no `tier:` field added. If multiple match → sort by the embedded item-count (need to reconstruct original ordinal ordering: the `entire-` prefixed file is always rank 1, and the rest need to be ordered by ascending cumulative item count since that's how they were originally enumerated) → rename to `tier-1.yml`, `tier-2.yml`, ... in that order, adding `tier: <rank>` into each YAML's top-level mapping.
  - Legacy pre-existing `tier-1.yml`/`tier-2.yml` files (from the old naming scheme, called out as "already superseded in code, only lingering as committed files") also need `tier:` fields added even though their filenames don't change — same directory glob should also match already-`tier-N.yml`-named files and just inject the field, not rename.
- **GMG** (`lists/greenmangaming/bundle/<slug>/`): glob `tier-*.yml` (today already named this way from the scraped identifier). If exactly one file → rename to `bundle.yml`, no field. If multiple → sort by the numeric suffix already in the filename (since GMG's existing naming is coincidentally ordinal already) → keep names, add `tier: N` field matching the existing numeric suffix (or renumber if the existing scraped numbering isn't contiguous from 1 — verify with `find lists/greenmangaming -name 'tier-*.yml' | sort` first).
- **ITAD** (`lists/<provider>/bundle/<slug>/`, note ITAD writes into *each provider's own* list tree per the crawler docstring, not under `isthereanydeal/`): glob `tier-*.yml` per bundle directory, same approach as GMG (numeric suffix is already the rank since `parser.py` code-constructs it as `f"tier-{len(tiers)+1}"`).
- **Single-tier heuristic, generalized:** for every bundle directory (any source) that after globbing has exactly one tier-pattern-matching file, rename to `bundle.yml` and strip/omit `tier`. For any directory with ≥2, renumber 1..N by whatever each source's existing ordering convention implies (documented above) and inject `tier: N`.
- **Archive `references` updates:** each list YAML has a `Reference(name="Crawl metadata"/"Crawl source", path=...)` computed via `os.path.relpath` — these are relative paths pointing at the archive JSON, unaffected by renaming the list file itself as long as the directory doesn't move (only the leaf filename changes) — recompute `relpath` only if the migration also changes directory depth, which it doesn't here. Confirm no *other* file references list files by exact filename (grep `entire-.*-item-bundle\|tier-[0-9].*\.yml` across `lists/**/*.yml` and `archives/**/*.json` for any list referencing another list — unlikely but worth a repo-wide grep before running).
- **Idempotency & safety:** script should be dry-run by default (`--apply` flag to actually write), use the same `atomic_write` helper already used by crawlers (`from game_collections.io import atomic_write` — check actual import path), and validate the resulting YAML against `GameList` (parse-after-write round trip) before considering a file migrated, aborting the whole batch on any single validation failure (matches existing "atomic, verify, never partially write" convention seen in `io.py`'s stage/apply).

**Tests:** `tests/test_migrate_tiers.py` (new) — build a temp `lists/` tree mimicking each source's real pre-migration layout (single-tier and multi-tier cases per source, plus a legacy `tier-1.yml` Humble case), run the migration, assert final filenames/fields and that `discover_game_lists()` + adapter `_selected_list_ids()` still produce the same *effective* selection before/after migration (regression guard that migration doesn't change sync behavior, only representation).

**Commit boundary:** one commit that runs the script and commits the resulting `lists/**` diff (large diff, mechanical) — keep the migration script itself in a separate commit from its execution output if the repo's convention favors "tool commit" + "generated-data commit" as two reviewable units (check `git log` for that pattern in this repo before deciding — CLAUDE.md/`ai/plans` naming suggests a plan-per-feature style, so likely fine as 2 commits: "add migration script (+ tests)" then "apply tier filename migration to lists/").

---

## Phase 4 — Textual `apply` TUI (ask #3)

**New dependency:** add `textual` to `pyproject.toml` `[project.dependencies]` (or a new optional extra `[project.optional-dependencies] tui = ["textual"]` if the repo prefers keeping the core CLI dependency-light — check `pyproject.toml`'s existing extras structure first; given `patchright`/`markdownify` are already unconditional deps for scraping, a straight new required dep is consistent with existing style unless there's already an extras pattern).

**Metadata-for-picker gap — recommended approach:** build a **lightweight stitching loader**, not a `GameList`/`LoadedGameList` schema change. Reasoning: denormalizing bundle source/date/item-count onto the public `GameList` model would (a) require another schema/migration round on every list file, (b) create dual-source-of-truth drift risk against the archive JSON that's supposed to remain canonical for that metadata, and (c) the picker is a niche, occasional-use tool — not worth permanently bloating the public schema all downstream consumers must also handle. Instead:
- New module `src/game_collections/launchers/steam/picker.py` (or `src/game_collections/apply/` if this warrants its own top-level package alongside `sources/`/`launchers/` — recommend `src/game_collections/apply/` since this isn't Steam-specific logic, it wraps `SteamAdapter` but the picker/filter/config-file concepts are launcher-neutral):
  - `BundleMetadata` dataclass: `list_id`, `source` (derived from `list_id`'s first path segment, e.g. `humblebundle`/`greenmangaming`), `bundle_kind` (`choice`/`bundle`/etc., second path segment), `item_count` (`len(game_list.games)` — directly available, no archive lookup needed!), `date` (best-effort: parse the `YYYY-MM-DD_slug` directory-name convention already used by crawlers, e.g. `_bundle_date_prefix`/`_offer_key`-style parsing reused/duplicated as a small regex against `list_id`'s path segments — since going to the archive JSON for date is heavier and the date is already baked into the directory name by convention, prefer parsing `list_id` over opening each archive's `metadata.json`), `tier` (from `GameList.tier`, Phase 0).
  - `def load_bundle_metadata(game_lists: list[LoadedGameList]) -> list[BundleMetadata]` — pure function over already-loaded lists, no archive JSON access needed for date/item-count/source/tier since all of those are derivable from `list_id` + `GameList` fields alone. (Only if finer metadata like original price or per-item detail is wanted later would archive JSON stitching be needed — out of scope for the picker's stated filters: type/source, item-count range, manual toggle, date.)
- **Selection config file schema** — new Pydantic model in `src/game_collections/apply/config.py`:
  ```python
  class ApplySelection(StrictModel):
      schema_version: Literal[1] = Field(1, alias="schema")
      selected: list[str] = Field(default_factory=list)   # explicit list_ids the user wants included
      excluded: list[str] = Field(default_factory=list)   # explicit list_ids the user wants excluded
                                                             # (both lists rather than a single boolean map keeps
                                                             # the file readably diffable/reviewable in git, and
                                                             # lets "new bundles added later" default to a
                                                             # policy decided by presence/absence — see below)
      updated_at: datetime
  ```
  Committed at a fixed path, e.g. `config/apply-selection.yml` (matches existing `config/isthereanydeal-providers.yml` naming convention seen in `cli.py`).
  - **Open design question:** should newly-discovered bundles (not yet mentioned in either list) default to included or excluded until the user runs `apply` again and explicitly decides? Recommend: absent from both lists = "undecided," and `sync`/`apply --headless` treat undecided as excluded-by-default (safer: nothing gets synced without explicit opt-in) OR included-by-default (matches today's `sync` behavior, which currently syncs everything eligible with no selection concept at all — introducing this file must not silently change default behavior for users who never touch `apply`). **Recommend: if `config/apply-selection.yml` doesn't exist at all, `sync` behaves exactly as today (no filtering) — full backward compatibility.** If it exists, only lists explicitly in `excluded` are dropped from an otherwise-full selection, and `selected` becomes irrelevant/is just "everything not excluded" — simplifying to **a single `excluded: list[str]`** field is likely cleaner than tracking both, since "everything not excluded" is the natural default and matches "opt out of specific bundles" as the TUI's real job (checkboxes start pre-checked, unchecking = excluding). Flag this simplification for confirmation.
- **Where `sync` reads it:** `src/game_collections/cli.py` `sync_command` (~790-847) and `eligible_command` (~763-) both call `discover_game_lists(...)` then `adapter.plan(...)`. Insert a filter step between discovery and `plan()`: `game_lists = [gl for gl in game_lists if gl.id not in excluded_ids]` where `excluded_ids` comes from loading `config/apply-selection.yml` if present (new `--selection-config` CLI option, default `Path("config/apply-selection.yml")`, silently absent = no filtering). This requires zero changes to `SteamAdapter.plan/stage/apply` — the filtering happens purely at the `discover_game_lists()` → `plan()` boundary, which is exactly the reuse point the user asked for.

**The `apply` command itself:**
- New file `src/game_collections/apply/tui.py` — Textual `App` subclass, e.g. `ApplyPickerApp`:
  - Screen: scrollable list of `BundleMetadata` rows as `Checkbox` widgets (pre-checked unless already excluded), each row showing source/date/item-count/tier.
  - Filter bar widgets: a `Select`/dropdown for source, two `Input` fields (or a range slider substitute) for min/max item-count, two `Input`/date-picker-ish fields for date-after/date-before — Textual doesn't ship a native date-picker widget, so plain validated `Input` with `YYYY-MM-DD` parsing is the pragmatic choice (flag: verify Textual's current widget catalog for anything better before hand-rolling, but don't block the plan on it — `Input` + manual parse is a safe fallback either way).
  - Filters affect visibility/highlighting only, not the underlying checkbox state — unchecking still means "excluded" regardless of current filter view (standard picker UX, avoids losing selections when a filter hides a row).
  - On save (a bound key, e.g. `ctrl+s` or an explicit "Save & Exit" button): write `ApplySelection` to `config/apply-selection.yml` via the same `atomic_write` helper, AND if the user is mid-`--apply` flow, also copy the file into the staging directory (`adapter.stage()`'s `output_dir` — the CLI orchestrates this: after `stage()` returns `staged_dir`, copy `config/apply-selection.yml` into `staged_dir / "apply-selection.yml"` so the staged bundle used for the real Steam replace is self-contained/auditable, matching the existing pattern where `stage()` already writes a `README.txt` report into the same directory).
- **New CLI command** in `cli.py`: `@app.command("apply")` — parallels `sync_command`'s options (`--source`, `--steam-root`, `--steam-id`, `--api-key`, `--match-mode`, `--reconcile-managed`, `--lists-root`) but instead of immediately printing a plan, launches `ApplyPickerApp(bundle_metadata).run()`, then on exit (if saved) proceeds to call `_steam_adapter()` → `discover_game_lists()` (filtered by the just-saved selection) → `adapter.plan(...)` → same `_print_plan` + `--apply`/`stage`/`confirm`/`apply` flow as `sync_command` today (literally delegate to the same helper functions/shared code path, only the list discovery step differs by the added filter).

**Tests:**
- `tests/test_apply_config.py` (new) — round-trip `ApplySelection` model, load/save, `extra="forbid"` strict behavior consistent with `StrictModel` convention.
- `tests/test_apply_metadata.py` (new) — `load_bundle_metadata()` against a handful of representative `list_id` shapes per source (humble choice `YYYY-MM/`, humble bundle `YYYY-MM-DD_slug/tier-N.yml`, gmg/itad equivalents) verifying date/source/item-count/tier extraction.
- Textual apps are testable headlessly via `textual`'s own `Pilot`/snapshot testing utilities (`textual.testing` or `pytest-textual-snapshot` — check what's idiomatic for the installed Textual version) — at minimum, a smoke test that the app mounts, filters narrow the visible rows, and toggling+saving produces the expected `ApplySelection`.
- `tests/test_cli.py` — add coverage for the new `apply` command's non-interactive plumbing (the filter-application boundary before `adapter.plan()`), likely by monkeypatching/stubbing the Textual app run to return a fixed selection so the test doesn't need a real terminal.

**Commit boundary:** likely 2-3 commits — (1) dependency + config model + metadata loader + tests, (2) Textual TUI app + smoke tests, (3) CLI `apply` command wiring + `sync` filter integration + tests.

---

## Phase 5 — BYOB ("pick N of M") support (ask #4)

Sequential sub-phases per the user's "all of the above, step after step" scoping.

### 5a. Model the quota

**File:** `src/game_collections/models.py` — add an optional field to `GameList` (alongside `tier` from Phase 0):
```python
pick_quota: Annotated[int, Field(ge=1)] | None = None
```
Semantics: "you may select/own any `pick_quota` of the `len(games)` games in this list and still be considered eligible for it." `None` = today's default "own everything" semantics (fully backward compatible — every existing list has no quota and continues to require all games). Naming bikeshed: `pick_quota` vs `pick_count` vs `byob_quota` — recommend `pick_quota` since it reads naturally as "the quota of picks allowed," but flag for user preference.
- Regenerate `schemas/game-list.schema.json`, extend `tests/test_schema.py` coverage as in Phase 0.
- `tests/test_lists.py` — add a `GameList` construction test with `pick_quota` set, and one validator consideration: should `pick_quota` be bounded by `len(games)` at parse time (`pick_quota <= len(games)`)? Recommend yes — add a `model_validator(mode="after")` on `GameList` enforcing `pick_quota is None or pick_quota <= len(self.games)`, mirroring the existing dedup validator style on `Game`.

### 5b. ITAD `byob` — populate the quota from existing (already-fetched) data

**Files:**
- `src/game_collections/sources/isthereanydeal/models.py` — `ItadListSummary.byob: bool` already exists (line ~165) but per the plan doc (`ai/plans/011_...md:44-49`) the real upstream JSON carries `liveData.byob: [{"count": N, "price": [...]}, ...]` — a *list* of purchasable tiers (pick 3 for $X, pick 5 for $Y, etc.), not a single quota. This means BYOB bundles are actually **multiple quota tiers**, not one pick-count — e.g., "pick any 3 for $10, or any 5 for $15." Add a model, e.g. `ItadByobTier(StrictModel)`: `count: int`, `price: HumblePrice`-equivalent-for-ITAD (check what price model ITAD already uses, likely `ItadPrice` — reuse it), attached as `ItadArchive.byob_tiers: list[ItadByobTier] = Field(default_factory=list)`.
- `src/game_collections/sources/isthereanydeal/parser.py` (`parse_bundle_detail_json`/`parse_bundle_detail_page`, ~line 442/618 and the byob docstring ~528-534) — currently deliberately collapses BYOB to one synthetic tier; change to: when `summary.byob` is true, parse `liveData.byob` into `ItadByobTier` entries instead of synthesizing a single flat tier, and when writing the list (`write_itad_offer`), emit one `GameList` per byob count-tier, all pointing at the *same* full game pool but with `pick_quota=<count>` set and `tier=<index+1>` if there are multiple byob tiers (reusing the Phase 0/1 tier convention — a byob bundle with 2 purchasable pick-counts is structurally "2 tiers," consistent with how fixed-price multi-tier bundles already work). Filename convention: extend Phase 1's rule — single byob tier → `bundle.yml` with `pick_quota` set, no `tier`; multiple → `tier-N.yml` with both `tier` and `pick_quota` set.
- **VERIFY BEFORE IMPLEMENTING** (flagging per repo convention): the exact shape of `liveData.byob` in the real embedded JSON (field names `count`/`price`, currency format, whether `price` is even present for all entries, whether counts overlap with existing `tiers`/are exclusive) must be checked against a live ITAD bundle detail page before writing the Pydantic model — this is exactly the kind of "external shape" the repo's CLAUDE.md says to verify, not guess, and the existing plan doc already flags it as unmodeled/unverified. Do this via a `patchright`-fetched live page + manual JSON inspection (or reuse `ai/plans/011...` fixture snapshots if one was already captured) before finalizing `ItadByobTier`'s fields.
- **Tests:** `tests/test_isthereanydeal_parser.py`, `tests/test_isthereanydeal_crawler.py` — add byob fixture case(s) once shape is verified; assert `pick_quota` set correctly per emitted tier.

### 5c. Humble Choice pick-count — needs a new field to be discovered, not yet confirmed present

**Investigation status:** grep across `humblebundle/parser.py`/`models.py` found **no existing field** carrying "how many items you're allowed to pick" — `HumbleTier.item_count` is the cumulative *pool size*, not a pick quota, and `parse_choice_page` builds exactly one tier over the whole pool with no quota concept at all today. This is a **live-page investigation task**, flagged explicitly per "verify, don't guess external shapes":
- Action: fetch a real active Humble Choice page (or reuse an already-archived fixture HTML if the repo has one committed under test fixtures — check `tests/fixtures/humblebundle/` for a Choice page fixture first) and inspect `data-content-choice-data` / `webpack-choice-marketing-data` (the two embedded blobs `parse_choice_page` already reads) for a field resembling `total_choices`/`choicesMade`/`numChoices`/similar — Humble Choice pages are known (from public knowledge, unverified against this repo's actual fixture) to expose something like a "choices included" count in the marketing/content JSON tied to subscription tier (Lite/Standard/Premium each unlock a different pick-count) — this repo has NOT verified that shape, so **do not hardcode a guessed field name**; this must be a live/fixture inspection step before writing any parser change.
- Once verified: add `HumbleChoicePickTier` or extend `HumbleTier`/`HumbleArchive` with e.g. `pick_options: list[HumbleChoicePickOption]` (`option_name` e.g. "Standard", `pick_quota: int`, `price: HumblePrice`) mirroring the ITAD byob-tiers-list shape for consistency across sources, then emit one `GameList` per pick-option the same way as 5b (single option → `bundle.yml`, multiple → `tier-N.yml`, each with `pick_quota` set).
- **Tests:** new fixture-based `tests/test_humblebundle_parser.py` cases once the real shape is confirmed; `tests/test_humblebundle_crawler.py` for the resulting file-emission changes.

### 5d. Sync/ownership matching for quota-based lists

**File:** `src/game_collections/launchers/steam/adapter.py` — `evaluate()` (the method producing `CollectionEligibility` per list, referenced near `def evaluate` before `def plan`):
- Today, per the described `--mode any/all`, eligibility is all-or-any across the *entire* list's `games`. For a `pick_quota`-bearing list, eligibility must instead be: `eligible = len(owned_ids-derived distinct owned games) >= pick_quota`, independent of `--mode`, since quota lists are inherently "any N of M," not "all" or "any single one." Concretely: compute `owned_count` (count of `game.ids` groups where at least one id is owned — i.e., count of *games*, not individual ids, matching), and if `list_data.pick_quota is not None`, override the all/any comparison with `owned_count >= list_data.pick_quota`; `owned_ids`/`missing_ids` in the resulting `CollectionEligibility` should then report the actually-owned subset (for a quota list, "missing" isn't really meaningful in the same way — every unowned game in the pool is "missing" but that's expected/fine since you only need `pick_quota` of them; keep `missing_ids` as informational only, not a factor in `eligible` when quota mode is active).
- **Renewal/reconciliation nuance flagged by the user** ("a fresh list-checkout later might have games added/removed from the pool"): since each ITAD/Humble Choice re-crawl of the *same* bundle would produce a new archive+list snapshot (dated/keyed per crawl, per existing `_offer_key`/date-prefix conventions), a changed pool becomes a *different* `list_id` (new directory) naturally — the existing per-crawl snapshot model already handles "pool changed" as "it's a new list," so no special reconciliation logic is needed beyond what already exists; the sync-eligibility change in `evaluate()` is the only adapter change required. Document this reasoning as the answer to the open question rather than building new reconciliation code.
- **Tests:** `tests/test_steam_adapter.py` — new cases: quota list where owned count meets/exceeds quota → eligible regardless of `--mode`; owned count below quota → ineligible; quota list combined with `--tiers highest` grouping (should still work unchanged since quota and tier-rank are orthogonal fields).

**Commit boundary:** 5a (model+schema) as one commit; 5b (ITAD) as one commit *after* live-shape verification; 5c (Humble) as one commit *after* live-shape verification (likely the last commit in the whole plan, gated on investigation); 5d (adapter matching) as one commit, reasonably shippable right after 5a since it only depends on the field existing, not on either scraper populating it yet.

---

## Summary of phase ordering & shippability

1. Phase 0 — `tier` field + schema (foundation, no behavior change)
2. Phase 1 — crawlers write `bundle.yml`/`tier-N.yml` + populate `tier` (per-source commits)
3. Phase 2 — adapter reads `tier` field, deletes regex (depends on 0+1)
4. Phase 3 — migration script + apply to `lists/**` (depends on 0-2 to define target shape)
5. Phase 4 — Textual `apply` TUI + selection config (independent of Phase 5, can ship anytime after Phase 0-3 land since it needs `tier` for display but not `pick_quota`)
6. Phase 5 — BYOB: 5a (model) → 5d (adapter matching, can ship right after 5a) → 5b (ITAD, gated on live verification) → 5c (Humble, gated on live verification)

### Critical Files for Implementation
- /home/user/git/luckydonald/game_collections/src/game_collections/models.py
- /home/user/git/luckydonald/game_collections/src/game_collections/launchers/steam/adapter.py
- /home/user/git/luckydonald/game_collections/src/game_collections/launchers/base.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/crawler.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/parser.py
- /home/user/git/luckydonald/game_collections/src/game_collections/cli.py
- /home/user/git/luckydonald/game_collections/src/game_collections/lists.py