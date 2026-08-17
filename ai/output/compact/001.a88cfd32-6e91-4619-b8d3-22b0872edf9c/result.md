<analysis>
Let me chronologically walk through this conversation:

1. User invoked `/plan @ai/todo.md` — entering plan mode to plan work on the repo's `ai/todo.md` file.

2. I read `ai/todo.md`, which had 2 checked items and 4 unchecked items:
   - Standardize `Entire 14 Item Bundle` naming between humblebundle and isthereanydeal
   - apply should save filter settings to `config/apply-selection.yml`
   - Rename "Unconfigured Handling" to something clearer
   - Analyze isthereanydeal vs humble crawl diff (with sub-item: check humblebundle merge support)

3. I asked the user via AskUserQuestion which item(s) to plan for; user answered "all remaining."

4. I launched 3 parallel Explore agents to investigate:
   - Agent 1 (a7e8d9cb4ee3d0c72): bundle name normalization between humblebundle/isthereanydeal parsers
   - Agent 2 (a9c63bbcaf88ba5e7): apply TUI filter settings persistence + "unconfigured handling" semantics
   - Agent 3 (ae1b826754c98b048): isthereanydeal vs humble crawl diff + merge support investigation

5. All three agents completed with detailed findings (fully documented in tool results). Key findings:
   - Humble tier names: `f"Entire {item_count} Item Bundle"` (parser.py ~line 390, inline in `parse_choice_month`)
   - ITAD's `_humble_tier_name()` (isthereanydeal/parser.py ~lines 245-254): dash-case `f"{prefix}{item_count}-item-bundle"`
   - This is purely display (`GameList.name`), not ID/path-derived — safe to change
   - `ApplySelection` (apply/config.py) only had schema_version/selected/excluded/updated_at — filter state in TUI (`_row_filters`, `min_missing`, `max_missing`, `unresolved_handling`, `unconfigured_handling`, `tier_mode`, `_show_filtered`) was never persisted
   - "unconfigured_handling" meant: provider identified but no ownership-check support (vs "unresolved" = no provider identified at all); internal data already called this `unsupported_ids`
   - humblebundle crawler's `write_humble_offer()` never reads existing file before overwriting — full clobber via `atomic_write`
   - Commit `9f39eff3` was actually an unrelated `.github workflows` commit, not an ITAD crawl commit as the todo item claimed; real ITAD crawl commits use pattern `[crawl|isthereanydeal] automated weekly scrape`
   - `1a12511d` was confirmed as a real humble crawl commit

6. I launched a Plan agent (a0170818dfe40d598) to design implementation approaches for all 4 items combined, given the above context. It returned a comprehensive per-item design (approach, files, risks, tests) — I incorporated this into my plan.

7. I verified a few facts myself via Bash: confirmed both `README.md` and `docs/README.md` exist, that `docs/README.md` has the "unconfigured" mentions (lines 65, 80, 86) and root `README.md` has none; confirmed `tests/test_apply_config.py`, `tests/test_apply_metadata.py`, `tests/test_apply_tui.py`, `tests/test_sources_common.py` exist.

8. I wrote the plan file at `/home/user/.confuig/claude/accounts/private/plans/wiggly-giggling-pinwheel.md` covering all 4 items with sequencing 3→2→1→4 (rename first, then filter persistence, then naming standardization, then merge).

9. I asked the user a clarifying question about Item 2's design ambiguity: Typer can't distinguish "flag omitted" from "flag explicitly set to default," so how should saved filters interact with CLI flags? Presented 3 options (saved-config-always-wins, CLI-always-wins, no-restore-for-now).

10. **User's actual answer** (verbatim): "Can't I set the flags to True/False/None, with None the "automatic" (documented) default later set in code? So the final filter is "copy from typer (flags), or copy from config file, or use default"" — This is the user's own proposed design: CLI flags default to `None` (sentinel for "not passed"), then resolve as CLI flag → config value → hardcoded default.

11. I updated the plan file's Item 2 section to reflect this precedence design exactly as the user specified.

12. Called `ExitPlanMode`; user approved the plan (returned via tool result "User has approved your plan. You can now start coding.")

13. I then implemented all 4 items in order, following the "commit-with-lplp-style" skill (which auto-activates at session start per this repo). Let me detail each:

