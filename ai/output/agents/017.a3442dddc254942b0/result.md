This confirms the pattern: merging IDs across storefronts for the *same* real game (alias groups) is explicitly OR/alternative semantics — "a Steam DLC and its Epic counterpart" are cross-referenced as the same game, and the merged `ids` list is one Game with multiple alternative identities, not multiple required items.

I have all the information needed to write the final report.

## Summary

**1. Matching logic — OR semantics (any-of), confirmed at file:line:**

- `src/game_collections/completion.py:44-62` (`evaluate_completion`): for each `Game`, it collects all its `steam:` app IDs into `game_app_ids`, then:
  ```python
  if any(app_id in owned_app_ids for app_id in game_app_ids):
      owned_game_count += 1
  ```
  (line 60). A `Game` with multiple Steam IDs counts as owned/eligible if the account owns **any one** of them. This propagates into `owned_count`/`missing_count` used for `pick_quota` and `min_owned`/`max_owned`/`min_missing`/`max_missing` eligibility bounds in `src/game_collections/launchers/steam/adapter.py:150-171` (`SteamAdapter.evaluate`).

**2. Documented intent — OR/alternative-storefronts only, no AND/bundle-of-items concept found:**

- `lists/README.md:21`: "A game can carry multiple IDs when it is available from multiple storefronts."
- `README.md:14-20` shows one ID per game in its example; no multi-id example is given anywhere.
- `docs/README.md:160` and `src/game_collections/sources/isthereanydeal/resolver.py:82-140` describe the ITAD alias mechanism (`resolve_game_with_aliases`), which explicitly merges multiple storefront IDs (e.g. Steam + Epic) for what's confirmed to be **the same real game** — i.e. alternative identities, not separate required items. No comment, doc, or code anywhere describes a Game "requiring" or "bundling" several separately-tracked owned items (AND semantics). This concept does not currently exist in the codebase.

**3. `lists.py` discovery/uniqueness:**

- `discover_game_lists` (`src/game_collections/lists.py:72-101`) loads every `lists/**/*.yml`, and only checks for duplicate/case-colliding **list IDs** (derived from file path) across files (lines 90-99). It does **not** check for duplicate qualified game IDs across different list files.
- Per-list uniqueness is enforced only within `GameList.validate_games` (`src/game_collections/models.py:112-121`): duplicate game names (casefolded) and duplicate qualified IDs are rejected **within one list**, not across lists. So the same `steam:440` could legally appear in two different list files without any validator complaining.

**4. `search.py`/`cli.py complete` — same-provider duplicate ids:**

- The `Game` model itself (`models.py:58-67`) only forbids *exact duplicate* qualified IDs on one game; two different `steam:` IDs on the same Game name are allowed by validation.
- However, `complete_game_list` (`search.py:127-220`) never produces this automatically: `_should_search` (`search.py:82-95`) checks `has_provider = any(value.startswith(f"{provider}:") ...)` — if a game already has any ID for a provider, that provider is skipped in `blank`/`missing`/`unresolved` modes, and `refetch_all` mode strips existing same-provider IDs before re-adding (line 198), so it replaces rather than appends a second one. Getting two `steam:` IDs on one Game currently requires manual YAML editing.

**5. `migrate_tiers.py` / `apply/metadata.py`:**

- Neither interprets per-game `ids` semantics at all. `migrate_tiers.py` only renames/relabels list *files* and sets the list-level `tier` field. `apply/metadata.py`'s `BundleMetadata.item_count = len(game_list.data.games)` (line 59) counts **games**, not ids, so multi-id games aren't double-counted there either — consistent with the OR/single-entity interpretation used everywhere else.

**Bottom line:** Today, owning any one id in a Game's `ids` list counts as owning the whole Game entry — that's the sole semantics implemented and documented. There is no existing notion of a Game requiring multiple ids to be simultaneously owned (AND/bundle semantics); every multi-id mechanism in the repo (docs, `Game` model, ITAD alias merging) treats multiple ids as alternative storefront identities for one logical game.