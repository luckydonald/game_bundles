# Add a Digiphile source (`scrape digiphile`) to game_bundles

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo `e1bfc5d1-e6e8-4eb9-9345-4b41f2436a61` asks for a Digiphile scraper.
List: https://www.digiphile.co/collections, live example https://www.digiphile.co/collections/social-multiplayer-games-collection-digiphile, expired example https://www.digiphile.co/collections/vr-games-showcase-the-new-essentials.
Digiphile is currently only covered indirectly: `lists/digiphile/bundle/2026-10-15_orcatober-aquatic-horrors.yml` and `2026-10-20_social-multiplayer.yml` come from dekudeals and isthereanydeal.
A dedicated scraper gives first-hand tiers, prices, exact dates and Steam ids, covers the 10 older bundles the aggregators never listed, and lets the aggregators dedupe against it through the existing `existing_list_match` / `backfill_existing_lists`.

## Findings (verified live)

- digiphile.co is a Next.js app, not Shopify (`/collections.json` and `/products.json` are 404).
  Plain `httpx` works with any `User-Agent`, including the library default; no Cloudflare challenge, no browser needed.
- The pages are server-rendered, and the full data sits in the RSC flight payload: `<script>self.__next_f.push([1,"…"])</script>` chunks.
  Concatenating the string element (index 1) of every chunk and `json.JSONDecoder().raw_decode`-ing from `"bundles":` (list page) or `"bundle":` (detail page) yields plain JSON.
- `/collections` lists 12 bundles, expired ones included (back to 2025-11), all with `status: "Active"` even when `endsAt` is long past, so status is useless and `startsAt`/`endsAt` are the truth.
  List items are summaries only (no `tiers`/`products`), so every bundle needs its detail page `/collections/<slug>`.
  There is no pagination on the 12.
