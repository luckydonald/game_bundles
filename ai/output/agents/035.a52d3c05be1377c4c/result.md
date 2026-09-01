These tests parse the generated YAML with `GameList.model_validate`/`yaml.safe_load` and assert on specific fields (name, tier, games, references) rather than comparing full raw YAML text — no fixture files under `tests/fixtures/` are used for any of these four sources (only `tests/fixtures/steam` exists).

## GameList(...) construction call sites

| File:Line | Function | Purpose |
|---|---|---|
| `src/game_collections/sources/humblebundle/crawler.py:328` | `write_humble_offer` (choice-bundle branch) | Fresh crawl output — one `GameList` per choice-tier pick option (`pick-N` pool), written via `_write_merged_game_list` (merges with existing file if present) |
| `src/game_collections/sources/humblebundle/crawler.py:379` | `write_humble_offer` (non-choice/tiered branch) | Fresh crawl output — one `GameList` per bundle tier, also merged via `_write_merged_game_list` |
| `src/game_collections/sources/isthereanydeal/crawler.py:467` | `write_itad_offer` (BYOB pick-pool branch) | Fresh crawl output — one `GameList` per BYOB tier count, written directly with `atomic_write`/`render_game_list_yaml` (no merge) |
| `src/game_collections/sources/isthereanydeal/crawler.py:508` | `write_itad_offer` (regular tier branch) | Fresh crawl output — one `GameList` per tier with games, written via `atomic_write` |
| `src/game_collections/sources/dailyindiegame/crawler.py:277` | `write_dig_offer` | Fresh crawl output — single `GameList` for the whole bundle |
| `src/game_collections/sources/greenmangaming/crawler.py:290` | `write_gmg_offer` | Fresh crawl output — one `GameList` per tier with games |

All six sites are authoritative fresh-crawl writers (each source's `write_*_offer` function); none are for editing/merging existing lists other than the humblebundle ones, which call `_write_merged_game_list` (crawler.py:271) to merge into any pre-existing file at that path rather than blindly overwrite.

## Fixtures check

- `tests/fixtures/` only contains a `steam/` subdirectory (used by `tests/test_steam_io.py`, `tests/test_steam_models.py`); there is no `tests/fixtures/humblebundle`, `tests/fixtures/isthereanydeal`, `tests/fixtures/greenmangaming`, or `tests/fixtures/dailyindiegame`.
- None of `tests/test_humblebundle_crawler.py`, `tests/test_isthereanydeal_crawler.py`, `tests/test_greenmangaming_crawler.py`, `tests/test_dailyindiegame_crawler.py` reference `fixtures/` at all — they generate output into `tmp_path`, then read the produced `bundle.yml`/`tier-N.yml` files back (e.g. `tests/test_humblebundle_crawler.py:100,165,296,340,364,405`; `tests/test_isthereanydeal_crawler.py:283,318,356,372-389`; `tests/test_greenmangaming_crawler.py:69,108`) and assert on parsed field values, not exact raw-text/golden YAML comparisons.
- Therefore adding a new field to the `GameList` model would not break any pre-existing golden/snapshot fixture files for these four sources, since none exist; only the in-test parsed-field assertions in the above test files would need review.