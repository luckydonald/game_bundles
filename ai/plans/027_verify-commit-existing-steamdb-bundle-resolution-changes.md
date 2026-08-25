# Verify & commit existing SteamDB/bundle-resolution changes

## Context

The user asked to fix two things: (1) SteamDB search only using the "Apps" tab, missing bundle-only results, and (2) the custom "unresolved item" link resolver rejecting Steam bundle URLs like `https://store.steampowered.com/bundle/46228/Forgive_Me_Father_2_Deluxe_Edition/`, plus updating the data model if needed.

Investigation found the working tree already has uncommitted changes that fully implement both fixes, with tests:

- `src/game_collections/sources/humblebundle/steamdb.py`: `STEAMDB_SEARCH_URL` dropped the `a=app` query param (was restricting results to the Apps tab only), now uses SteamDB's unfiltered "Everything" search. `_RESULT_LINK_HREF` now matches both `/app/(\d+)/` and `/bundle/(\d+)/` result rows; bundle rows are surfaced as `"bundle/<id>"`.
- `src/game_collections/sources/humblebundle/resolver.py`: `_search_steam` passes through steamdb bundle results (`result_id` containing `/`) into `StoreCandidate(url=".../bundle/<id>/", qualified_id="steam:bundle/<id>")` instead of assuming everything is an app id.
- `src/game_collections/sources/storefronts.py`: `parse_store_identity` now also matches `/bundle/(\d+)(?:/|$)` in a pasted Steam URL and returns `steam:bundle/<id>` (previously only `/app/<id>/` was accepted, so a bundle URL raised `ValueError`). `product_url` special-cases `bundle/`-prefixed values to build `https://store.steampowered.com/bundle/<id>` correctly.
- `src/game_collections/completion.py`: `evaluate_completion` skips `steam:bundle/<id>` ids when computing owned/missing AppID counts, since Steam's Web API ownership list has no per-bundle ownership signal (only per-AppID). Ids that are only ever `bundle/...` fall through to `unsupported_ids` handling rather than crashing on `int(...)`.
- Data model: no new type was needed. `models.py`'s `QualifiedGameId` (`provider:value`) stays as-is; `steam:bundle/<id>` is a string-prefix convention layered on the existing `steam` provider value, consumed only in the three files above.
- Matching tests already added: `tests/test_humblebundle_steamdb.py`, `tests/test_humblebundle_resolver.py`, `tests/test_storefronts.py`, `tests/test_completion.py`.

Nothing here needs new implementation. The remaining work is to verify the existing changes are correct and complete, then commit them following this repo's commit workflow.

## Steps

1. Run the full test suite to confirm everything passes:
   ```console
   env UV_CACHE_DIR=/tmp/uv-cache uv run pytest
   ```
2. Run `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` and `... schema` to confirm no schema drift was introduced (none expected — no model shape changed, only string-convention handling).
3. Review `git diff` for the changed files once more to confirm nothing extraneous is bundled in.
4. Commit the changes for this task following the `commit-with-lplp-style` skill (already active for this repo per `CLAUDE.md`): stage the specific files listed above (steamdb.py, resolver.py, storefronts.py, completion.py, and their four test files) — not the unrelated already-modified files in git status (README.md, config/humblebundle-store-ids.yml, the bundle list YAMLs) unless the user confirms those belong to the same change. Write the commit message via `ai/git/pending-commit.md` per the skill.

## Verification

- `uv run pytest` passes, especially the four new/changed tests: `test_steamdb_search_url_formats_query`, `test_parse_steamdb_results_includes_bundle_rows`, `test_steamdb_fallback_can_resolve_to_a_bundle`, `test_parse_store_identity_accepts_steam_bundle_url`, `test_product_url_round_trips_steam_bundle_identity`, `test_steam_bundle_only_id_is_treated_as_unsupported_not_a_crash`, `test_steam_bundle_id_alongside_a_real_appid_only_counts_the_appid`.
- `uv run game-collections validate` / `schema` succeed with no diff to `schemas/*.json`.