- A nonexistent slug returns **HTTP 200** with a Next.js "404" body, so "bundle is gone" must be detected by the missing `"bundle":` payload, not by the status code.
- Detail `bundle` has `slug`, `title`, `fullTitle`, `type` (`SteamGame` | `EBook`), `startsAt`/`endsAt`/`sellFrom`/`sellTo`/`upgradeTo` (ISO, exact), `minPrice`/`suggestedPrice`, `bundleTypeTag.name` (Signature Series, Guest Curator, …), `charities[]`, `tiers[]`, `products[]`, `productGroups[]`.
- `tiers[]` have `id`, `name`, `price` (USD), `order`, `type` ∈ `Base` | `Charity` | `Upsell`, `bonusItems[]`.
  - `Base`: the cumulative price breakpoints (`Tier $4.00`, `$6.00`, …).
    Each product points at exactly one tier through `bundleTierId` and lists only the *newly unlocked* games, so higher tiers accumulate (the dekudeals/ITAD lists use exactly the Base tiers as ranks 1..N, name `$4.00 USD`).
  - `Charity`: an optional donation add-on (soundtracks, art books, a cosmetic DLC; Orcatober's has 5 products), not part of the game roster.
  - `Upsell`: separately purchasable add-ons (DLC, or a whole extra game such as *The Bathhouse Restored Edition*); Planet Coaster's "Free Game+" has a $0 Base tier and three Upsell tiers.
- `products[]` have `title`, `type` (`SteamGame` | `EBook`), `price`, `bundleTierId`, `order`, `productGroupId`, `expirationDays`, and for Steam games `steamGameMetadata.steamAppId` (int).
  All 83 Steam products across the 10 Steam bundles carry an app id, so **no resolver, no Steam title search, no `unresolved:` markers** (like dailyindiegame).
- The two EBook bundles (`before-absolute-creator-owned-image-comics`: 86 comics, 16 `productGroups`; `welcome-to-astro-city`: 6) have no Steam id: archive-only, like Fanatical's books.
- Aggregator list names: Orcatober's equals the Digiphile slug, but Social Multiplayer's is `social-multiplayer` (dekudeals' slug) while Digiphile's is `social-multiplayer-games-collection-digiphile`.
  The slugified `title` (`Social Multiplayer` → `social-multiplayer`) matches both, so the dedup trusts a match named exactly after either the slug or the slugified title.

## Decision to confirm

Lists contain **only `Base` tiers** (ranks = Base breakpoints sorted by price, name `4.00 USD` like Fanatical's), identical to what dekudeals and ITAD already wrote, so backfilling the two existing lists stays consistent.
`Charity` and `Upsell` products are recorded completely in the archive (tier type, price, app id) but are not put into the list: they are optional add-ons, not the bundle's roster.
If you would rather have the Upsell games (e.g. The Bathhouse Restored Edition, Planet Coaster 2) in the list, that is a small follow-up on top of the archive data.

## Approach

New package `src/game_collections/sources/digiphile/`, following the `fanatical/` pipeline minus the resolver:

- `models.py`: `DIGIPHILE_V1 = SchemaDateVersion(2026, 10, 28)`, `DigiphileArchive` (`machine_name` = slug, `url`, `name`, `bundle_type` Literal `steam-game`/`ebook`, `charities: list[str]`, `curator_tag`, `min_price`, `suggested_price`, `dates`, `tiers`), `DigiphileTier` (`identifier`, `name`, `tier_type` Literal `base|charity|upsell`, `price`, `items`), `DigiphileItem` (`title`, `product_type`, `price`, `ids`: `steam:<appid>` for Steam products plus the anchor `digiphile:<product ULID>`, see Open point), `DigiphileDates` (`start`/`end` as `ScrapedTimestamp`, confidence 1.0 from `startsAt`/`endsAt`; `first_seen`, `crawled`).
  Base tiers hold cumulative `items` (as in `FanaticalTier`); Charity/Upsell tiers hold only their own.
  `StrictModel`, `Versioned[...]` as in the sibling models.
- `parser.py`: `extract_flight_json(html, key)` (decode chunks, `raw_decode` from `"<key>":`), `parse_bundle_list(html)` → raw summaries (slugs, verbatim for `source.json`), `parse_bundle(html)` → validated `DigiphileDraft` or `DigiphileParseError` when the payload is missing (soft-404) or the shape changed, `bundle_slug(url)` (https, `digiphile.co`/`www.digiphile.co`, `/collections/<slug>` only, `?linkId=…` query ignored), `page_url(slug)`.
- `crawler.py`: `DigiphileHttpClient` (bounded-retry `httpx`, copy of `FanaticalHttpClient`), `crawl_digiphile_offers(fetch, urls=None, crawled=None, archive_root=None, log, on_offer)` with the usual `Bundle x/y` logging, per-bundle error isolation, `load_cached_archive` resume; `write_digiphile_offer(...)` writes `archives/digiphile/bundle/<slug>/{metadata,source}.json`, then the list.
  `source.json` stores the list summary plus the detail `bundle` object verbatim.
- List writing: games of `Base` tiers (`Game(name=title, ids=[steam:<id>, digiphile:…])`), non-Steam products skipped, no Steam game → archive only.
  Multiple Base tiers → `merge_tiered_games` (`sources/common.py`); a single Base tier (indie-boomer-shooters, Free Game+) → plain list without `tiers`.
  Path `lists/digiphile/bundle/<startsAt date>_<slug>.yml`, references: `Digiphile bundle` url, `Crawl metadata`, `Crawl source`; `crawlers: [digiphile]`.
- Dedup: `existing_list_match(lists_root, "digiphile", slug, pool, crawler_name="digiphile")`, also retried with the slugified title; accepted only if `is_same_bundle` (exact slug or exact slugified title, date prefix ignored, same guard as Fanatical against the shared substring match); on a hit `backfill_existing_lists(...)` adds `digiphile:` ids and references and records the crawler.
- `migrations.py`: empty `METADATA_MIGRATIONS` / `SOURCE_MIGRATIONS`; `__init__.py` re-exports.

Wiring (each mirrors the Fanatical commit `1c0c41cc7`):

- `sources/names.py`: `SourceName.DIGIPHILE = "digiphile"`.
- `migrations/schema_versions.py`: register the source for `migrate --type metadata|source`.
- `schema.py`: `generate_/render_/write_digiphile_schema`; regenerate `schemas/digiphile-archive.schema.json` plus the new `SourceName` value in every other `schemas/*-archive.schema.json` with `game-collections schema` (never hand-edit).
- `cli.py`: `scrape digiphile` (`--url` repeatable, `--lists-root`, `--archive-root`, `--refresh/--no-cache`, `--git` session through `git_ops.finish_scrape_git_session(session, ["lists", "archives/digiphile"], message)` and `_git_commit_message`), plus the schema option in `schema_command`.
- Docs: Digiphile section in `sources/README.md`, "Digiphile imports" in the root `README.md`, one-line mentions in `CLAUDE.md` (CLI verb list and architecture) — `lists/README.md` needs only a short "Generated Digiphile lists" note (Base-tier ranks).
- Style per `CLAUDE.md`: full annotations, early returns, bare `# end …` comments, no `_`-prefixed new names or modules (the Fanatical files still use `_helper` names; the new package avoids them), existing comments left intact.

## Tests (offline, `tests/`)

- `tests/digiphile_data.py`: builders producing trimmed flight-payload HTML (`self.__next_f.push` chunks) for a Steam bundle with Base/Charity/Upsell tiers, a single-Base-tier bundle, an EBook bundle, and the soft-404 page.
- `tests/test_digiphile_parser.py`: chunk decoding, tier typing and cumulative Base accumulation, exact dates, `bundle_slug` URL validation (query ignored, foreign hosts rejected), soft-404 → `DigiphileParseError`, unknown/changed shape → error.
- `tests/test_digiphile_crawler.py`: fake `fetch`, caching/resume, explicit `--url`, per-bundle error isolation, list contents (Base ranks only, Charity/Upsell archive-only, EBook archive-only, single tier has no `tiers`), dedup/backfill against pre-existing aggregator lists (exact slug and slugified-title match, no backfill of a similarly named other bundle).
- `tests/test_schema.py` drift check passes after regenerating.

## Verification

1. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests -q -k "digiphile or schema or cli"`, then the full suite; fix anything red in separate commits.
2. `uv run game-collections schema`; the diff must be exactly the new schema file plus the `SourceName` value in the existing archive schemas.
3. Live into a scratch directory (`--lists-root`/`--archive-root` under the scratchpad, not the repo): `scrape digiphile` archives 12 bundles, writes 10 lists (+2 archive-only EBook bundles), a second run resumes from the archive, `--url …/vr-games-showcase-the-new-essentials` and a made-up slug (error, not a crash).
4. Live against a copy of `lists/digiphile`: Orcatober and Social Multiplayer get backfilled (new `digiphile:` ids, `digiphile` in `crawlers`) instead of duplicated; `game-collections validate` passes.
5. No generated `lists/` or `archives/` data is committed with the code (same as the Fanatical commit); the real `scrape --git digiphile` run is a separate manual-scrape commit the user triggers.
6. `sync steam --apply` is not touched.

## Open point

The item `digiphile:` anchor id: Fanatical anchors on its own product slug, but Digiphile products have no slug, only an opaque ULID `id` (`01M36M4WV5MPFC6XDWAXN0NPT1`) and a title.
Plan: anchor on the product `id` (`digiphile:<ULID>`), stable per product and unambiguous (two products can share a base title, e.g. the Steam game and its soundtrack); the existing `steam:` id stays first so Steam matching keeps working.
