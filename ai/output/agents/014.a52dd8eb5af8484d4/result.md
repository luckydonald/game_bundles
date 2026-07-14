Now I have everything needed for a precise report.

## Report: Steam match-mode / ownership-eligibility touch points

**1. `src/game_collections/launchers/steam/adapter.py`**

Type aliases (lines 31-32):
```python
SteamMatchMode = Literal["any", "all", "none"]
SteamTierMode = Literal["all", "highest"]
```

`SteamOptions` dataclass (lines 35-56), frozen/slots, fields: `steam_id`, `steam_root`, `api_key`, `match_mode: SteamMatchMode = "all"`, `tier_mode: SteamTierMode = "all"`, `reconcile_managed: bool = False`, `protected_collection_name: str | None = None`. `__post_init__` (47-53) validates `match_mode in ("any","all","none")` and `tier_mode in ("all","highest")`.

`SteamAdapter.evaluate()` (110-167) is the eligibility core. Per game (117-138): `steam_ids = [id for id in game.qualified_ids if id.provider == "steam"]`; if none, `unsupported.append(game.name)` and skip. Otherwise each steam id's `.value` is parsed to `int` (raising on invalid/non-positive), appended to `required`; game counts as owned (`owned_game_count += 1`) if `any(app_id in owned_app_ids for app_id in game_app_ids)` (136-138) — i.e. ownership is per-game OR across a game's own multiple steam ids, not per-id. After the loop: `missing = sorted(set(required) - owned_app_ids)`, `owned = sorted(set(required) & owned_app_ids)` (140-141) — these are id-level sets, not counts. The decision (142-153):
```python
pick_quota = game_list.data.pick_quota
if self.options.match_mode == "none":
    eligible = True
elif pick_quota is not None:
    eligible = owned_game_count >= pick_quota
elif self.options.match_mode == "any":
    eligible = bool(owned)
else:
    eligible = bool(required) and not missing
```
Note: `pick_quota` (a `GameList` field, numeric threshold already) takes priority over `match_mode` whenever set — this is the closest existing precedent for a numeric-threshold generalization. `owned_game_count` (per-game boolean-OR count) is what `pick_quota` compares against, distinct from `owned`/`missing` (id-level). `CollectionEligibility` is built (154-164) with `owned_ids=[f"steam:{id}" ...]`, `missing_ids=[...]`, `unsupported_ids=unsupported` (game names, not ids).

`SteamAdapter._selected_list_ids()` (194-228) implements `tier_mode`: `"all"` returns all eligible ids; `"highest"` groups by parent path (`list_id.rpartition("/")[0]`) and `tier` rank, picks per-group max rank among eligible ones (raises on ambiguous duplicate rank).

**2. `src/game_collections/models.py`**

`QualifiedGameId` (30-51): `provider: NonEmptyString`, `value: NonEmptyString`; `parse()` splits on first `:` via `partition`, validates provider against `PROVIDER_PATTERN = ^[a-z][a-z0-9-]*$` (line 12). `Game` (54-77): `ids: list[str]`, `qualified_ids` property re-parses each. Nothing in models.py special-cases `unresolved` — it's just a provider string like any other (`unresolved:source:isthereanydeal:...` per CLAUDE.md:32, parsed as provider=`unresolved`). Steam adapter's `unsupported` bucket is simply "no `provider == 'steam'` id present," so `unresolved:...`-only games land there today.

**3. `src/game_collections/cli.py`**

