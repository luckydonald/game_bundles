# Percentage-based ownership bounds

## Context

`sync`/`eligible`/`apply` gate eligibility with four absolute-count bounds: `--min-owned`, `--max-owned`, `--min-missing`, `--max-missing`. These treat "2 missing" the same whether the bundle has 3 games or 8, even though that's a very different completion ratio (66% vs 25%). The user wants percentage-based siblings of these bounds so ratio-based filtering ("at most 25% missing") is possible alongside the existing absolute ones. Per user's answer: cover **both** missing and owned (not missing-only), at the CLI/adapter level; the missing-pct variant should get full parity with `--min-missing`/`--max-missing` (picker fields + persisted selection), matching how those two already work, while owned-pct mirrors the current CLI-only treatment of `--min-owned`/`--max-owned` (no picker fields, not persisted — that's the existing asymmetry, not something this change should fix). No answer was given on combine semantics when both an absolute and pct bound are set for the same direction — defaulting to **AND** (both must hold), consistent with how the existing bounds already combine with each other.

Percentages are plain floats in `0-100` (e.g. `--max-missing-pct 25`), computed as `count / completion.total * 100`. `completion.total` already exists (`GameListCompletion.total` in `src/game_collections/completion.py`) and is exactly `owned_count + missing_count` (hidden games excluded). When `total == 0`, define percentage bounds as vacuously satisfied (skip the pct check for that list) — nothing to divide.

## Core: `src/game_collections/launchers/steam/adapter.py`

- `SteamOptions` (dataclass, ~line 35): add `min_owned_pct: float | None = None`, `max_owned_pct: float | None = None`, `min_missing_pct: float | None = None`, `max_missing_pct: float | None = None`.
- `__post_init__`: extend the existing bound-validation loop to also range-check the four new fields into `[0, 100]` (separate loop or extend the existing `bound_name` tuple with a per-field min/max check).
- `SteamAdapter.evaluate()` (~line 147): after computing `completion`, compute `owned_pct = completion.owned_count / completion.total * 100 if completion.total else None` and `missing_pct = completion.missing_count / completion.total * 100 if completion.total else None`. Extend the `eligible = (...)` boolean (the `else` branch, ~line 159) with four more `and` clauses, each skipped (short-circuited to `True`) when its pct value is `None` (total==0) or its bound is `None` — mirroring the existing `self.options.min_owned is None or ...` pattern exactly.

## CLI: `src/game_collections/cli.py`

- `_steam_adapter` (~line 899): add the four new params, add them to the `bounds` dict (~line 920) that gets `**`-splatted into every `SteamOptions(...)` call — no other change needed there.
- `eligible_command` (~line 1068) and `sync_command` (~line 1118): add four new `typer.Option` params mirroring the existing four exactly (`--min-owned-pct`, `--max-owned-pct`, `--min-missing-pct`, `--max-missing-pct`, all `float | None = None`, help text analogous to the existing ones but stating "percent"), pass through to `_steam_adapter(...)`.
- `apply_command` (~line 1206):
  - `--min-owned-pct`/`--max-owned-pct`: plain CLI passthrough only (like `--min-owned`/`--max-owned` today) — added as options, passed directly into every `_steam_adapter(...)` call site (there are three: initial resolution ~1270, the `resolve_ownership_choice` closure ~1299, and the final adapter build ~1382). Not part of `ApplySelection`, not wired into `ApplyPickerApp`.
  - `--min-missing-pct`/`--max-missing-pct`: full parity with `--min-missing`/`--max-missing` — add `_resolve_filter(min_missing_pct, previous_selection.min_missing_pct if previous_selection is not None else None, None)` (and same for max, default `None`) near line 1247; pass into `ApplyPickerApp(...)` constructor call; read back `picker.min_missing_pct`/`picker.max_missing_pct` at the three spots that currently read `picker.min_missing`/`picker.max_missing` (~1374, ~1390, ~1414) and pass into the final `_steam_adapter(...)`/`replace(early_adapter.options, ...)` calls.

## Persisted selection: `src/game_collections/apply/config.py`

- `ApplySelection` model: add `min_missing_pct: float | None = None`, `max_missing_pct: float | None = None` (next to `min_missing`/`max_missing`, ~line 38). No changes needed to `load_selection`/`save_selection`/`excluded_list_ids` — both are generic over the model's fields already.

## Picker UI: `src/game_collections/apply/tui.py`

- `ApplyPickerApp.__init__` (~line 436): add `min_missing_pct: float | None = None`, `max_missing_pct: float | None = None` params; store as `self.min_missing_pct`/`self.max_missing_pct` (next to `self.min_missing`/`self.max_missing`, ~line 471).
- `_mount_picker` (~line 519): add two more `FilterInput` widgets after the existing `filter-max-missing` one: `id="filter-min-missing-pct"` (placeholder `"min missing %"`) and `id="filter-max-missing-pct"` (placeholder `"max missing %"`), pre-filled from `self.min_missing_pct`/`self.max_missing_pct`.
- `on_input_changed` (~line 1077): add an `as_float` helper alongside the existing `as_int` (same try/except-on-empty-or-invalid shape), and two more `elif` branches for the new widget ids setting `self.min_missing_pct`/`self.max_missing_pct`, followed by the same `self._deselect_filtered_out(); self._rebuild_tree()` calls already at the end of the handler.
- `_bundle_hidden_by_missing_bounds` (~line 733): after the existing `hidden_count`/`min_missing`/`max_missing` checks, add analogous pct checks — compute `missing_pct = completion.missing_count / completion.total * 100 if completion.total else None`, and only compare against `self.min_missing_pct`/`self.max_missing_pct` when `missing_pct is not None` (skip the check on `total == 0`, matching the adapter's vacuous-pass rule).
- `_build_selection` (~line 1134): add `min_missing_pct=self.min_missing_pct, max_missing_pct=self.max_missing_pct` to the `ApplySelection(...)` construction.

## Docs: `docs/README.md`

- Line ~53 examples block: add one example, e.g. `uv run game-collections sync steam --max-missing-pct 25 --tiers all`.
- Line ~65 paragraph ("four independent, optional numeric bounds..."): reword to "eight independent, optional numeric bounds" (or similar), listing the four new `--*-pct` flags, stating they're percentages of the list's total counted games (`0-100`, vacuously satisfied when a list has zero counted games), and that an absolute bound and its pct sibling combine with AND like all the other bounds.
- Line ~86 picker paragraph: extend "The picker exposes `--min-missing`/`--max-missing`..." to also mention `--min-missing-pct`/`--max-missing-pct` as picker fields; extend the `_resolve_filter` precedence-order bullet to include the two new flags; note `--min-owned-pct`/`--max-owned-pct` join `--min-owned`/`--max-owned` as CLI-only (no picker fields).
- Line ~168 `pick_quota` paragraph: extend the "regardless of the `--min-owned`/`--max-owned`/`--min-missing`/`--max-missing` bounds" list to include the four new pct flags.

## Tests

- `tests/test_steam_adapter.py`: add tests mirroring `test_max_missing_zero_ignores_games_without_steam_ids`/`test_min_owned_one_...` for the new pct bounds — in particular a test demonstrating the motivating case: an 8-game list missing 2 (25%) is eligible with `max_missing_pct=30` but not with `max_missing=1`, and a 3-game list missing 2 (66%) is ineligible with `max_missing_pct=30` even though it'd pass a lenient absolute bound — proving the pct and absolute bounds are independent AND-combined checks. Also a zero-total-list case confirming pct bounds don't block it.
- `tests/test_cli.py`: extend/add a fallback-precedence test analogous to `test_apply_filter_flags_fall_back_to_saved_selection_then_default` for `--max-missing-pct` (saved selection value used when flag omitted, CLI overrides when passed).
- `tests/test_apply_config.py`: extend the round-trip test(s) to also set/assert `min_missing_pct`/`max_missing_pct`.
- `tests/test_apply_tui.py`: extend `test_missing_bounds_and_tiers_default_to_constructor_args_and_are_changeable` (or add a sibling test) driving `filter-min-missing-pct`/`filter-max-missing-pct` `Input.Changed` events and asserting `app.min_missing_pct`/`app.max_missing_pct` update and that filtering/`_build_selection` reflect them.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_steam_adapter.py tests/test_cli.py tests/test_apply_config.py tests/test_apply_tui.py -q`
- Manual dry run against the real repo lists: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections sync steam --max-missing-pct 25 --tiers all --log-skips` and confirm the `yuri-in-luck` bundle (missing 1 of 11 ≈ 9%) now shows as eligible even though its absolute `--max-missing 0` default still excludes it — a concrete before/after check that pct bounds behave as intended on real data.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` full suite before considering the change done, per project convention.
