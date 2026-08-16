I now have enough detail for a comprehensive report.

## Summary

**Pipeline location:** `/home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/` — `crawler.py`, `parser.py`, `resolver.py`, `models.py`, `provider_config.py`, `shop_config.py`, `game_alias_config.py`.

### 1. Bundle/item discovery — no package/DLC/sub-item handling exists

- Discovery: `crawler.py:223-238` `_discover_summaries` pages `POST /bundles/api/list/` (`parser.py:137-164` `parse_list_page`).
- Per-bundle items: `crawler.py:296-371` in `crawl_itad_offers` fetches each `/bundles/<id>/` detail page and parses tiers via `parser.py:325-460` `parse_bundle_detail_json` (primary, reads embedded `var page` JSON `liveData.tiers[].games[]`) or `parser.py:583-699` `parse_bundle_detail_page` (HTML fallback).
- Each `game` entry in a tier yields exactly **one** `ItadItem` (`models.py:23-38`), keyed by `slug`/`title` (`parser.py:388-410`, `parser.py:627-641`). There is no traversal of "Contents of this package," no "contains"/"dlc"/"package"/"sub-item" concept anywhere in this module (`grep` across all files under `sources/isthereanydeal/` for those terms returns nothing relevant — only unrelated matches like regex `.group()` calls and the alias-groups docstring). If ITAD ever exposed a bundled item that is itself a "Frostpunk: GOTY" package containing sub-games, it would currently be treated as one flat slug/title/ids item, not expanded.

### 2. Storefront ID resolution — one bundle item → resolved via reviews, but current code path yields one storefront ID typically, not truly "no multi-ID support"

- `parser.py:308-322` `_resolve_urls(urls, bundle_id, slug)`: calls `qualified_ids_from_urls(urls)` (in `sources/storefronts.py`, not read here) over every `review.url` on that item (`parser.py:395-401`), so it **does already support multiple storefront IDs per item** if the detail page lists multiple recognized store links (e.g. both Steam and GOG). It appends `isthereanydeal:<slug>` always, and `unresolved:source:isthereanydeal:<bundle_id>:<slug>` if none resolved.
- HTML fallback path does the analogous thing at `parser.py:645-647,657-660` (collecting all recognized store `<a href>`s per current slug).
- This is genuinely per-*item* (one ITAD slug), not per-*bundle*; nothing here resolves one item to multiple *separate game entries* (i.e., it does not split a grouped/package item into several `Game`s with different names).

### 3. Provider directory selection + dedicated-scraper skip logic

- Provider directory slug: `provider_config.py:60-78` `resolve_provider_slug`, using reviewed `config/isthereanydeal-providers.yml` (loaded `provider_config.py:39-46`), falling back to a slugified provider name with a warning.
- Skip logic ("already covered by dedicated scraper"): `crawler.py:376-419`, two functions:
  - `_existing_choice_match` (`crawler.py:376-399`): Humble Choice special-case — matches `lists/humblebundle/choice/<YYYY-MM>.yml` by parsing the monthly title pattern.
  - `_existing_list_match` (`crawler.py:402-419`): generic substring dedup — walks `lists_root/<provider_slug>/**` and checks if `real_slug` (the provider's own bundle slug, decoded via `real_provider_slug`, `parser.py:193-202`) appears as a substring in any existing filename.
  - Both are invoked in `write_itad_offer` at `crawler.py:436-442`; if either matches, only the archive (`metadata.json`/`source.json`) is written and the list-write is skipped with a log line (`crawler.py:439-441`). Tested in `tests/test_isthereanydeal_crawler.py:392-408` (greenmangaming) and `:411-434` (humblebundle/choice by month).
- List path construction and write: `crawler.py:444-522`, building `lists/<provider_slug>/bundle/<date-prefix>_<real_slug>/{bundle.yml|tier-N.yml}`, one `Game(name=item.title, ids=item.ids)` per unique item (`crawler.py:448-499`, dedup via `seen_ids`).

### 4. `complete --provider isthereanydeal` per-game solver

- CLI wiring: `cli.py:342-424` `complete_command`; when `"isthereanydeal"` is in selected providers (`cli.py:374-393`), builds `itad_resolve` closure calling `resolve_game_with_aliases` (loads `config/isthereanydeal-game-aliases.yml` via `game_alias_config.py:load_game_alias_config`, `cli.py:376`).
- Core solver: `resolver.py`. `parse_unresolved_marker`/`_UNRESOLVED_PATTERN` (`resolver.py:18-35`) parse `unresolved:source:isthereanydeal:<bundle_id>:<slug>` markers. `resolve_game` (`resolver.py:73-110`) fetches `/game/<slug>/info/` (`parse_game_detail_json`, `parser.py:535-580`) for `steam:<appid>`, plus `qualified_ids_from_urls` over the game's `deals` redirect targets (`resolver.py:48-70,92-96`). `resolve_game_with_aliases` (`resolver.py:113-140`) merges ids across a reviewed alias group of ITAD slugs known to be the same real game (documented use case at `game_alias_config.py:19-20`: DLC named differently per storefront, e.g. Pinball FX vs standalone slug — this is about *cross-platform slug aliasing*, not package/DLC bundling into one `Game`). `resolve_isthereanydeal_markers` (`resolver.py:143-167`) applies this across a `Game.ids` list, dropping the marker once solved.
- `config/isthereanydeal-shops.yml` is used only in the crawler for corroboration logging (`parser.py:269-305`, `crawler.py:284-286,318-322`), not in the resolver.

### 5. Tests/fixtures

- `tests/test_isthereanydeal_parser.py`, `tests/test_isthereanydeal_crawler.py`, `tests/test_isthereanydeal_resolver.py`, `tests/test_isthereanydeal_game_alias_config.py`, `tests/test_isthereanydeal_shop_config.py`. None reference "package," "contains," "DLC," "Frostpunk," or grouped/nested items — confirmed via grep. Existing coverage is entirely flat: one tier → N one-to-one game items, multi-tier cumulative lists, BYOB pools, and the substring-based dedup skip (`test_isthereanydeal_crawler.py:392-434`).

### Where grouped/multi-item logic would need to be added

There is currently no concept of a "package" containing sub-items anywhere in this pipeline — `ItadItem`/`Game` is strictly 1 ITAD slug : 1 entry. To support a package item expanding into multiple `Game`s (or a "prefer more detailed" merge), the natural insertion points are:
- **Parsing**: `parser.py:379-411` (`parse_bundle_detail_json`, JSON-embedded games loop) and `parser.py:607-648` (HTML fallback) — this is where per-item children/sub-items (if ITAD's embedded JSON exposes them, e.g. a `contains`/`children` field on `game`) would need to be detected and expanded into multiple `ItadItem`s or a new nested model.
- **Model**: `models.py` `ItadItem` (currently flat `slug/title/ids`) would need a way to represent grouped sub-items, and downstream `crawler.py:448-499` (`write_itad_offer`'s per-tier `Game` construction) would need to decide whether to emit one `Game` per package or expand into several, plus dedup/"prefer more detailed" logic when the same underlying game appears both standalone and inside a package elsewhere.