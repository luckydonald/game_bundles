# Add a DekuDeals bundle source (`scrape dekudeals`)

## Context

The project has four bundle-aggregator sources (Humble, DailyIndieGame, Green
Man Gaming, isthereanydeal), each crawling one storefront/aggregator into
`lists/<source>/...` + `archives/<source>/...`. dekudeals.com/bundles is a
fifth bundle aggregator worth covering (confirmed live via WebFetch):

- The bundles index (`/bundles`) lists bundle cards (title, tiered prices,
  item counts, end date, thumbnail) each linking to `/bundles/<slug>`.
- A bundle detail page (e.g. `/bundles/crawling-through-the-dungeons`) shows
  tiered pricing (buy-in unlocks more games, like Humble Choice/Deals BYOB)
  and links every game to DekuDeals' own `/items/<game-slug>?platform=all`
  page — **not** directly to Steam/GOG/etc.
- DekuDeals itself frequently just re-lists bundles run by other sites
  already covered here (the example bundle fetched was actually a Humble
  Bundle). This mirrors isthereanydeal's situation exactly.
- A DekuDeals item page (e.g. `/items/dungeon-drafters`) lists every
  storefront DekuDeals tracks for that game (Steam `store.steampowered.com/
  app/<id>/...`, Nintendo, PlayStation, Xbox/Microsoft, Amazon physical
  links, etc.), each as a real outbound URL.

