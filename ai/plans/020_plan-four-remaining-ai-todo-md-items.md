# Plan: four remaining `ai/todo.md` items

## Context

`ai/todo.md` has four unchecked items left. They are independent and will be
implemented/committed as separate tasks (per the `commit-with-lplp-style`
skill active for this repo). Investigated via three parallel Explore passes
and one Plan pass; findings below are already verified against the current
code (line numbers may drift slightly by the time of implementation — treat
them as strong pointers, not gospel).

**Sequencing:** do Item 3 (rename) before Item 2 (persist filters), so the
new persisted field is never named `unconfigured_handling` only to be
renamed again immediately after.

Order: **3 → 2 → 1 → 4** (rename first to avoid churn, then the two apply/TUI
items, then the two crawler items).

---

## Item 3 — Rename "Unconfigured Handling"

**Why:** `unconfigured_handling` sounds like it's about *unconfigured*
lists/games in general, but it specifically means "this game's storefront
was identified but game-collections has no ownership-check/URL-builder
support for that store" — distinct from `unresolved_handling` ("no storefront
could be identified at all"). The internal completion data already calls
this bucket `unsupported_ids` (`completion.py`), so the public name should
match: **rename to `unsupported_store_handling` / `--unsupported-store-handling`.**

**Files to change** (rename `unconfigured_handling` → `unsupported_store_handling`,
`--unconfigured-handling` → `--unsupported-store-handling`, and the TUI
widget id `#filter-unconfigured-handling` → `#filter-unsupported-store-handling`
plus its label text):
- `src/game_collections/completion.py` — `evaluate_completion(...)` param, docstring, body (~lines 29-91)
- `src/game_collections/launchers/steam/adapter.py` — `SteamAdapterOptions.unconfigured_handling` field and call-through (~lines 47, 60, 151)
- `src/game_collections/cli.py` — the `--unconfigured-handling` Typer option on all commands that expose it (`eligible`, `sync`, `apply`) and every pass-through
- `src/game_collections/apply/tui.py` — constructor param, `self.unconfigured_handling`, the `#filter-unconfigured-handling` `FilterSelect` widget + label, its change handler
- `docs/README.md` — three prose mentions (lines ~65, 80, 86); root `README.md` has no mentions (confirmed)
- Tests referencing the old name: `tests/test_completion.py`, `tests/test_steam_adapter.py`, `tests/test_cli.py`, `tests/test_apply_tui.py`

**Breaking change, no alias.** Per CLAUDE.md's stance against compatibility
shims, do a clean rename — document it as a breaking CLI-flag rename in the
commit message and in `docs/README.md`'s prose (no changelog file exists in
this repo). No schema regeneration needed (not a Pydantic list/archive model).

---

## Item 2 — Persist apply TUI filter settings into `config/apply-selection.yml`

**Why:** `apply steam` already saves the selected/excluded bundles to
`config/apply-selection.yml`, but the filter panel (item/date bounds, missing
bounds, unresolved/unsupported-store handling, tier mode, show-filtered
toggle) resets every time the TUI is reopened. The todo asks that filters be
saved alongside the selection.

**Model change** — `src/game_collections/apply/config.py`, `ApplySelection`
(currently `schema_version`, `selected`, `excluded`, `updated_at` only): add
optional fields, all defaulted to today's actual defaults so existing saved
YAML without these keys still validates:
```python
min_items: int | None = None
max_items: int | None = None
date_after: str | None = None
date_before: str | None = None
min_missing: int | None = None
max_missing: int | None = 0
unresolved_handling: MissingHandling = "ignore"
unsupported_store_handling: MissingHandling = "ignore"   # post-item-3 name
tier_mode: Literal["all", "highest"] = "highest"
show_filtered: bool = False
```
Import `MissingHandling` from `game_collections.completion` rather than
redeclaring it.

**Save path** — `src/game_collections/apply/tui.py::_build_selection()`
(~lines 1109-1123): populate the new fields from `self._row_filters.*`,
`self.min_missing`/`max_missing`, `self.unresolved_handling`/
`self.unsupported_store_handling`, `self.tier_mode`, `self._show_filtered`.

**Load path (currently write-only — must be added):** today `cli.py`'s
`apply` command loads `previous_selection` only to seed
`previously_excluded`; filter values always come from CLI flags/Typer
defaults. Give `ApplyPickerApp.__init__` (`tui.py`) new optional params for
the filter fields it doesn't already accept (`min_items`, `max_items`,
`date_after`, `date_before`, `show_filtered`).

**Precedence, per user decision:** change every filter-related Typer option
in `cli.py` (`--min-missing`, `--max-missing`, `--unresolved-handling`,
`--unsupported-store-handling`, `--tiers`, plus any new ones for item/date
bounds and show-filtered) to default to `None` at the Typer/CLI layer —
i.e. "not passed" is now representable, distinct from a real value. The
resolution order becomes, per field: **explicit CLI flag (if not `None`)
→ value from the loaded `ApplySelection` (if `previous_selection` exists and
has it set) → hardcoded documented default** (`max_missing=0`,
`*_handling="ignore"`, `tier_mode="highest"`, `show_filtered=False`, bounds
unset). Resolve this in `cli.py`'s `apply` command right after loading
`previous_selection`, before constructing `ApplyPickerApp`, so `tui.py`
itself always receives fully-resolved values (no three-way logic inside the
TUI). Document the new default-`None` CLI behavior in `docs/README.md`
alongside the existing filter-flag prose.

