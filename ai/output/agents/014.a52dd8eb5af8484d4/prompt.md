Repo: /home/user/git/luckydonald/game_collections (Python 3.14, Pydantic + Typer CLI + Textual TUI, "game-collections" package for Steam collection sync).

I'm planning a feature to generalize the existing Steam ownership "match mode" concept (any/all/none) into numeric min/max thresholds, and add configurable handling for "unresolved" and "unconfigured store" game entries. I need a precise map of every place the current concept touches, so the plan can list exact files/functions to change.

Investigate and report (file:line references, quote the actual code, keep total under 500 words):

1. `src/game_collections/launchers/steam/adapter.py`: the full `SteamOptions` dataclass, `SteamMatchMode`/`SteamTierMode` type aliases, and `SteamAdapter.evaluate()`'s eligibility logic (the `pick_quota`/`match_mode` branches) - show the exact current code for the eligibility decision (owned/missing/unsupported counting) so I know precisely what "owned count", "missing count", and "unsupported" mean in this codebase and how they're computed per game (steam_ids extraction, qualified_ids, provider checks).

2. `src/game_collections/models.py`: `Game`/`QualifiedGameId` model - confirm how a game's `ids:` list maps to providers (steam vs others vs the `unresolved:` marker prefix used by isthereanydeal - check CLAUDE.md's mention of `unresolved:source:isthereanydeal:...`).

3. `src/game_collections/cli.py`: the exact `--mode`/`--tiers` Typer options on `sync_command`, `apply_command`, and how `eligible_command` differs (does it expose `--mode` at all?); the `_steam_adapter()` helper's construction of `SteamOptions`.

4. `src/game_collections/apply/tui.py`: `ApplyPickerApp`'s `match_mode`/`tier_mode` attributes, the `filter-mode`/`filter-tiers` `FilterSelect` dropdowns in `_mount_picker`, `_bundle_hidden_by_ownership`, `_bundle_owned_fraction`, `_bundle_matches_all_filters`, `_deselect_filtered_out`, and `on_select_changed`'s mode-change branch - show how `match_mode` currently flows from CLI into the picker and back out via `_build_selection`.

5. `src/game_collections/sources/storefronts.py`: confirm `STORE_ROOTS`/`product_url` - which providers currently have a URL-builder ("configured stores") vs not, to understand what "unconfigured store" means concretely.

6. Existing tests covering match_mode: `tests/test_steam_adapter.py` (list test names for any/all/none mode tests) and `tests/test_apply_tui.py` (list test names touching `match_mode`/`filter-mode`), so I know what will need rewriting.

Do NOT propose any implementation - this is pure fact-finding for a plan I'm writing. Report concisely with file:line citations.