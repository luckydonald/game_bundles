I have enough detail to write the combined plan now.

## Combined Implementation Plan

### Item 1 — Standardize bundle tier name casing (humblebundle vs isthereanydeal)

**Approach:** Rewrite `_humble_tier_name` in `src/game_collections/sources/isthereanydeal/parser.py` (lines 245-254) to produce the same string format humblebundle's inline code produces, rather than factoring out a shared helper. Recommendation: **duplicate the format string, do not add a shared helper in `common.py`.** Rationale: the two call sites differ in signature shape (humble's is inline with an `index==0` special case tied to iteration order; ITAD's is a standalone function keyed off `item_count == expected_game_count`), the string is a one-line format with no real logic to deduplicate, and forcing a shared helper across `sources/humblebundle/` and `sources/isthereanydeal/` would need to live in `common.py` purely for two call sites — CLAUDE.md's "launcher-neutral" note is about the YAML *loading* layer (`models.py`/`lists.py`), not source-crawler internals, so it doesn't mandate sharing here. Keep `_humble_tier_name`'s docstring (already explains it mirrors the dedicated Humble scraper's naming) and just change its body to:
```python
prefix = "Entire " if item_count == expected_game_count else ""
return f"{prefix}{item_count} Item Bundle"
```

**Files touched:**
- `src/game_collections/sources/isthereanydeal/parser.py` (lines 245-254, `_humble_tier_name`)
- `tests/test_isthereanydeal_parser.py:321` — update assertion from `"entire-1-item-bundle"` to `"Entire 1 Item Bundle"`

**Risks:** Low. Confirmed `GameList.name` (and the `Game`/`GameGroup`/`Reference` name fields) in `schemas/game-list.schema.json` is an unconstrained `{"type": "string", "minLength": 1}` — changing the string content doesn't touch the schema, so `uv run game-collections schema` regeneration is **not needed**. Confirmed via `derive_list_id`/`validate_list_id` that list IDs come from file paths only, never from `name:`, so this change is safe per the "IDs must never be touched by display-name changes" rule. `_dedupe_tier_name` (immediately below, lines 257-266) already handles same-named-tier collisions generically by string equality, so the format change doesn't interact badly with dedup.

**Test additions:** Update the one existing assertion; no new tests strictly required, but consider adding a second case asserting the non-"entire" branch (e.g. tier 2 of a multi-tier ITAD-mirrored-humble bundle) renders as `"N Item Bundle"` to lock in parity with humble's own `f"{item_count} Item Bundle"` (index != 0) branch.

---

### Item 2 — Persist apply TUI filter settings into `config/apply-selection.yml`

**Approach:** Extend `ApplySelection` (`src/game_collections/apply/config.py`, lines 26-34) with new **optional** fields mirroring the TUI's live filter state, all with defaults so existing saved YAML (lacking these keys) still validates under `model_validate_json` strict mode:

```python
class ApplySelection(StrictModel):
    schema_version: Literal[1] = Field(alias="schema", serialization_alias="schema")
    selected: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    updated_at: datetime
    min_items: int | None = None
    max_items: int | None = None
    date_after: str | None = None
    date_before: str | None = None
    min_missing: int | None = None
    max_missing: int | None = 0
    unresolved_handling: MissingHandling = "ignore"
    unconfigured_handling: MissingHandling = "ignore"   # coordinate final name with item 3
    tier_mode: Literal["all", "highest"] = "highest"
    show_filtered: bool = False
```
Import `MissingHandling` from `game_collections.completion` (already a dependency of `tui.py`) rather than re-declaring the `Literal["hide","ignore","enforce"]` in `config.py`, to avoid drift. Defaults chosen to exactly match today's CLI/TUI defaults (`max_missing=0`, `unresolved_handling="ignore"`, `tier_mode="highest"`, min/max_items and dates unset, `show_filtered=False`) so a freshly-created selection with no filter customization round-trips identically to today's behavior.

**Where to populate on save:** In `_build_selection()` (`tui.py` lines 1113-1127), add the new keyword args sourced from `self._row_filters.min_items/max_items/date_after/date_before`, `self.min_missing`, `self.max_missing`, `self.unresolved_handling`, `self.unconfigured_handling`, `self.tier_mode`, `self._show_filtered`.

**Where to restore on load (currently write-only — confirmed):** Today `cli.py`'s `apply_command` (lines 1069-1070) calls `load_selection(selection_config)` only to seed `previously_excluded = excluded_list_ids(previous_selection)`; the filter-related constructor args to `ApplyPickerApp` (`min_missing`, `max_missing`, `unresolved_handling`, `unconfigured_handling`, `tiers`) come **exclusively from CLI flags/their Typer defaults**, never from the loaded selection. To make this round-trip, in `apply_command`:
1. After `previous_selection = load_selection(selection_config)`, if `previous_selection is not None`, use its filter fields as the base defaults for constructing `ApplyPickerApp`, but only where the corresponding CLI flag was left at its Typer default (i.e., explicit CLI flags should still win over a saved config, consistent with how `--selection-config`-driven exclusion already composes with explicit choices). Since Typer doesn't cleanly expose "was this option explicitly passed," the simplest correct approach is: **CLI flags always take precedence when passed; there's no built-in way to distinguish "flag left at default" from "flag explicitly set to the default value," so document this as a known limitation** — OR, cleaner, treat it the same way `resume_selection` already works inside the `while True:` loop (lines 1138-1152): only restore from `previous_selection` on the *very first* iteration when the user hasn't explicitly overridden via CLI, and pass those restored values into `ApplyPickerApp`'s constructor params (`min_missing=`, `max_missing=`, `unresolved_handling=`, `unconfigured_handling=`, `tier_mode=`, plus new params for `min_items`/`max_items`/`date_after`/`date_before`/`show_filtered`, which `ApplyPickerApp.__init__` doesn't currently accept at all).
2. `ApplyPickerApp.__init__` (`tui.py`, constructor around lines 440-470) needs new optional constructor parameters for `min_items`, `max_items`, `date_after`, `date_before`, `show_filtered` (it already accepts `min_missing`, `max_missing`, `unresolved_handling`, `unconfigured_handling`, `tier_mode`) to seed `self._row_filters = _Filters(...)` and `self._show_filtered` instead of always defaulting to `_Filters()`/`False`.
3. Simplest overall design given the loop already re-invokes `ApplyPickerApp` with `initial_selection=resume_selection` on retry: **have `ApplyPickerApp.__init__` accept the loaded `ApplySelection` object itself (reuse `initial_selection`) and, when the explicit filter constructor args are left `None`/unset, fall back to reading filter values out of `initial_selection`** — this keeps a single source of truth and avoids duplicating "was this explicit" logic in `cli.py`. Concretely: in `cli.py`, pass `initial_selection=previous_selection if resume_selection is None else resume_selection` (previously only `resume_selection`), and in `ApplyPickerApp.__init__`, when building `self._row_filters`/`self.min_missing`/etc., prefer the CLI-flag-provided value if it differs from the Typer default, else read from `initial_selection` if present, else use the hardcoded defaults. Note this still has the "can't tell explicit-default from unset" ambiguity — flag this as an explicit open design question for the user/reviewer rather than silently picking a lossy heuristic.

**Files touched:**
- `src/game_collections/apply/config.py` (add fields to `ApplySelection`)
- `src/game_collections/apply/tui.py` (`_build_selection`, `ApplyPickerApp.__init__` new params, `_Filters` construction)
- `src/game_collections/cli.py` (`apply_command`, how `previous_selection`/`resume_selection` feed into `ApplyPickerApp`)

**Risks:**
- Backward compatibility: must confirm `model_validate_json` strict mode tolerates missing keys with `Field(default=...)` — it does, since `ApplySelection` already has `default_factory=list` fields (`selected`, `excluded`) that work today; new scalar defaults follow the same pattern.
- Precedence ambiguity between CLI flags and saved-config filters (see above) — needs explicit product decision; recommend documenting in `docs/README.md` whichever behavior is chosen.
- `save_selection` uses `model_dump(by_alias=True, mode="json")` + `yaml.safe_dump` — new fields will just appear as additional YAML keys; need to confirm no `additionalProperties: false`-style strict rejection breaks anything downstream that also parses `apply-selection.yml` (only `load_selection`/`excluded_list_ids` do, per grep — safe).

**Test additions:** `tests/test_apply_config.py` — new round-trip test asserting the new optional fields serialize/deserialize, and a test that an old-style YAML (missing the new keys) still loads via `load_selection` producing the documented defaults. `tests/test_apply_tui.py` — test that `_build_selection()` includes the new filter fields, and (if restore-on-load is implemented) a test that constructing `ApplyPickerApp` with an `initial_selection` containing filter fields seeds `self._row_filters`/`self.min_missing`/etc. `tests/test_cli.py` — integration test around `apply_command`'s restore-from-`previous_selection` behavior if that precedence logic lands in `cli.py`.

**Schema regeneration:** Not applicable — `ApplySelection` isn't one of the Pydantic models covered by `schemas/*.json` (only `game-list.schema.json` and the `<source>-archive.schema.json` files are, per `CLAUDE.md` and `find schemas -iname "*.json"`); `config/apply-selection.yml` has no JSON Schema file. No `uv run game-collections schema` step needed for this item.

---

### Item 3 — Rename "Unconfigured Handling"

**Candidate names** (all must clearly signal "store identified, but ownership can't be checked there" vs "unresolved" = "couldn't even identify a provider"):
1. `--unsupported-store-handling` / `unsupported_store_handling` — clear, matches existing internal vocabulary (`unsupported_ids` field already exists in `GameListCompletion`!).
2. `--unownable-handling` / `unownable_handling` — short but a bit unusual/ambiguous (reads like "can never be owned" rather than "ownership unknown").
3. `--no-ownership-check-handling` / `no_ownership_check_handling` — very explicit but long and awkward as an attribute name.

**Recommendation: option 1, `--unsupported-store-handling` / `unsupported_store_handling`.** It's the clearest, and it's already consistent with the existing `unsupported_ids: list[str]` field name inside `GameListCompletion` in `completion.py` (line 23) and the `unsupported_ids.append(game.name)` call (line 72) — so this rename actually *removes* an inconsistency (currently the public flag says "unconfigured" while the internal data field already says "unsupported").

**Every location needing the rename** (confirmed via grep):
- `src/game_collections/completion.py`: `evaluate_completion(..., unconfigured_handling: MissingHandling = "ignore")` param (line 34), its use in the docstring (line 36) and body (line 67).
- `src/game_collections/launchers/steam/adapter.py`: `SteamAdapterOptions.unconfigured_handling` field (line 47), the `handling_name` validation loop tuple at line 60, the `unconfigured_handling=self.options.unconfigured_handling` call-through at line 151.
- `src/game_collections/cli.py`: the `--unconfigured-handling` Typer option + help text (line 1050, and the same pattern likely repeated at the other two call sites mentioned in the task at ~922/974 for `eligible`/`sync` — needs verification each occurrence uses identical option definition text), all `unconfigured_handling=unconfigured_handling` pass-throughs to `_steam_adapter(...)` (lines 1093, 1122) and to `ApplyPickerApp(...)` (line 1146).
- `src/game_collections/apply/tui.py`: constructor param `unconfigured_handling: MissingHandling = "ignore"` (line 443), `self.unconfigured_handling` attribute (line 469), its use building `evaluate_completion(...)` call (line 690), the widget id `#filter-unconfigured-handling` and its label text "unconfigured: hide/ignore/enforce" (lines ~533-544), the `on_select_changed`-style handler comparing/assigning `self.unconfigured_handling` (lines 987-988), and the `_is_hidden_by_handling`-style docstring/logic at lines 867-877.
- `src/game_collections/apply/config.py` (**if item 2 lands first or alongside**): the new `unconfigured_handling` field proposed in item 2 must be named `unsupported_store_handling` from the start — coordinate so item 2's PR either lands after item 3's rename decision, or item 2 is written directly with the new name to avoid a double rename.
- `docs/README.md`: three prose mentions confirmed by grep — line 65 (`` `--unresolved-handling`/`--unconfigured-handling` (`hide`/`ignore`/`enforce`, default `ignore`) ``), line 80 (prose "unresolved/unconfigured ownership handling"), line 86 (picker field description `` `--unresolved-handling`/`--unconfigured-handling`/`--tiers` as dropdowns ``). (Root `README.md` and `lists/README.md` had zero matches for "unconfigured" — only `docs/README.md` needs edits, but re-grep at implementation time since `docs/README.md` appears to be the file CLAUDE.md calls "root README.md" — confirm this mapping, the CLAUDE.md text says "root `README.md`" but the actual verbose docs live in `docs/README.md`; there may be two READMEs to check, worth re-verifying paths before editing.)
- Tests: `tests/test_completion.py`, `tests/test_steam_adapter.py`, `tests/test_cli.py`, `tests/test_apply_tui.py` — all reference `unconfigured_handling` per the earlier grep and will need every occurrence renamed.

**Breaking change:** Yes — `--unconfigured-handling` is a public Typer CLI flag on `apply`, `eligible`, and `sync` (all three commands per the task's line references). Per CLAUDE.md's stance against compatibility shims/hacks, **recommend a clean rename with no hidden alias**, documented as a breaking change in `docs/README.md`'s changelog/behavior notes (check if the repo keeps a CHANGELOG; none was found in the file listing, so the rename note should go inline in `docs/README.md` prose or the commit message itself, per the repo's commit-per-task documentation convention).

---

### Item 4 — humblebundle crawler merge instead of overwrite

**Confirmed:** `write_humble_offer()` (`src/game_collections/sources/humblebundle/crawler.py`, lines 247-352) never reads existing `path` contents before `atomic_write(path, render_game_list_yaml(game_list, path, repository_root))` — full clobber, for both the choice/pick-option branch (lines 267-301) and the regular tiers branch (lines 304-350). Same clobber pattern exists in `isthereanydeal/crawler.py::write_itad_offer()` (per task description; not independently re-verified in this pass but consistent with the same `atomic_write`-only pattern).

**Merge key:** `GameList.games: list[Game]`, and `GameList`'s own validator (`models.py` lines 121-126) already enforces games are unique by `name.casefold()` within a list — so **game name (casefold) is the natural, already-enforced merge key**, not `ids`.

**Merge strategy design:**
- Before writing, if `path.exists()`, load it via `load_game_list(path, lists_root)` (`src/game_collections/lists.py:52`) to get the existing `GameList`.
- Build a `dict[str, Game]` keyed by `casefold(name)` from the existing list's `games`.
- For each freshly-crawled `Game`: if a name-matching existing entry exists AND its `ids` differ from the freshly-crawled `ids` in a way that looks like manual enrichment (i.e., existing `ids` is a *strict superset* of, or otherwise not a pure subset of, the fresh `ids` — signaling a human added/fixed something) — **keep the existing entry's `ids`/`group` as-is**; otherwise (existing entry is missing, or fresh crawl strictly subsumes/matches what's already there) use the freshly-crawled entry. Simpler, safer alternative given "prefer enhancing, not overwriting" is the stated guiding principle: **always prefer the existing entry when one exists by name, full stop** — never let a re-crawl regress a manually-fixed `ids:` list, and only ever *add* new games not previously present. This is simpler to reason about, has no edge cases around "which unresolved marker is 'worse'", and matches the todo's literal wording ("merging... instead of overwriting").
- New games (crawled name not in existing file) get appended.
- Recommend **never remove** existing entries absent from the fresh crawl output — for a historical/completed bundle, the source listing should be stable, but if Humble Bundle Inc. ever edits contents post-launch (rare but has happened for asset corrections), a game silently vanishing from a still-referenced list would be a worse failure mode (broken user selections, phantom exclusions) than a stale entry lingering. So: additive-only merge, no removal, matching the item's "enhancing, not overwriting" framing exactly.
- Non-`games` fields (`name`, `tier`, `pick_quota`, `references`) should come from the **fresh crawl** (these represent metadata about the bundle/tier itself, not manually-curated content, and should track source-of-truth updates — e.g. archive URL/crawl-metadata references should stay current).

**Where the merge logic should live:** A new shared helper in `src/game_collections/sources/common.py`, e.g.:
```python
def merge_game_list(existing: GameList | None, fresh: GameList) -> GameList:
    """Combine a freshly-crawled list with any already-committed list at the same path.

    Keeps every existing `Game` entry as-is (preserving manual `ids:`/`group` edits),
    appends only genuinely new games from `fresh`, and otherwise takes bundle-level
    metadata (name/tier/pick_quota/references) from `fresh`.
    """
```
Signature takes `existing: GameList | None` (so callers just pass `None` when the file doesn't exist yet, avoiding a separate existence check duplicated at each call site) and `fresh: GameList`, returns a new `GameList`. This lives in `common.py` because, as the task notes, `isthereanydeal/crawler.py::write_itad_offer()` has the identical clobber problem and should eventually call the same helper — even though the todo item text only explicitly asks for humblebundle, put the reusable piece in the shared module now so item 4 doesn't have to be redone when ITAD gets the same treatment. Only `humblebundle/crawler.py::write_humble_offer()` needs to actually *call* it for this item; wiring `isthereanydeal/crawler.py` up to the same helper is out of scope but should be called out as a natural immediate follow-up in the commit message/PR description.

**Files touched:**
- `src/game_collections/sources/common.py` (new `merge_game_list` helper; needs `load_game_list`/`lists_root` context — note `common.py` currently has no dependency on `lists.py`, so check for import-cycle risk: `lists.py` imports from `models.py` only, `common.py` doesn't currently import `lists.py` — should be safe to add).
- `src/game_collections/sources/humblebundle/crawler.py`: `write_humble_offer()`, both write sites (choice/pick-option loop lines 267-301, and tiers loop lines 304-350) — each `atomic_write(path, render_game_list_yaml(game_list, ...))` call needs to first attempt `load_game_list(path, lists_root)` (catching "doesn't exist" — note `load_game_list` currently assumes the file exists via `path.read_text`; needs a `path.exists()` guard before calling it, or a new existence-tolerant wrapper) then pass through `merge_game_list`.

**Risks:**
- `load_game_list` requires `lists_root` for `derive_list_id`'s path-escape validation — `write_humble_offer` already has `lists_root` in scope, so this is fine, but confirm `list_directory`/`path` values built inside `write_humble_offer` are always under `lists_root` (they are, per the code: `list_directory = lists_root / "humblebundle/..."`).
- If an existing file is present but fails to validate (e.g. was hand-edited into an invalid state, or an old schema version), the merge should fail loudly (raise) rather than silently discarding the existing file and overwriting — consistent with the project's "unknown external fields as errors" philosophy; do not catch-and-ignore `ListLoadError`.
- Name-based matching breaks if a game gets renamed between crawls (upstream Humble sometimes retitles). Recommend documenting this as a known limitation rather than solving ID-based fuzzy matching now — GameList already enforces name uniqueness so there's no better key without introducing something like a stable per-item Humble `machine_name`, which isn't currently threaded through to `Game`.
- Determinism/YAML diff noise: since existing entries are kept verbatim (including their original position in the existing file's `games` list) except appended-new-games at the end, re-running the crawler on an unchanged bundle should now produce a **byte-identical** file when nothing changed — actually improves the "resume from already-archived output" behavior mentioned in CLAUDE.md, worth calling out as a nice side effect.

**Test additions:** `tests/test_humblebundle_crawler.py` — new test(s): (a) writing to a fresh path still works unchanged (regression), (b) writing over an existing list where the existing file has manually-edited `ids:` on one game preserves those `ids:` after re-crawl, (c) a genuinely new game appearing in a re-crawl gets appended without disturbing existing entries' order/content, (d) existing `references`/`name`/`tier` get updated to the fresh crawl's values even when `games` are preserved. Possibly a new `tests/test_sources_common.py` (check if it exists) for `merge_game_list` in isolation — confirm via `ls tests/` whether such a file already exists before creating test-file-naming plan.

**Schema regeneration:** Not needed — no Pydantic model shape changes, only crawler logic. Confirm at implementation time via `tests/test_schema.py` (drift detector) that nothing changed.

---

### Cross-item coordination note
Item 2 proposes adding an `unconfigured_handling` field to `ApplySelection`; item 3 proposes renaming that whole concept to `unsupported_store_handling`. **Sequence item 3 before item 2**, or write item 2's new `ApplySelection` field directly as `unsupported_store_handling` from the start, so there's never a persisted-YAML field that needs its own rename/migration on top of the CLI rename.

### Critical Files for Implementation
- src/game_collections/sources/isthereanydeal/parser.py
- src/game_collections/apply/config.py
- src/game_collections/apply/tui.py
- src/game_collections/cli.py
- src/game_collections/completion.py
- src/game_collections/launchers/steam/adapter.py
- src/game_collections/sources/humblebundle/crawler.py
- src/game_collections/sources/common.py
- src/game_collections/lists.py