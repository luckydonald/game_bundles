## A) Filter settings persistence

**In-memory filter state not persisted** in `src/game_collections/apply/tui.py`:

- `_Filters` dataclass (lines 55–77): `min_items`, `max_items`, `date_after`, `date_before` — bound to `#filter-min-items/-max-items/-date-after/-date-before` widgets, held in `self._row_filters` (set in `on_input_changed`, lines ~1066–1092).
- `self.min_missing` / `self.max_missing` (constructor params, set from `#filter-min-missing`/`#filter-max-missing` in `on_input_changed`, lines 1094–1097).
- `self.unresolved_handling` (`#filter-unresolved-handling` Select, updated in `on_select_changed` around line 976–984).
- `self.unconfigured_handling` (`#filter-unconfigured-handling` Select, updated at lines 985–988).
- `self.tier_mode` (`#filter-tiers` Select "highest"/"all", updated around line 992, drives `_apply_tier_mode_to_selection`).
- `self._show_filtered` (`#filter-show-filtered` Checkbox, `on_checkbox_changed` lines 1036–1039) — whether filtered-out bundles still render (unchecked) in the tree.

All of these live only as instance attributes on `ApplyPickerApp`; the constructor receives them as CLI-flag defaults (`apply` command, `cli.py` ~lines 1050–1051, 1140–1150) but nothing writes them back out.

**Where `ApplySelection` is saved**: `_build_selection()` (tui.py ~lines 1109–1123) builds an `ApplySelection(schema=1, selected=…, excluded=…, updated_at=…)` from `self._checked`/`self._bundles`, filtering by `_bundle_matches_all_filters`. `action_save()` (~line 1130) stores it as `self._pending_selection` and pushes `ApplyActionScreen`; the actual `save_selection(selection, selection_config)` atomic-write call happens in `cli.py` line 1168, inside the `apply` command's picker loop, after `picker.run()` returns and the user chooses an action (save/apply/dry-run/close) in that modal.

**Current `ApplySelection` model** (`apply/config.py` lines 26–34): `schema_version` (alias `schema`, Literal[1]), `selected: list[str]`, `excluded: list[str]`, `updated_at: datetime`. To persist filters, new fields would be needed, e.g.: `min_items`, `max_items`, `date_after`, `date_before`, `min_missing`, `max_missing`, `unresolved_handling: MissingHandling`, `unconfigured_handling: MissingHandling`, `tier_mode: Literal["all","highest"]`, `show_filtered: bool` — all optional/defaulted for backward compatibility with existing saved YAML files (`load_selection` uses strict JSON-mode validation, `config.py` lines 37–58).

## B) "Unconfigured Handling"

Term appears as `--unconfigured-handling` CLI option (`cli.py` lines 922, 974, 1050, help text: *"How games from stores without a URL builder count toward ownership."*), as the `unconfigured_handling` parameter threaded through `completion.py` (line 34), `launchers/steam/adapter.py` (`SteamAdapterOptions.unconfigured_handling`, lines 47, 60, 151), and in the TUI as `self.unconfigured_handling` plus the `#filter-unconfigured-handling` `FilterSelect` widget (tui.py lines 469, 533–544, 690, 867–877, 985–989) with options labeled "unconfigured: hide/ignore/enforce".

**Actual semantics** (`completion.py::evaluate_completion`, lines 29–91): for each game in a list, if it has any Steam qualified ID it's counted normally via Steam ownership. Otherwise the game is classified as `unresolved` (all its qualified IDs have provider `"unresolved"` — i.e., no store/provider could be matched at all) vs. `unconfigured` (everything else — it has a recognized provider/store, but that store has no URL-builder/ownership-check support, e.g. non-Steam storefronts). `unresolved_handling` governs the first case; `unconfigured_handling` governs the second. For each, `MissingHandling` = `"hide"` (drop entirely, counted in `hidden_count`), `"ignore"` (counted in `unsupported_ids`, excluded from totals/required lists), or `"enforce"` (treated as a required-but-always-missing game, added to `missing_ids`/`total`/`missing_count` via `enforced_ids`). So "unconfigured" specifically means "recognized provider, but that provider/store has no ownership-verification support (no Steam app ID, no URL builder)" — distinct from "unresolved" (provider couldn't be identified at all).