- `sync_command` (867-927): `--mode` (879, `Literal["any","all","none"]`, default `"all"`), `--tiers` (880, `Literal["all","highest"]`, default `"highest"`).
- `apply_command` (930-1019+): same `--mode`/`--tiers` options (942-943), passed both to `_steam_adapter(...)` (978-979) and `ApplyPickerApp(...)` (990-991), then re-merged post-picker via `replace(early_adapter.options, match_mode=picker.match_mode, tier_mode=picker.tier_mode)` (1007) and again at 1018-1019.
- `eligible_command` (838-864) has **no** `--mode`/`--tiers` options at all; it calls `_steam_adapter(steam_root, steam_id, api_key, source, collection)` (856) with no `match_mode`/`tier_mode` args, so it always uses `SteamOptions` defaults (`"all"`/`"all"`).
- `_steam_adapter()` helper (734-792): `match_mode: SteamMatchMode = "all"`, `tier_mode: SteamTierMode = "all"` params, forwarded verbatim into each `SteamOptions(...)` branch (757-763, 767-774, 780-787).

**4. `src/game_collections/apply/tui.py`**

`ApplyPickerApp.__init__` (288-311) stores `self.match_mode`/`self.tier_mode` from constructor args (defaults `"all"`/`"highest"`, note default mismatch vs `SteamOptions`' `"all"`/`"all"`). `_mount_picker` (353-373) builds `filter-mode` `FilterSelect` with options `[("mode: off","none"),("mode: any","any"),("mode: all","all")]` and `filter-tiers` with `[("tiers: highest","highest"),("tiers: all","all")]`. `_bundle_owned_fraction` (452-463) returns `(owned_count, total_games)` or `None` if ownership unknown. `_bundle_hidden_by_ownership` (474-493): hides if `match_mode=="any"` and `owned==0`, or `match_mode=="all"` and `owned<total`; `"none"` never hides. `_bundle_matches_all_filters` (515-530) combines row filters + `_bundle_hidden_by_ownership` + `_bundle_matches_tier_filter`. `_deselect_filtered_out` unchecks bundles failing `_bundle_matches_all_filters`. `on_select_changed` (722-742) handles `filter-mode`/`filter-tiers` id changes, updating `self.match_mode`/`self.tier_mode` and rebuilding. `_build_selection` (849-864) only includes a bundle in `selected` if `list_id in self._checked and _bundle_matches_all_filters(...)`, else it goes to `excluded` — this is how mode flows back out to `ApplySelection`.

**5. `src/game_collections/sources/storefronts.py`**

`STORE_ROOTS`/`StoreName` (14-21) covers exactly `steam, gog, epic, ubisoft, humble` — these are the "configured stores" with a `product_url()` builder (132-144, via `_PRODUCT_PATH_MARKERS`, lines 123-129, same 5 keys). `product_url()` returns `None` for any other provider string, explicitly citing `unresolved` and `isthereanydeal` as markers with "no product page" (136-137) — i.e. "unconfigured store" = any `provider` value absent from `_PRODUCT_PATH_MARKERS`/`STORE_ROOTS`.

**6. Tests**

`tests/test_steam_adapter.py`: `test_all_mode_ignores_games_without_steam_ids`, `test_any_mode_selects_partial_ownership_and_exports_only_owned_ids`, `test_any_mode_requires_at_least_one_owned_steam_id`, `test_none_mode_is_eligible_even_with_zero_owned_games`, `test_none_mode_overrides_an_unmet_pick_quota`, `test_pick_quota_met_is_eligible_regardless_of_match_mode`, `test_pick_quota_not_met_is_ineligible_even_in_any_mode`, `test_pick_quota_combines_with_highest_tier_selection`, plus tier tests (`test_highest_tier_uses_the_tier_field_across_sibling_bundle_directories`, `test_all_tiers_keeps_every_matching_tier`, `test_highest_tier_rejects_ambiguous_numeric_rank`).

`tests/test_apply_tui.py`: `test_mode_all_hides_partial_ownership_mode_any_only_hides_zero_owned` (170), `test_switching_tiers_to_highest_unchecks_lower_sibling_tiers` (794), `test_mode_and_tiers_selectors_default_to_constructor_args_and_are_changeable` (826); `test_filter_deselects_non_matching_bundles` (688) also exercises `_bundle_matches_all_filters`.