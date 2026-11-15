# Plan: merge into already scraped lists instead of overwriting them

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

Todo: `30adb33d-8a12-4441-9f87-32ef664cf2de` (detect already scraped bundles and merge).

## Context

Direct scrapers rewrite their own `lists/<provider>/...yml` from scratch.
Any `references`, `crawlers` entry and storefront `ids` another scraper (isthereanydeal, dekudeals) had backfilled into that list are lost on the next direct run.
Real cases: `e7b80401f` (greenmangaming dropped the isthereanydeal references, crawler and `isthereanydeal:*` ids from `girls-just-wanna-have-guns-bundle.yml` and `lego-dc-vs-marvel-collection-bundle.yml`), and `010864593` (fanatical dropped the dekudeals data from `2026-10-27_build-your-own-slayer-bundle.yml`).

## Findings

- `greenmangaming/crawler.py` `write_gmg_offer` builds a fresh `GameList` and calls `atomic_write(render_game_list_yaml(...))` with no look at the existing file.
- `fanatical/crawler.py` `write_fanatical_offer` does look for an existing list via `existing_list_match`, but that returns the first *substring* hit in sorted order.
  For `build-your-own-slayer-bundle` that is `2021-07-23_build-your-own-slayer-bundle-2.yml`, which `is_same_bundle` rejects, so `existing` becomes `None` and the fresh list overwrites the 2026 file at the computed path.
- `dekudeals`, `digiphile`, `dailyindiegame` write their own path the same unconditional way, so they have the same latent bug.
- Humble already solves this with `_write_merged_game_list` (`humblebundle/crawler.py`) using `merge_game_list(existing, fresh, authoritative=True)` from `sources/common.py`.
  That unions `references` and `crawlers`, keeps a matched game's existing `ids`/`group`, refreshes tier membership and quarantines vanished games into `invalid`.
- The aggregators (isthereanydeal, dekudeals) already go through `backfill_existing_lists`, which is why they look fine.

## Changes

1. New module `src/game_collections/sources/merged_write.py` with `write_merged_game_list(game_list, path, repository_root)`.
   It loads the existing file at `path` if any (via `lists.load_game_list`, failing loudly on an invalid existing file), merges with `merge_game_list(..., authoritative=True)` and writes through `atomic_write`/`render_game_list_yaml`.
   It moves Humble's helper body here; Humble's `_write_merged_game_list` becomes a thin call to it so behaviour stays identical.
2. Use it at the final write of `greenmangaming`, `fanatical`, `dekudeals`, `digiphile` and `dailyindiegame` crawlers (the "no existing match, write own list" branch), replacing the bare `atomic_write(path, render_game_list_yaml(...))`.
   `isthereanydeal` writes into other providers' directories and already has its own backfill/merge flow, so it is left alone (verify with a read of its two write sites).
3. Fanatical: in `write_fanatical_offer`, when the computed own path already exists, treat it as the existing list (it is by construction the same bundle) before consulting `existing_list_match`, so the substring-hit-on-a-different-edition problem cannot misroute.
4. Docs: a short note in `src/game_collections/sources/README.md` (direct scrapers merge into an existing list instead of overwriting) and in `CLAUDE.md`'s `common.py` line.
   No public list format change, so root `README.md`/`lists/README.md`/schemas stay untouched.

## Tests

- `tests/test_greenmangaming_crawler.py`: pre-seed a list with an extra `isthereanydeal` reference, `crawlers` entry and `isthereanydeal:` id, run `write_gmg_offer`, assert all three survive and gmg's own data is still current.
- `tests/test_fanatical_crawler.py`: pre-seed `2021-..._<slug>-2.yml` plus the own-date list carrying a `dekudeals` crawler/ids, run `write_fanatical_offer`, assert the dekudeals data survives.
- `tests/test_sources_common.py` (or a new `tests/test_merged_write.py`): new file, merge into existing, invalid existing raises.
- Same idempotency check for dekudeals, digiphile, dailyindiegame where a crawler test file exists.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` (full suite) and `uv run game-collections validate`.
- `uv run game-collections schema` is not expected to change; `tests/test_schema.py` confirms.
- No live `scrape` in the real checkout (autostash risk); tests use temp dirs only.
