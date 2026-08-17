Confirmed: tier-1.yml has 5 games, tier-2.yml ("Beat The Average") has 11 games — ascending item count, full tier highest number. Same pattern as Humble example (tier-1=2 items, tier-2=5 items, tier-3="Entire 9 Item Bundle"). I have everything needed.

## Report

**Both sources use the same convention: ascending tier numbers = ascending item counts; the full/"entire" tier always gets the highest number; `bundle.yml`/`tier: None` is used only when there's exactly one tier.**

**Humble** (`src/game_collections/sources/humblebundle/crawler.py:294-346`): for both Choice pick-options and Games bundles, `rank = enumerate(..., start=1)` walks `archive.tiers` (or `choice_pick_options`) in the order the parser produced them, writing `tier-{rank}.yml` with `tier: rank`, or `bundle.yml`/`tier: None` if only one tier exists (lines 293-316, 335-346). Ordering source: `parser.py:376-406` builds `tiers` by iterating Humble's own `tier_order` array, and `parser.py:488` sorts `choice_pick_options` by ascending `quota`. Confirmed by fixture/test `test_humblebundle_parser.py:87,134` (`tier_order: ["all","basic"]` → `["Entire 2 Item Bundle", "1 Item Bundle"]`, i.e. index 0 = full) but crawler test `test_humblebundle_crawler.py:181-217` builds `archive.tiers` as `[1-item tier, "Entire 3 Item Bundle"]` and asserts `tier-1.yml`↔`tier: 1` for the 1-item tier and `tier-2.yml`↔`tier: 2` for the entire/3-item tier — i.e. tier number rises with item count.

**isthereanydeal** (`src/game_collections/sources/isthereanydeal/crawler.py:459-521`): identical `rank = enumerate(..., start=1)` pattern over `archive.tiers`/`archive.byob_tiers`, same `bundle.yml` fallback for a single tier. Ordering source: `parser.py` preserves ITAD's own embedded/HTML tier order, which is inherently cumulative/ascending (`parser.py:591` comment: "render in ascending-tier order"). Test `test_isthereanydeal_crawler.py:260-322` confirms `tier-1` has `item_count=1`, `tier-2` has `item_count=2`.

**On-disk confirmation:**
- `lists/humblebundle/bundle/2026-06-17_upload-vr-summer-2026/`: tier-1 = "2 Item Bundle", tier-2 = "5 Item Bundle", tier-3 = "Entire 9 Item Bundle".
- `lists/fanatical/bundle/2013-03-05_bundle-four/`: tier-1.yml has 5 games, tier-2.yml ("Beat The Average") has 11 games.

**`src/game_collections/migrate_tiers.py:124-131`** (legacy `N-item-bundle.yml`/`entire-N-item-bundle.yml` filenames) explicitly sorts by ascending item-count `rank` when assigning `tier-{rank}.yml`/`tier: rank`, matching the same convention.

**`lists/README.md:53`** only says "Tier counts and names follow Humble's advertised cumulative tiers" — it does not spell out numbering direction, but the code (both sources) and the migration script agree: **tier number increases with tier size; the full/entire bundle is always the highest-numbered tier.**

No disagreement found between the two sources.