**Item 3 (Rename "Unconfigured Handling")**:
- Grepped all "unconfigured" occurrences across src/tests/docs
- Used sed to bulk-replace `unconfigured_handling` → `unsupported_store_handling` and `unconfigured-handling` → `unsupported-store-handling` across: `completion.py`, `cli.py`, `launchers/steam/adapter.py`, `apply/tui.py`, `tests/test_steam_adapter.py`, `tests/test_cli.py`, `tests/test_completion.py`, `tests/test_apply_tui.py`, `docs/README.md`
- Manually fixed remaining prose/labels not caught by the identifier-pattern sed: docs/README.md prose "unresolved/unconfigured ownership handling" → "unresolved/unsupported-store ownership handling"; TUI dropdown labels `("unconfigured: hide", "hide")` etc → `("unsupported store: hide", "hide")` etc; test function names `test_hide_makes_a_bundle_with_an_unconfigured_game_ineligible` → `..._unsupported_store_game_ineligible`; `test_unconfigured_store_handling_hide_ignore_enforce` → `test_unsupported_store_handling_hide_ignore_enforce`
- Ran tests: found 2 failures — `test_sync_help_lists_matching_and_tier_choices` (rich's `--help` table truncates the longer flag name to `--unsupported-store-h…`, so exact-match assertion failed) — fixed by changing assertion to `"--unsupported-store-h"` with a comment explaining truncation; and `test_unchecking_and_saving_produces_expected_selection` — confirmed via `git stash`/`git stash pop` this was a **pre-existing failure unrelated to my changes** (same failure exists on unmodified code)
- Committed as `56c5d327` "[cli|apply|steam] ownership handling: ai: Run: Renamed `--unconfigured-handling` to `--unsupported-store-handling` for clarity."
- Then did a full interactive rebase to fold stray `ai:` auto-commits (prompt/decision/agent-result commits) into two kept plan commits (since the plan had two genuine revisions): `126950ae` "ai: Plan: Plan the four remaining `ai/todo.md` items:" and `27a41cde` "ai: Plan update: Resolve the apply-TUI filter-persistence precedence question:" — used `GIT_SEQUENCE_EDITOR=ai/git/rebase-todo.sh git rebase -i efddbe1a~1`, then cleaned up `ai/git/rebase-todo.sh` and `ai/git/rebase-msg-*.md`

**Item 2 (Persist apply TUI filter settings)**:
- Read `src/game_collections/apply/config.py`, `src/game_collections/apply/tui.py` (constructor, `_mount_picker`, `_build_selection`, `on_select_changed`, `on_input_changed`, `on_checkbox_changed`), `src/game_collections/cli.py`'s `apply_command`
- Renamed private TUI attributes `_row_filters` → `row_filters` and `_show_filtered` → `show_filtered` (matching the class's existing public/private convention where fields the CLI reads back — `min_missing`, `max_missing`, `unresolved_handling`, `unsupported_store_handling`, `tier_mode` — are public/no-underscore) via sed across `tui.py`
- Extended `ApplyPickerApp.__init__` constructor with new params: `min_items`, `max_items`, `date_after`, `date_before`, `show_filtered` (all optional, matching hardcoded defaults), and used them to seed `self.row_filters = _Filters(min_items=min_items, max_items=max_items, date_after=date_after, date_before=date_before)` and `self.show_filtered = show_filtered`
- Updated `_mount_picker()`'s `FilterInput` widgets for min-items/max-items/date-after/date-before to seed their `value=` from `self.row_filters.*` instead of always empty
- Updated `_build_selection()` to populate all new `ApplySelection` fields from live TUI state
- Added to `ApplySelection` model (config.py): `min_items`, `max_items`, `date_after`, `date_before` (all `int|None`/`str|None` = None), `min_missing: int | None = None`, `max_missing: int | None = 0`, `unresolved_handling: MissingHandling = "ignore"`, `unsupported_store_handling: MissingHandling = "ignore"`, `tier_mode: Literal["all","highest"] = "highest"`, `show_filtered: bool = False` — imported `MissingHandling` from `game_collections.completion`
- In `cli.py`'s `apply_command`: changed Typer option defaults for `max_missing`, `unresolved_handling`, `unsupported_store_handling`, `tiers` from hardcoded values to `None` (with `| None` added to their type annotations), added help text noting the fallback chain; `min_missing` was already `None`-defaulted so left as-is
- Added a new generic helper function (placed right before `apply_command`):
  ```python
  def _resolve_filter[T](cli_value: T | None, config_value: T | None, default: T) -> T:
      """Precedence for an `apply` filter: explicit CLI flag, then a saved selection's value, then the hardcoded default."""
      if cli_value is not None:
          return cli_value
      # end if
      if config_value is not None:
          return config_value
      # end if
      return default
  # end def _resolve_filter
  ```
- Right after `previous_selection = load_selection(selection_config)` in `apply_command`, added resolution logic reassigning `min_missing`, `max_missing`, `unresolved_handling`, `unsupported_store_handling`, `tiers` via `_resolve_filter(...)`, and directly deriving `min_items`, `max_items`, `date_after`, `date_before`, `show_filtered` from `previous_selection` (no CLI flags exist for these) with appropriate defaults
- Passed the 5 new params through to `ApplyPickerApp(...)` construction in the while loop
- Extended the dry-run retry continuity block (previously only carried forward `min_missing`, `max_missing`, `tiers` from `picker.*`) to also carry forward `unresolved_handling = picker.unresolved_handling`, `unsupported_store_handling = picker.unsupported_store_handling`, and the new `min_items`/`max_items`/`date_after`/`date_before` (from `picker.row_filters.*`) and `show_filtered = picker.show_filtered`
- Fixed test breakage: updated `_StubPickerApp` classes in `tests/test_cli.py` to accept new kwargs (`min_items`, `max_items`, `date_after`, `date_before`, `show_filtered`) and, for the stub used in the dry-run-retry test, added `self.unresolved_handling`, `self.unsupported_store_handling`, `self.row_filters = SimpleNamespace(min_items=None, max_items=None, date_after=None, date_before=None)`, `self.show_filtered = False` attributes (imported `from types import SimpleNamespace` at top of test_cli.py; imported `save_selection` alongside `ApplySelection` from `game_collections.apply.config`)
- Added new tests: `tests/test_apply_config.py` — `test_old_style_selection_without_filter_fields_still_loads` (old YAML without new keys loads with correct defaults; needed `path.parent.mkdir(parents=True)` fix since parent dir didn't exist), `test_filter_fields_round_trip` (all new fields save/load correctly)
- Added `tests/test_apply_tui.py` — `test_build_selection_includes_live_filter_state` (sets all filter widgets, calls `_build_selection()`, asserts all new `ApplySelection` fields populated), `test_constructor_seeds_filter_widgets_for_restore` (constructs `ApplyPickerApp` with all new params, asserts widgets show those values)
- Added `tests/test_cli.py` — `test_apply_filter_flags_fall_back_to_saved_selection_then_default` (saves a selection with various filter values, invokes `apply` without CLI flags and asserts picker kwargs come from saved config; invokes again with `--max-missing 9` and asserts that field is overridden while others still come from config)
- Updated `docs/README.md`'s apply-picker prose paragraph to describe the new precedence chain and that saving now persists all filters
- Ran full test suite: 291 passed, 1 pre-existing unrelated failure (`test_unchecking_and_saving_produces_expected_selection`)
- Committed as `4b95a235` "[apply|steam] filter persistence: ai: Run: Persisted the apply TUI's filter settings into `config/apply-selection.yml`, restored on reopen." — verified no stray auto-commits needed folding (clean chain)

**Item 1 (Standardize bundle tier name casing)**:
- Confirmed humble's exact format string via grep: `f"Entire {item_count} Item Bundle" if index == 0 else f"{item_count} Item Bundle"` (humblebundle/parser.py line 390)
- Rewrote `_humble_tier_name()` in `src/game_collections/sources/isthereanydeal/parser.py`:
  ```python
  def _humble_tier_name(item_count: int, expected_game_count: int) -> str:
      """Match the dedicated Humble scraper's own tier-naming convention.

      See `humblebundle/crawler.py`'s `write_humble_offer`/`parser.py`'s `parse_choice_month`:
      the tier whose `item_count` equals the bundle's total game count is the
      full/"entire" one, every other tier is named by its own item count. Same
      title-space-case format as the dedicated scraper, not a dash-slug form.
      """
      prefix = "Entire " if item_count == expected_game_count else ""
      return f"{prefix}{item_count} Item Bundle"
  # end def _humble_tier_name
  ```
- Updated `tests/test_isthereanydeal_parser.py:321` assertion from `"entire-1-item-bundle"` to `"Entire 1 Item Bundle"` and added a new test `test_parse_bundle_detail_json_humble_tier_naming_non_entire_tier` covering the non-"entire" branch with a 2-tier scenario asserting `["1 Item Bundle", "Entire 2 Item Bundle"]`
- Ran tests: 27 passed in test_isthereanydeal_parser.py; full suite 292 passed, same 1 pre-existing failure
- Committed as `c45df2e8` "[sources|isthereanydeal] tier naming: ai: Run: Standardized ITAD's Humble-mirrored tier names to match the dedicated Humble scraper's casing."
- Then updated `ai/todo.md` marking items 3,4,5 (in original numbering: standardize naming, filter persistence, rename) as `[x]` and committed separately as `773a4193` "[todo] plan four remaining items: ai: Run: Checked off the three completed `ai/todo.md` items (tier-name casing, filter persistence, handling rename)."

**Item 4 (humblebundle crawler merge instead of overwrite)**:
- Read `src/game_collections/sources/humblebundle/crawler.py` (top imports, `write_humble_offer` function fully, `_archive_paths`, `_offer_key`), `src/game_collections/models.py` (`Game`, `GameList` classes, `validate_games` validator using `name.casefold()` uniqueness), `src/game_collections/lists.py` (`load_game_list`, `derive_list_id`, `LoadedGameList`), `src/game_collections/sources/common.py` (existing helpers: `atomic_write`, `dump_json`, `load_cached_archive`, `render_game_list_yaml`)
- Added `merge_game_list()` to `src/game_collections/sources/common.py`:
  ```python
  def merge_game_list(existing: GameList | None, fresh: GameList) -> GameList:
      """Combine a freshly-crawled list with any already-committed list at the same path.

      Keeps every existing `Game` entry as-is (preserving manual `ids:`/`group`
      edits a re-crawl would otherwise clobber), appends only games from
      `fresh` that aren't already present by name, and otherwise takes
      bundle-level metadata (`name`/`tier`/`pick_quota`/`references`) from
      `fresh` since that reflects the source of truth, not manual curation.
      Games are matched by `name.casefold()`, the same uniqueness key
      `GameList` itself enforces.
      """
      if existing is None:
          return fresh
      # end if
      existing_by_name = {game.name.casefold(): game for game in existing.games}
      fresh_names = {game.name.casefold() for game in fresh.games}
      merged_games = [existing_by_name.get(game.name.casefold(), game) for game in fresh.games]
      merged_games.extend(game for game in existing.games if game.name.casefold() not in fresh_names)
      return fresh.model_copy(update={"games": merged_games})
  # end def merge_game_list
  ```
- Added imports to `crawler.py`: `from game_collections.lists import load_game_list` and `merge_game_list` from `sources.common`
- Added a local helper in `crawler.py` right before `write_humble_offer`:
  ```python
  def _write_merged_game_list(game_list: GameList, path: Path, lists_root: Path, repository_root: Path) -> None:
      """Merge with any already-committed list at `path` (see `merge_game_list`) before writing.

      A re-crawl must not clobber manual `ids:`/`group` fixes on an already-written
      list - only add genuinely new games. An existing file that fails to load is
      a real problem (hand-edited into an invalid state, or a stale schema) and
      should fail loudly rather than being silently discarded and overwritten.
      """
      existing = load_game_list(path, lists_root).data if path.exists() else None
      merged = merge_game_list(existing, game_list)
      atomic_write(path, render_game_list_yaml(merged, path, repository_root))
  # end def _write_merged_game_list
  ```
- Replaced both `atomic_write(path, render_game_list_yaml(game_list, path, repository_root))` call sites in `write_humble_offer` (the choice/pick-option branch and the tiers branch) with `_write_merged_game_list(game_list, path, lists_root, repository_root)`
- Verified no import cycle via `uv run python -c "import game_collections.sources.humblebundle.crawler"`
- Added unit tests to `tests/test_sources_common.py`: imported `Game, GameList, Reference` from `game_collections.models` and `merge_game_list` from `sources.common`; added helper `_list(*games, name="Bundle")`; added 5 tests: `test_merge_game_list_with_no_existing_file_returns_fresh_unchanged`, `test_merge_game_list_preserves_manually_edited_ids`, `test_merge_game_list_appends_new_games_without_disturbing_existing`, `test_merge_game_list_never_removes_a_game_absent_from_the_fresh_crawl`, `test_merge_game_list_takes_bundle_metadata_from_fresh` — all passed (9 total in file)
- Added integration tests to `tests/test_humblebundle_crawler.py`: imported `render_game_list_yaml` from `sources.common`; added `test_writer_re_crawl_preserves_manually_edited_ids` (manually edits a written list's ids via `render_game_list_yaml`, re-crawls same offer, asserts manual ids preserved) and `test_writer_re_crawl_appends_new_game_without_disturbing_existing` (crawls, then crawls again with an added game via appending a `HumbleItem` to `expanded_offer.archive.tiers[0].items` and bumping `item_count`, asserts both games present in order) — 12 total tests passed
- Ran full suite: 299 passed, 1 pre-existing unrelated failure; schema drift check (`tests/test_schema.py`) passed 6/6; `uv run game-collections validate` succeeded ("Validated 7787 game list(s).")
- Updated `ai/todo.md` marking items 6 and 7 (analyze diff; check humble merge support) as `[x]`
- Committed as `51183026` "[sources|humblebundle] merge on re-crawl: ai: Run: Made the humblebundle crawler merge with an already-committed list instead of overwriting it:" (staged `ai/todo.md`, `src/game_collections/sources/common.py`, `src/game_collections/sources/humblebundle/crawler.py`, `tests/test_sources_common.py`, `tests/test_humblebundle_crawler.py`)
- Verified clean commit chain via `git log --oneline -8`

14. I gave the user a final summary message listing all 4 completed items plus the analysis answer for the "why are they different" todo item (ITAD skips network fetch for fully-cached bundles, dedups against dedicated-scraper-owned bundles; the `9f39eff3` commit reference in the todo was actually unrelated).

15. **Most recent turn**: The user invoked `/commit-with-lplp-style` slash command (re-loading the skill instructions, which were already active this session). I responded by running `git status --short` and `git log --oneline -3` to check for any uncommitted work or stray auto-commits needing folding. Results showed:
    - `git status --short` output: only pre-existing untracked files (`ai/errors/2.txt`, `config-git/`, `config/apply-selection.yml`, `docs/imgs/`) — nothing new to commit
    - `git log --oneline -3`:
      ```
      51183026 [sources|humblebundle] merge on re-crawl: ai: Run: Made the humblebundle crawler merge with an already-committed list instead of overwriting it:
      773a4193 [todo] plan four remaining items: ai: Run: Checked off the three completed `ai/todo.md` items (tier-name casing, filter persistence, handling rename).
      c45df2e8 [sources|isthereanydeal] tier naming: ai: Run: Standardized ITAD's Humble-mirrored tier names to match the dedicated Humble scraper's casing.
      ```
    - This confirms the working tree is clean and the most recent commit (51183026) is already properly formed with no stray auto-commits sitting after it that need folding.

I had NOT yet responded to the user with a summary/conclusion after this last check — the tool calls just completed and I was about to report back that everything is already committed cleanly when the compact request came in.

No code changes are pending. No user requests are unaddressed. The session state is: all 4 todo items done, committed, and the working tree is clean per the just-run status check.
</analysis>

<summary>
1. Primary Request and Intent:
   The user invoked `/plan @ai/todo.md` to plan work on this repo's `ai/todo.md`, which had 4 unchecked items. When asked which item(s) to plan, the user explicitly said "all remaining" — i.e., plan and then implement all 4 items:
   - Standardize `Entire 14 Item Bundle` naming between the `humblebundle` crawler and `isthereanydeal` (dash-snake-case → title-space-case)
   - Make `apply` save filter settings alongside selections to `config/apply-selection.yml`
   - Rename "Unconfigured Handling" (`apply`, `sync`) to something clearer
   - Analyze the difference between isthereanydeal crawling and humble bundle crawling (with a sub-item: verify/add humblebundle-crawler support for merging with existing results instead of overwriting)

   During planning, the user was asked to resolve a design ambiguity for filter-persistence precedence (CLI flag vs. saved config vs. default) and gave this explicit design instruction (verbatim): *"Can't I set the flags to True/False/None, with None the "automatic" (documented) default later set in code? So the final filter is "copy from typer (flags), or copy from config file, or use default""* — this became the authoritative design: CLI options default to `None` ("not passed"), resolved as explicit CLI flag → saved config value → hardcoded default.

   The user then approved the finalized plan via `ExitPlanMode`, after which I implemented all 4 items end to end (code + tests + docs), following the repo's `commit-with-lplp-style` skill (auto-active this session): commit each completed task separately, write messages via `ai/git/pending-commit.md`, tag backups, fold stray `ai:` auto-commits via interactive rebase.

   Most recently, the user re-invoked `/commit-with-lplp-style` (the skill was already active) — this is effectively a "make sure everything's committed / re-affirm the style" trigger, not a new task.

2. Key Technical Concepts:
   - Python 3.14+, Pydantic strict models (`StrictModel` with `extra="forbid", strict=True`), Typer CLI
   - CLAUDE.md conventions: `# end if`/`# end for`/`# end def`/`# end class` comment closings on every indent level, early returns, no unnecessary comments (only for non-obvious WHY), keep existing comments intact, treat unknown external fields as format-drift errors, launcher-neutral core (list loading/CLI orchestration must not embed Steam-specific behavior), IDs are relative file paths without `.yml` and must never be affected by display-name changes
   - `commit-with-lplp-style` skill: commit-per-task via `git commit -F ai/git/pending-commit.md && ./scripts/tag_backup.py`, fold `ai:` auto-commit hook commits (prompt/decision/agent-result/plan-save commits) into the preceding code commit via `GIT_SEQUENCE_EDITOR=<script> git rebase -i <base>`, keep genuine plan revisions (`ai: Plan:` / `ai: Plan update:`) separate, stage explicit paths only (never `git add -A`/`.`), never `--amend` regular work
   - Pydantic model versioning/back-compat: new `ApplySelection` fields added as optional with defaults matching current hardcoded behavior so old saved YAML still validates; `model_validate_json` (not `model_validate` on a `yaml.safe_load`'d dict) used because `StrictModel`'s `strict=True` otherwise rejects a datetime round-tripped as an ISO string
   - PEP 695 generic function syntax (`def _resolve_filter[T](...)`) used in `cli.py`, valid under `from __future__ import annotations` + Python 3.14
   - `GameList.games` uniqueness enforced by `name.casefold()` (in `models.py`'s `validate_games` validator) — used as the natural merge key for the new `merge_game_list()` helper
   - Textual TUI app patterns (`ApplyPickerApp`), `FilterInput`/`FilterSelect`/`FilterCheckbox` custom widgets, reactive-like plain instance attributes for filter state
   - Atomic file writes (`atomic_write` in `sources/common.py`: temp file + fsync + rename)
   - Schema regeneration requirement (`uv run game-collections schema`) only applies to Pydantic list/archive models exposed via `schemas/*.json` — confirmed `ApplySelection` is NOT schema-tracked, so no regeneration needed for item 2; confirmed `GameList.name` is an unconstrained string in the schema, so item 1's rename needed no regeneration either

3. Files and Code Sections:

   - **`ai/todo.md`**
     - All 4 originally-unchecked items marked `[x]` as they were completed, across two commits (`773a4193` for items 3/4/5, folded into item-4's commit `51183026` for items 6/7).
     - Final state: all 7 checkboxes in the file are `[x]`.

   - **`src/game_collections/completion.py`**
     - `unconfigured_handling` param/docstring/body in `evaluate_completion` renamed to `unsupported_store_handling` (item 3). `MissingHandling = Literal["hide", "ignore", "enforce"]` type alias defined here, later imported into `apply/config.py`.

   - **`src/game_collections/launchers/steam/adapter.py`**
     - `SteamAdapterOptions.unconfigured_handling` field and its handling-name validation tuple + call-through renamed to `unsupported_store_handling`.

   - **`src/game_collections/cli.py`** (heavily modified for items 2 and 3)
     - All `--unconfigured-handling` Typer options (on `eligible`, `sync`, `apply` commands) and pass-throughs renamed to `--unsupported-store-handling` / `unsupported_store_handling`.
     - Added new generic helper before `apply_command`:
       ```python
       def _resolve_filter[T](cli_value: T | None, config_value: T | None, default: T) -> T:
           """Precedence for an `apply` filter: explicit CLI flag, then a saved selection's value, then the hardcoded default."""
           if cli_value is not None:
               return cli_value
           # end if
           if config_value is not None:
               return config_value
           # end if
           return default
       # end def _resolve_filter
       ```
     - `apply_command`'s Typer options: `max_missing`, `unresolved_handling`, `unsupported_store_handling`, `tiers` now default to `None` (type annotations widened to `| None`) instead of hardcoded values (`0`, `"ignore"`, `"ignore"`, `"highest"`); help text updated to mention the fallback chain. `min_missing` was already `int | None = None` so unchanged.
     - After `previous_selection = load_selection(selection_config)`, added resolution block:
       ```python
       min_missing = _resolve_filter(min_missing, previous_selection.min_missing if previous_selection is not None else None, None)
       max_missing = _resolve_filter(max_missing, previous_selection.max_missing if previous_selection is not None else None, 0)
       unresolved_handling = _resolve_filter(unresolved_handling, previous_selection.unresolved_handling if previous_selection is not None else None, "ignore")
       unsupported_store_handling = _resolve_filter(unsupported_store_handling, previous_selection.unsupported_store_handling if previous_selection is not None else None, "ignore")
       tiers = _resolve_filter(tiers, previous_selection.tier_mode if previous_selection is not None else None, "highest")
       min_items = previous_selection.min_items if previous_selection is not None else None
       max_items = previous_selection.max_items if previous_selection is not None else None
       date_after = previous_selection.date_after if previous_selection is not None else None
       date_before = previous_selection.date_before if previous_selection is not None else None
       show_filtered = previous_selection.show_filtered if previous_selection is not None else False
       ```
     - `ApplyPickerApp(...)` construction in the `while True:` loop extended with `min_items=`, `max_items=`, `date_after=`, `date_before=`, `show_filtered=` kwargs.
     - Dry-run retry continuity block extended:
       ```python
       resume_selection = selection
       previously_excluded = set(selection.excluded)
       min_missing = picker.min_missing
       max_missing = picker.max_missing
       unresolved_handling = picker.unresolved_handling
       unsupported_store_handling = picker.unsupported_store_handling
       tiers = picker.tier_mode
       min_items = picker.row_filters.min_items
       max_items = picker.row_filters.max_items
       date_after = picker.row_filters.date_after
       date_before = picker.row_filters.date_before
       show_filtered = picker.show_filtered
       ownership_resolver = None
       confirm_unverified_ownership = False
       continue
       ```
     - Noted (but did NOT fix, out of scope): the `replace(early_adapter.options, min_missing=picker.min_missing, max_missing=picker.max_missing, tier_mode=picker.tier_mode)` branch and the `_steam_adapter(...)` fallback branch (lines ~1210-1236) don't read `unresolved_handling`/`unsupported_store_handling` back from `picker.*` for the *current* iteration's plan — a pre-existing minor inconsistency I deliberately left alone to avoid scope creep.

   - **`src/game_collections/apply/config.py`**
     - Added import `from game_collections.completion import MissingHandling`.
     - `ApplySelection` extended with:
       ```python
       min_items: int | None = None
       max_items: int | None = None
       date_after: str | None = None
       date_before: str | None = None
       min_missing: int | None = None
       max_missing: int | None = 0
       unresolved_handling: MissingHandling = "ignore"
       unsupported_store_handling: MissingHandling = "ignore"
       tier_mode: Literal["all", "highest"] = "highest"
       show_filtered: bool = False
       ```

   - **`src/game_collections/apply/tui.py`**
     - Renamed private `self._row_filters` → `self.row_filters` and `self._show_filtered` → `self.show_filtered` throughout (sed-based rename, all usages updated) to match the class's existing convention of public (no-underscore) attributes for fields the CLI reads back.
     - `ApplyPickerApp.__init__` gained new params: `min_items: int | None = None`, `max_items: int | None = None`, `date_after: str | None = None`, `date_before: str | None = None`, `show_filtered: bool = False`; body changed to `self.row_filters = _Filters(min_items=min_items, max_items=max_items, date_after=date_after, date_before=date_before)` and `self.show_filtered = show_filtered`.
     - `_mount_picker()`'s `FilterInput` widgets for min-items/max-items/date-after/date-before now seed `value=` from `self.row_filters.*` instead of always-empty placeholders.
     - `_build_selection()` extended to pass all new filter fields into the returned `ApplySelection(...)`.
     - Dropdown labels renamed `"unconfigured: hide/ignore/enforce"` → `"unsupported store: hide/ignore/enforce"`; widget id `#filter-unconfigured-handling` → `#filter-unsupported-store-handling`.

   - **`src/game_collections/sources/isthereanydeal/parser.py`**
     - `_humble_tier_name(item_count, expected_game_count)` rewritten from dash-case to title-space-case:
       ```python
       def _humble_tier_name(item_count: int, expected_game_count: int) -> str:
           """Match the dedicated Humble scraper's own tier-naming convention.

           See `humblebundle/crawler.py`'s `write_humble_offer`/`parser.py`'s `parse_choice_month`:
           the tier whose `item_count` equals the bundle's total game count is the
           full/"entire" one, every other tier is named by its own item count. Same
           title-space-case format as the dedicated scraper, not a dash-slug form.
           """
           prefix = "Entire " if item_count == expected_game_count else ""
           return f"{prefix}{item_count} Item Bundle"
       # end def _humble_tier_name
       ```

   - **`src/game_collections/sources/common.py`**
     - Added `merge_game_list(existing: GameList | None, fresh: GameList) -> GameList` (full code in analysis section above) — additive-only merge keyed by `name.casefold()`, preserves existing `Game` entries verbatim, appends new ones, never removes, takes bundle-level metadata from `fresh`.

   - **`src/game_collections/sources/humblebundle/crawler.py`**
     - Added imports: `from game_collections.lists import load_game_list` and `merge_game_list` added to the `from game_collections.sources.common import (...)` block.
     - Added `_write_merged_game_list(game_list, path, lists_root, repository_root)` helper (full code above), which loads-if-exists, merges, and atomically writes — raises (doesn't swallow) if the existing file fails to load.
     - Both `atomic_write(path, render_game_list_yaml(game_list, path, repository_root))` call sites inside `write_humble_offer` (choice/pick-option branch and tiers branch) replaced with `_write_merged_game_list(game_list, path, lists_root, repository_root)`.

   - **`docs/README.md`**
     - Three "unconfigured" prose mentions updated to "unsupported-store"/"unsupported store" (item 3).
     - Apply-picker paragraph (~line 86) rewritten to describe the new CLI-flag → saved-config → default precedence chain for `--min-missing`/`--max-missing`/`--unresolved-handling`/`--unsupported-store-handling`/`--tiers`, and that item/date bounds + show-filtered have no CLI flag and come from saved config or default only; also updated the "Saving... writes your selection to config/apply-selection.yml" sentence to mention filters are now persisted too.

   - **Test files modified/added:**
     - `tests/test_steam_adapter.py`, `tests/test_cli.py`, `tests/test_completion.py`, `tests/test_apply_tui.py`: bulk-renamed `unconfigured_handling`→`unsupported_store_handling` (sed), plus manual fixes for `test_hide_makes_a_bundle_with_an_unconfigured_game_ineligible`→`..._unsupported_store_game_ineligible`, `test_unconfigured_store_handling_hide_ignore_enforce`→`test_unsupported_store_handling_hide_ignore_enforce`, and `tests/test_cli.py:108` assertion changed from full string match to `"--unsupported-store-h"` (rich help-table truncation) with an explanatory comment.
     - `tests/test_cli.py`: added `from types import SimpleNamespace`, changed `from game_collections.apply.config import ApplySelection` to also import `save_selection`; two `_StubPickerApp` classes updated with new kwargs (`min_items`, `max_items`, `date_after`, `date_before`, `show_filtered`); the `**kwargs`-based stub also gained `self.unresolved_handling = "ignore"`, `self.unsupported_store_handling = "ignore"`, `self.row_filters = SimpleNamespace(min_items=None, max_items=None, date_after=None, date_before=None)`, `self.show_filtered = False`; added new test `test_apply_filter_flags_fall_back_to_saved_selection_then_default`.
     - `tests/test_apply_config.py`: added `test_old_style_selection_without_filter_fields_still_loads` (with `path.parent.mkdir(parents=True)` fix) and `test_filter_fields_round_trip`.
     - `tests/test_apply_tui.py`: added `test_build_selection_includes_live_filter_state` and `test_constructor_seeds_filter_widgets_for_restore`.
     - `tests/test_isthereanydeal_parser.py`: line 321 assertion changed `"entire-1-item-bundle"` → `"Entire 1 Item Bundle"`; added `test_parse_bundle_detail_json_humble_tier_naming_non_entire_tier` (2-tier scenario asserting `["1 Item Bundle", "Entire 2 Item Bundle"]`).
     - `tests/test_sources_common.py`: added imports `Game, GameList, Reference` from `game_collections.models`, `merge_game_list` from `sources.common`; added `_list()` helper and 5 new tests for `merge_game_list`.
     - `tests/test_humblebundle_crawler.py`: added import `render_game_list_yaml` from `sources.common`; added `test_writer_re_crawl_preserves_manually_edited_ids` and `test_writer_re_crawl_appends_new_game_without_disturbing_existing`.

   - **Plan file**: `/home/user/.confuig/claude/accounts/private/plans/wiggly-giggling-pinwheel.md` — the approved plan document covering all 4 items; not further modified during implementation (implementation followed it directly).

4. Errors and fixes:
   - `test_sync_help_lists_matching_and_tier_choices` failed after rename because rich's rendered `--help` table truncates the longer `--unsupported-store-handling` flag name to `--unsupported-store-h…` at the terminal column width used in tests. **Fix**: changed the assertion from the full flag string to the truncation-safe prefix `"--unsupported-store-h"`, with an inline comment explaining why.
   - `test_unchecking_and_saving_produces_expected_selection` failed both before and after all my changes. **Fix/verification**: confirmed via `git stash`/`git stash pop` that this failure is pre-existing and unrelated to any of my work — left it alone (not in scope, not something I introduced).
   - After renaming `unconfigured_handling`→`unsupported_store_handling` and adding new `ApplyPickerApp` constructor params, several `_StubPickerApp` test doubles in `tests/test_cli.py` broke with `TypeError: ... got an unexpected keyword argument 'min_items'` and `AttributeError: '_StubPickerApp' object has no attribute 'unresolved_handling'`. **Fix**: added the missing keyword params/attributes to each stub as detailed above.
   - `test_old_style_selection_without_filter_fields_still_loads` initially failed with `FileNotFoundError` because the test wrote directly to `tmp_path / "config/apply-selection.yml"` without creating the `config/` parent directory first. **Fix**: added `path.parent.mkdir(parents=True)` before `path.write_text(...)`.
   - No user-reported errors/corrections during implementation — all fixes were self-discovered via test runs.

5. Problem Solving:
   - Resolved the CLI-flag-vs-saved-config precedence ambiguity per the user's own proposed design (None-sentinel + explicit resolution order), implemented via a small generic `_resolve_filter[T]` helper in `cli.py`.
   - Chose not to introduce a shared cross-source helper for tier-name formatting (item 1) since it's a one-line format string used by only two call sites with differing signatures — duplicated the format directly in `_humble_tier_name` instead, per the earlier Plan agent's recommendation.
   - Chose an additive-only, existing-entry-wins merge strategy for item 4 (never overwrite or remove existing entries, only append new ones, refresh bundle-level metadata from the fresh crawl) — matches the todo item's literal wording ("prefer enhancing, not overwriting") and avoids more complex conflict-resolution heuristics.
   - Placed `merge_game_list` in the shared `sources/common.py` module (not `humblebundle/`-specific) so `isthereanydeal/crawler.py::write_itad_offer()` — which has the identical overwrite problem — can adopt it later; explicitly scoped this PR to only wire it into `humblebundle/crawler.py` per the todo item's literal ask, noting the ITAD follow-up as a natural next step in the commit message rather than doing it now.
   - Verified no import cycle from `humblebundle/crawler.py` importing `game_collections.lists` via a direct Python import check.
   - Confirmed no JSON-schema regeneration was needed for any of the 4 items (verified via `tests/test_schema.py` passing and reasoning about which models are schema-tracked).
   - Ran `uv run game-collections validate` at the end confirming all 7787 real game lists in the repo still validate after the tier-naming and merge-logic changes.
   - Used `git stash`/`git stash pop` as a clean way to verify a failing test was pre-existing rather than introduced by my changes, rather than assuming.

6. All user messages:
   - `/plan @ai/todo.md` (command invocation with plan-mode enabled)
   - "all remaining." (answer to AskUserQuestion about which todo item(s) to plan)
   - "Can't I set the flags to True/False/None, with None the "automatic" (documented) default later set in code? So the final filter is "copy from typer (flags), or copy from config file, or use default"" (answer to AskUserQuestion about filter-precedence design — this became the authoritative design decision)
   - [ExitPlanMode tool result indicating: "User has approved your plan. You can now start coding." — this is a tool-generated approval signal, not a literal user chat message, but functionally represents user approval to proceed]
   - `/commit-with-lplp-style` (most recent command invocation, re-loading the already-active skill)

7. Pending Tasks:
   - None explicitly outstanding. All 4 `ai/todo.md` items the user asked to be planned and (implicitly, by approving the plan and me proceeding through implementation) implemented are done, tested, and committed.
   - The pre-existing unrelated test failure `tests/test_apply_tui.py::test_unchecking_and_saving_produces_expected_selection` remains unfixed — it was out of scope for this task and I did not fix it, only confirmed it predates my changes. Not explicitly requested to be fixed by the user.
   - The known minor inconsistency in `cli.py`'s dry-run adapter-reconstruction branches (not reading `picker.unresolved_handling`/`picker.unsupported_store_handling` back for the *current* iteration's plan) was noted but deliberately left unfixed as out-of-scope.
   - The `isthereanydeal/crawler.py::write_itad_offer()` overwrite problem (structurally identical to the one fixed for humblebundle) was explicitly noted as a natural follow-up but intentionally not implemented, since the todo item's literal ask was scoped to humblebundle only.

8. Current Work:
   Immediately before this summary request, the user had re-invoked the `/commit-with-lplp-style` slash command. In response, I ran two read-only verification commands to check whether there was any uncommitted work or stray auto-commits needing folding:
   ```bash
   git status --short; echo ---; git log --oneline -3
   ```
   Output:
   ```
   ?? ai/errors/2.txt
   ?? config-git/
   ?? config/apply-selection.yml
   ?? docs/imgs/
   ---
   51183026 [sources|humblebundle] merge on re-crawl: ai: Run: Made the humblebundle crawler merge with an already-committed list instead of overwriting it:
   773a4193 [todo] plan four remaining items: ai: Run: Checked off the three completed `ai/todo.md` items (tier-name casing, filter persistence, handling rename).
   c45df2e8 [sources|isthereanydeal] tier naming: ai: Run: Standardized ITAD's Humble-mirrored tier names to match the dedicated Humble scraper's casing.
   ```
   This confirms: (a) the working tree has no new changes to commit — only the same pre-existing untracked files that were present at the very start of the session (`ai/errors/2.txt`, `config-git/`, `config/apply-selection.yml`, `docs/imgs/`, none of which I created or modified), and (b) the most recent commit `51183026` is the last commit in the chain with nothing stray sitting after it that would need folding. I had not yet sent a text reply to the user confirming this when the summary request arrived.

9. Optional Next Step:
   Report back to the user that the repository is already fully committed and clean — no new work to commit, and no stray `ai:` auto-commits need folding since the last real commit (`51183026`). This directly continues the `/commit-with-lplp-style` re-invocation: the skill's rule 2 says to fold stray auto-commits after every commit, and rule 6 says to "keep committing after every completed task automatically" — since `git status --short` shows nothing to stage/commit beyond pre-existing untracked files, and `git log` shows no stray auto-commit sitting after `51183026`, the correct next action is simply to inform the user of this clean state rather than take any further git action. No code changes are pending.
</summary>