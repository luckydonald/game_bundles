# Generalize Steam `mode` into numeric ownership thresholds + configurable unresolved/unconfigured-store handling

## Context

`sync steam`/`apply steam`/the `apply` picker currently gate Steam-collection eligibility with a 3-state `--mode any|all|none` enum (`SteamAdapter.evaluate()` in `src/game_collections/launchers/steam/adapter.py`). This is too coarse for a real use case: finding bundles where you're *almost* done (e.g. own 5 of 8 games, forgot 3 or fewer) can't be expressed by `any`/`all`/`none` at all.

The plan generalizes `mode` into four independent numeric bounds (`min_owned`/`max_owned`/`min_missing`/`max_missing`, each optional) so "all" and "any" become expressible special cases *and* new thresholds like "own at least 5, missing at most 3" become possible. Alongside this, non-Steam game entries (the `unresolved:` marker and games from stores we don't have a URL-builder for) get their own independent `hide`/`ignore`/`enforce` handling instead of always being silently excluded from the ownership count - which is what actually enables meaningful missing-count filtering (today those entries never count as "missing" no matter what).

Decisions made with the user before writing this plan (see prior turn's `AskUserQuestion`):
- Keep `mode`'s old meaning expressible via the new primitives (`any` → `min_owned=1`, `all` → `max_missing=0`, `none` → all four bounds `None`) rather than dropping it outright.
- Default `unresolved_handling`/`unconfigured_handling` to `"ignore"` for both, preserving today's silent-exclusion behavior out of the box.
- Surface the new controls as both CLI flags and picker dropdowns/inputs, mirroring how `mode`/`tiers` work today.
- The user separately confirmed mid-plan: **remove the `mode` dropdown from the picker entirely**, replacing it with `min-missing`/`max-missing` number inputs. Owned-bound (`min_owned`/`max_owned`) picker UI is out of scope for this round - CLI/backend only, can be added later if wanted.

## Design

### 1. New shared completion-counting helper (new module)

Add `src/game_collections/completion.py`:
```python
MissingHandling = Literal["hide", "ignore", "enforce"]

@dataclass(frozen=True, slots=True)
class GameListCompletion:
    total: int              # games counted toward min/max bounds (post hide/enforce adjustment)
    owned_count: int
    missing_count: int
    owned_ids: list[str]        # "steam:<id>" strings, unchanged shape
    missing_ids: list[str]      # "steam:<id>" for real misses, PLUS the compact qualified-id
                                 # string (e.g. "unresolved:...", "gog:...") for any enforced
                                 # non-steam entry - keeps the existing string-list shape, just
                                 # sourced from a different provider for those entries
    unsupported_ids: list[str]  # game *names* for hidden/ignored non-steam entries (matches
                                 # today's CollectionEligibility.unsupported_ids semantics)

def evaluate_completion(
    games: list[Game],
    owned_app_ids: set[int],
    *,
    unresolved_handling: MissingHandling = "ignore",
    unconfigured_handling: MissingHandling = "ignore",
) -> GameListCompletion: ...
```
Per game: classify by qualified_ids into steam / unresolved (all ids have `provider == "unresolved"`) / unconfigured (has a non-steam, non-unresolved id - reuse `game_collections.sources.storefronts.product_url` to check "configured": a provider is configured if `product_url(provider, value)` is not `None`... actually simpler and decoupled from storefronts: unconfigured just means "not steam and not unresolved", regardless of whether it has a store link - keep this module storefronts-independent). Steam games: existing per-game owned-if-any-steam-id-owned logic (moved verbatim from `SteamAdapter.evaluate()`), contribute to `owned_ids`/`missing_ids`/`total`/`owned_count`/`missing_count`. Unresolved/unconfigured games: apply their respective `MissingHandling`:
- `hide`: excluded from everything (not in `total`, not in any id/name list).
- `ignore` (default): excluded from `total`/`owned_count`/`missing_count`, but its name goes into `unsupported_ids` (matches current behavior exactly).
- `enforce`: counted in `total` and `missing_count`, and its first qualified id's `.compact()` string goes into `missing_ids`.

This function is imported and used by **both** `SteamAdapter.evaluate()` (backend/CLI) and `ApplyPickerApp` (picker display), eliminating the current duplication (adapter's inline ownership counting vs. `tui.py`'s separate `_bundle_owned_fraction`/`_game_owned`).

### 2. `SteamOptions` (`launchers/steam/adapter.py`)

Replace `match_mode: SteamMatchMode = "all"` with:
```python
min_owned: int | None = None
max_owned: int | None = None
min_missing: int | None = None
max_missing: int | None = None
unresolved_handling: MissingHandling = "ignore"
unconfigured_handling: MissingHandling = "ignore"
```
`__post_init__` validates each bound `>= 0` when set. Remove `SteamMatchMode` type alias (or keep as a deprecated helper solely for translating old CLI-style shorthand internally, see §4).

`SteamAdapter.evaluate()`: replace the per-game loop with a call to `evaluate_completion(game_list.data.games, owned_app_ids, unresolved_handling=..., unconfigured_handling=...)`, then:
```python
pick_quota = game_list.data.pick_quota
if pick_quota is not None:
    eligible = completion.owned_count >= pick_quota
else:
    eligible = (
        (self.options.min_owned is None or completion.owned_count >= self.options.min_owned)
        and (self.options.max_owned is None or completion.owned_count <= self.options.max_owned)
        and (self.options.min_missing is None or completion.missing_count >= self.options.min_missing)
        and (self.options.max_missing is None or completion.missing_count <= self.options.max_missing)
    )
```
(`pick_quota` keeps priority exactly as today; "none"-equivalent - all four bounds `None` - falls out naturally as "always eligible", no special case needed.)

### 3. CLI (`cli.py`)

- `_steam_adapter()`: replace the `match_mode: SteamMatchMode` param with `min_owned/max_owned/min_missing/max_missing: int | None` + `unresolved_handling/unconfigured_handling: MissingHandling`, forwarded into every `SteamOptions(...)` branch.
- `sync_command`/`apply_command`: replace `--mode` with `--min-owned`/`--max-owned`/`--min-missing`/`--max-missing` (`int | None`, default `None` except `--max-missing` defaults to `0` to preserve today's `mode=all` default behavior) and `--unresolved-handling`/`--unconfigured-handling` (`Literal["hide","ignore","enforce"]`, default `"ignore"`).
- `eligible_command`: currently has **no** `--mode` at all (silently uses `SteamOptions` defaults). Add the same new flags here too for consistency across all three commands (closing that existing gap), same defaults.
- `apply_command`'s post-picker adapter rebuild (`replace(early_adapter.options, ...)`) carries `picker.min_missing`/`picker.max_missing` back in (owned bounds/handling stay at their CLI-supplied values, since the picker doesn't change those this round).

### 4. Picker (`apply/tui.py`)

- Remove the `filter-mode` `FilterSelect` and `self.match_mode` entirely.
- `ApplyPickerApp.__init__` gains `min_missing: int | None`, `max_missing: int | None` (replacing `match_mode`), plus `unresolved_handling`/`unconfigured_handling: MissingHandling` (default `"ignore"`).
- Add two new `FilterInput` fields, `filter-min-missing`/`filter-max-missing`, parsed with the existing `as_int` helper in `on_input_changed` (same pattern as `filter-min-items`/`filter-max-items`).
- Add two new `FilterSelect` dropdowns, `filter-unresolved-handling`/`filter-unconfigured-handling` (options `hide`/`ignore`/`enforce`), following the exact `on_select_changed` "only act on real change" pattern already used for `filter-tiers`.
- `_bundle_hidden_by_ownership`/`_bundle_owned_fraction`/`_game_owned` are replaced by calls into `evaluate_completion(...)` (imported from the new `completion.py`), so bundle-level hide/grey and per-game dim styling both come from the one shared computation. `_bundle_matches_all_filters` swaps its ownership check for the min/max-missing bounds check (mirroring the adapter's bounds logic).
- `_build_selection` unaffected in shape (still gates on `_bundle_matches_all_filters`).

### 5. Tests

- New `tests/test_completion.py`: unit tests for `evaluate_completion` covering steam owned/missing counting (ported from existing adapter tests) and all 3×2 hide/ignore/enforce × (unresolved/unconfigured) combinations.
- `tests/test_steam_adapter.py`: rewrite the `match_mode`-based tests (`test_all_mode_...`, `test_any_mode_...`, `test_none_mode_...`) as threshold-based (`max_missing=0`, `min_owned=1`, no bounds), add a "5 owned, 3 missing tolerated" style test, and hide/ignore/enforce integration tests through `SteamAdapter.evaluate()`. `pick_quota` tests unaffected (logic unchanged).
- `tests/test_apply_tui.py`: rewrite `test_mode_all_hides_partial_ownership_mode_any_only_hides_zero_owned` and `test_mode_and_tiers_selectors_default_to_constructor_args_and_are_changeable` for the new min/max-missing inputs; add tests for the two new hide/ignore/enforce dropdowns affecting picker visibility/dimming.

### 6. Docs

- `README.md`: rewrite every `--mode any|all|none` mention (sync/apply sections) to describe `--min-owned`/`--max-owned`/`--min-missing`/`--max-missing` and the new `--unresolved-handling`/`--unconfigured-handling` flags; rewrite the picker paragraph describing the (now-removed) `mode: off|any|all` dropdown to describe the two number inputs + two handling dropdowns instead.
- `lists/README.md`'s existing `--mode` mentions belong to the unrelated `complete` command (`--mode blank|missing|unresolved|refetch_all`) - confirmed out of scope, no changes needed there.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` - full suite green, including new `test_completion.py`.
- `uv run game-collections sync steam --min-owned 5 --max-missing 3 --source collection` against a local fixture/real account (dry run) to confirm the new "almost complete" filter surfaces the right bundles.
- Launch `apply steam` and manually confirm: `mode` dropdown gone; min/max-missing inputs filter the tree the same way `mode: all`/`any` used to for the `0`/`1`-equivalent cases; the two new hide/ignore/enforce dropdowns visibly change whether unresolved/unconfigured games affect a bundle's `(owned/total)` fraction and dimming.