This plan adds `src/game_collections/sources/dekudeals/` following the
existing crawler/parser/(resolver) pipeline, wired into `scrape dekudeals`,
per the user's answers:
- Resolve each game's real storefront IDs **immediately** during the bundle
  crawl (one-pass, like DailyIndieGame's per-game enrichment) rather than
  ITAD's deferred `unresolved:...` + `complete --provider` two-phase flow.
- Always include `dekudeals:<item-slug>` itself as one of the recorded ids.
- Persist resolved item-slug → ids mappings to a reviewed lookup file
  (mirroring Green Man Gaming's `GmgResolutionMap` /
  `config/greenmangaming-store-ids.yml` pattern) so a later crawl run skips
  re-fetching an item page already resolved.
- Replicate isthereanydeal's dedup/backfill logic: when a bundle DekuDeals
  lists is already covered by an existing dedicated-scraper list (matched by
  slug substring, plus Humble Choice's date-based naming), don't create a
  duplicate list file — backfill any storefront ids DekuDeals resolved that
  the existing list's games are missing, tag it with `crawlers: [dekudeals]`,
  and skip re-checking it once every existing game has that.

## New files

`src/game_collections/sources/dekudeals/`
- `models.py` — `DekuPrice`, `DekuItem` (`title`, `ids: list[str]` incl. its
  own `dekudeals:<slug>`, `url`), `DekuTier` (price + unlocked item count +
  items, mirroring `ItadTier`/Humble Choice tier shape so it plugs into the
  existing `TierDefinition`/`Game.tiers`/`merge_tiered_games` machinery in
  `models.py` and `sources/common.py`), `DekuDates` (`end`, `crawled`,
  tz-aware like `DigDates`), `DekuArchive` (`schema`, `machine_name` (slug),
  `url`, `name`, `dates`, `tiers`, cross-tier `game_count` validation like
  `DigArchive.validate_game_count`).
- `parser.py` — HTML parsing modeled on
  `dailyindiegame/parser.py`'s `HTMLParser` subclasses (no JSON-LD available,
  confirmed via WebFetch):
  - `parse_bundle_index_page(html) -> list[str]` — bundle slugs from
    `/bundles/<slug>` links on the index page.
  - `parse_bundle_page(html, url, crawled) -> (DekuArchive-shape draft, source dict)`
    — title, tiers (price/count breakpoints), and per-game `(title,
    item_slug)` pairs from `/items/<slug>` links, analogous to
    `_BundleGamesParser`/`parse_bundle_page` in dailyindiegame's parser but
    tier-aware.
  - `parse_item_page(html, url) -> dict[str, Any]` — every storefront URL
    listed on a `/items/<slug>` page (Steam/Nintendo/PlayStation/Xbox/
    Amazon/etc. anchors), for the crawler to turn into qualified ids.
  - Raise a `DekuParseError(ValueError)` on any structural mismatch, per
    project convention (never guess).
- `crawler.py` — modeled on `dailyindiegame/crawler.py`:
  - Plain `httpx` client (like ITAD's `ItadHttpClient`) is enough here —
    WebFetch got real HTML without a Cloudflare challenge, unlike DIG, so no
    `patchright` browser is needed.
  - `crawl_deku_offers(fetch, urls=None, crawled=None, archive_root=None,
    lists_root=None, resolution_map=GmgResolutionMap-like, log=_NO_LOG,
    on_offer=None) -> DekuCrawlReport` — discover or take explicit bundle
    URLs, skip via `load_cached_archive` when already archived (like DIG),
    then for each new game: reuse an id list from the resolution map if the
    item slug is already a key, otherwise fetch `/items/<slug>`, parse it via
    `parse_item_page`, build ids via
    `storefronts.qualified_ids_from_urls(...)` plus `steam:<id>` when a
    Steam URL was present, append `dekudeals:<slug>`, dedupe, and record the
    new mapping both in-memory (to write once at the end, like GMG's
    resolution map write) and against the item.
  - Dedup/backfill: reuse the exact `_existing_choice_match` /
    `_existing_list_match` / `_flatten_itad_games` / `_backfill_existing_lists`
    approach from `isthereanydeal/crawler.py` — either inline equivalents in
    `dekudeals/crawler.py`, or (preferred, since the logic is
    provider-agnostic) lift those four helpers out of
    `isthereanydeal/crawler.py` into `sources/common.py` and have both
    sources call the shared version. Decide during implementation based on
    how cleanly the ITAD-specific bits (byob/tier terminology) separate out;
    do not duplicate nontrivial logic if a clean extraction is possible.
  - `write_deku_offer(offer, lists_root, archive_root, repository_root) ->
    tuple[Path, ...]` — same shape as `write_dig_offer`/ITAD's writer:
    archive JSON + source JSON + one `lists/dekudeals/bundle/<slug>.yml`
    (flattened `tiers`/`Game.tiers`, per `lists/README.md`'s bundle
    convention) unless backfilling an existing list instead.
- `__init__.py` — re-export the public parser/model/crawler names, matching
  `dailyindiegame/__init__.py`'s pattern.

`config/dekudeals-store-ids.yml` — the persisted `DekuResolutionMap`
(`schema`, `games: dict[item_slug, list[qualified_id]]`), same shape/loader/
renderer as `GmgResolutionMap`/`load_resolution_map`/`render_resolution_map`
in `greenmangaming/resolver.py` (or defined directly in `dekudeals/crawler.py`
if there's no separate resolver step to justify its own `resolver.py`).

## Modified files

- `src/game_collections/schema.py` — add `write_dekudeals_schema`, following
  `write_dailyindiegame_schema`.
- `src/game_collections/cli.py`:
  - Import the new crawler/model symbols (see existing dailyindiegame/GMG
    import blocks).
  - `schema` command: add `--dekudeals-output` defaulting to
    `schemas/dekudeals-archive.schema.json`, call the new writer.
  - New `@scrape_app.command("dekudeals")` — `--url` (repeatable),
    `--lists-root`, `--archive-root`, `--refresh`/`--no-cache`,
    `--resolution-map` (default `config/dekudeals-store-ids.yml`), `--git`/
    `--git-style` (per CLAUDE.md, Humble and isthereanydeal support `--git`;
    add it here too since this is a recurring scrape). Wire
    `finish_scrape_git_session` to commit `lists`, `archives/dekudeals`, and
    the resolution map path, matching GMG's/ITAD's commit-path lists.
- `schemas/dekudeals-archive.schema.json` — generated (`game-collections
  schema`), not hand-written.
- `src/game_collections/sources/README.md` — add a "DekuDeals" paragraph
  next to the other four sources' summaries; mention it in the
  progress-logging/`on_offer` and resume/cache sections' function-name lists.
- Root `README.md` and `lists/README.md` — document `scrape dekudeals` and,
  if list-format specifics differ (they shouldn't beyond the standard bundle
  convention), note it.
- `.github/workflows/*` — leave untouched; CLAUDE.md/README says the
  scheduled scrape workflow is Humble-only, so no new workflow is implied by
  this task unless the user asks separately.

## Tests

New `tests/test_dekudeals.py` (or split
`test_dekudeals_parser.py`/`test_dekudeals_crawler.py` if that matches the
existing per-source test split — check `tests/` naming for
dailyindiegame/greenmangaming before choosing), with fixtures under
`tests/fixtures/dekudeals/` built from real saved HTML (bundle index, one
tiered bundle detail page, a couple of item pages covering Steam + at least
one other storefront + one with no recognized storefront at all), per
"Verify, don't guess external shapes" — no synthetic/invented HTML shapes.
Cover:
- Bundle index parsing → slug list.
- Bundle detail parsing → tiers, item slugs, error on missing structure.
- Item page parsing → storefront URLs, including a game with an unresolvable
  shop (skipped, not guessed, per `is_known_store_url`).
- Resolution-map hit avoids re-fetching an item page (inject a `fetch` that
  raises if called for a slug already in the map).
- Dedup/backfill against an existing Humble-covered list (and, if the
  Humble-Choice-style dedicated naming applies to any real DekuDeals bundle,
  that path too — otherwise the shared `_existing_list_match`-style substring
  path is enough).
- `write_deku_offer` produces schema-valid archive JSON and a `GameList` that
  round-trips through `render_game_list_yaml`.

Update `tests/test_schema.py` if it enumerates sources explicitly (drift
detector).

## Verification

1. `env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test`
2. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_dekudeals.py -q`
   and the full `uv run pytest` to check for regressions/schema drift.
3. `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` and confirm
   `schemas/dekudeals-archive.schema.json` is generated/stable across two
   runs.
4. `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape dekudeals
   --url https://www.dekudeals.com/bundles/<a-live-slug>` against a real,
   currently-live bundle (pick one that is *not* already covered elsewhere,
   to exercise the non-backfill write path) and inspect the written
   `lists/dekudeals/bundle/<slug>.yml` + `archives/dekudeals/...` by hand.
5. Re-run the same command and confirm it's a no-op (cached archive +
   resolution map hits, no refetching), then `--refresh` and confirm it
   re-fetches.
6. `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` over the
   whole `lists/` tree.