**Tests:** `tests/test_apply_config.py` (round-trip incl. old-style YAML
missing the new keys), `tests/test_apply_tui.py` (`_build_selection()`
includes new fields; `ApplyPickerApp` seeded from `initial_selection`
restores filter UI state), possibly `tests/test_cli.py` for the restore
precedence. No schema regeneration (`ApplySelection` has no JSON Schema file).

---

## Item 1 — Standardize bundle tier name casing

**Why:** Humble's own crawler names tiers `"Entire N Item Bundle"` /
`"N Item Bundle"` (title-space-case, built inline in
`humblebundle/parser.py::parse_choice_month`, ~line 390). isthereanydeal's
`_humble_tier_name()` (`isthereanydeal/parser.py`, ~lines 245-254) mimics the
same concept but emits dash-snake-case (`"entire-14-item-bundle"`) when
mirroring Humble-sourced bundles. This is purely a display string
(`GameList.name`) — never used for IDs/paths (those use `real_slug`/
`machine_name`), so this is a low-risk rename.

**Fix:** rewrite `_humble_tier_name`'s body to match Humble's own format
directly (no shared helper needed — it's a one-line format string, not worth
factoring into `common.py` for two call sites):
```python
prefix = "Entire " if item_count == expected_game_count else ""
return f"{prefix}{item_count} Item Bundle"
```

**Files:** `src/game_collections/sources/isthereanydeal/parser.py` (the
function above); `tests/test_isthereanydeal_parser.py:321` — update the
assertion from `"entire-1-item-bundle"` to `"Entire 1 Item Bundle"`, and add
a second case covering the non-"entire" branch (`"N Item Bundle"`) for
parity with Humble's own test coverage.

No schema regeneration needed (`name` is an unconstrained string field).

---

## Item 4 — humblebundle crawler: merge instead of overwrite

**Why:** `write_humble_offer()` (`humblebundle/crawler.py`, ~lines 247-352)
never reads the existing `lists/humblebundle/...yml` before writing — it
always builds a fresh `GameList` from the current crawl and does a full
`atomic_write`. Any manual edits (fixed `ids:`, resolved `unresolved:`
markers) get silently clobbered on the next scheduled crawl. The todo asks
to "prefer enhancing, not overwriting."

**Merge strategy** (additive-only, existing entries win):
- Before writing, if `path` already exists, load it via
  `load_game_list(path, lists_root)` (`src/game_collections/lists.py`).
- Merge keyed by `name.casefold()` (already the uniqueness key `GameList`
  enforces, per its validator in `models.py`).
- **Keep every existing `Game` entry exactly as-is** when a name match is
  found (never let a re-crawl regress a manually-fixed `ids:`/`group`).
- **Append** genuinely new games (name not present in the existing file).
- **Never remove** an existing game absent from the fresh crawl (a source
  bundle disappearing/shrinking is more likely a scrape glitch than a real
  removal; silently dropping a still-referenced game is the worse failure
  mode).
- Bundle-level metadata (`name`, `tier`, `pick_quota`, `references`) comes
  from the **fresh** crawl — that's source-of-truth data, not manual
  curation.
- If the existing file fails to load/validate, raise rather than silently
  discarding it (consistent with "treat unknown external fields as errors").

**Where it lives:** a new `merge_game_list(existing: GameList | None, fresh: GameList) -> GameList`
helper in `src/game_collections/sources/common.py` — shared module so
`isthereanydeal/crawler.py::write_itad_offer()` (which has the identical
clobber problem) can adopt it later; only `humblebundle/crawler.py` needs to
actually call it for this item (note the ITAD follow-up in the commit
message as an explicit next step, not done now).

**Files:** `src/game_collections/sources/common.py` (new helper),
`src/game_collections/sources/humblebundle/crawler.py::write_humble_offer()`
(both write sites — choice/pick-option branch and tiers branch — call
`load_game_list` when `path.exists()`, then `merge_game_list`, before
`atomic_write`).

**Tests:** `tests/test_sources_common.py` (new `merge_game_list` unit tests:
fresh path unaffected, existing manual `ids:` preserved, new game appended
without disturbing order, bundle-level metadata refreshed from fresh crawl).
`tests/test_humblebundle_crawler.py` (integration: re-running the crawler
over an already-written list preserves manual edits and adds only new
games). No schema regeneration (crawler logic only, no model shape change).

---

## Verification (all items)

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_isthereanydeal_parser.py tests/test_humblebundle_crawler.py tests/test_sources_common.py tests/test_apply_config.py tests/test_apply_tui.py tests/test_completion.py tests/test_steam_adapter.py tests/test_cli.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema   # confirm no drift (none expected for these items)
```
For item 2/3, additionally exercise `game-collections apply steam` (dry run,
no `--apply`) to confirm the renamed flag and the filter-restore round-trip
behave as expected in the live TUI.
