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

## Add-on tiers: `TierDefinition.kind` and `TierDefinition.requires`

Decided with the user: `Charity` and `Upsell` are part of the bundle and keep their categorization.
They need the first Base tier but are otherwise independent of the other tiers and of each other (the dependency is the user's domain knowledge; the payload only exposes `type`, `price` and `order`).
`TierDefinition` (`models.py`) gets two optional fields, both defaulted so every existing list stays valid and unchanged:

- `kind: Literal["base", "charity", "upsell"] = "base"`: the category, taken from Digiphile's tier `type`.
- `requires: list[int] = []`: ranks of tiers whose games this tier also includes; a tier with a non-empty `requires` is *dependent*.

```yaml
tiers:
- {rank: 1, name: 4.00 USD}
- {rank: 2, name: 6.00 USD}
- {rank: 5, name: 16.00 USD}
- {rank: 6, name: Venezuela Earthquake Relief, kind: charity, requires: [1]}
- {rank: 7, name: Snow Riders Map DLC, kind: upsell, requires: [1]}
games:
- {name: Flock Around, ids: [steam:3618030], tiers: [1, 2, 3, 4, 5]}
- {name: 'Lonely Mountains: Snow Riders - Cozy Pack', ids: [steam:4602210], tiers: [6]}
```

Semantics, kept small:

- `Game.tiers` stays the explicit membership (cumulative Base bundles keep writing full membership); `requires` only adds the games of the named tiers.
  `expand_list_tiers` (`lists.py`) builds `#tier-6` from tier 6's own games plus every game of tier 1 (transitive, cycle-safe), so a dependent tier on its own is "first level + this add-on".
  The expanded list keeps its tier definition (`LoadedGameList.tier: TierDefinition | None`), so `rank`, `name`, `kind` and `requires` reach the launcher layer.
- `GameList.validate_games` rejects `requires` naming an unknown rank, the tier itself, or forming a cycle.
- `--tiers highest` keeps its meaning "the highest tier I own" (the highest *eligible* self-contained tier, as today), and additionally merges every dependent tier of the same bundle which is itself eligible (which implies the tiers it requires are fulfilled) into that one collection.
  The collection keeps the highest tier's list id, so its Steam collection id stays stable while add-ons come and go; its games are the union of the owned ids, and its name is extended with each merged add-on's kind label plus its descriptive tier name: `🗃️ Social Multiplayer — 16.00 USD + Charity: Venezuela Earthquake Relief + Upsell: Snow Riders Map DLC` (a `base` kind adds no label).
  `--tiers all` is unchanged: one collection per tier, dependent tiers included.
- New launcher-neutral module `launchers/tier_selection.py` (not in the Steam adapter) holds `select_tiers(eligibility, mode) -> list[SelectedCollection]` (`primary`, `additions`, computed `name`/`owned_ids`), replacing `SteamAdapter._selected_list_ids`; `CollectionEligibility` gains `tier_name`, `tier_kind`, `tier_requires`.
  `SteamAdapter.plan` builds each `PlannedCollectionChange` from a `SelectedCollection`.
- `SteamAdapter._managed_deletions` currently raises on a selected collection whose Steam name is neither the list's plain nor prefixed name, so it must also accept `<expected name> + …` (the previous run's merged name), otherwise the first run after an add-on is bought or removed fails with "ID collision".
- Apply picker (`apply/tui.py`, `apply/metadata.py`): `BundleMetadata` carries `dependent`; `_highest_tier_ids` and `_apply_tier_mode_to_selection` choose the highest among non-dependent tiers only, keep dependent tiers visible and checked under `highest` (the adapter decides per run whether they are eligible and get merged), and `all` is unchanged.
- Digiphile list ranks: Base tiers by ascending price first (1..N, name `4.00 USD`, the same as dekudeals/ITAD wrote), then the Charity and Upsell tiers in Digiphile's own order, each `kind` set and `requires: [1]`.
  Planet Coaster's "Free Game+" has a $0 Base tier, so its Upsells require the free game; any bundle with an add-on gets `tiers` even if it has a single Base tier.
- `merge_tiered_games` (`sources/common.py`) takes optional `kind`/`requires` per tier (extra tuple elements with defaults) instead of a second code path.
- Whether the additive fields need a list schema version step (`migrations/list_versions.py`, `GAMELIST_V2`): none expected since old files validate unchanged; confirm against `tests/test_schema.py` and the migration tests while implementing.

This changes the public list format and the sync behavior, so it ships first in the one work commit: `models.py`, `lists.py`, `launchers/base.py`, new `launchers/tier_selection.py`, Steam adapter, apply picker, regenerated `schemas/game-list.schema.json`, `lists/README.md` (new `kind`/`requires` description), root `README.md` and `CLAUDE.md` (`--tiers` wording).
Tests: `tests/test_lists.py` (expansion, validation errors), new `tests/test_tier_selection.py` (highest eligible base tier, merged name and owned union, ineligible add-on not merged, `all` mode, old lists unchanged), the existing adapter plan test for the relaxed name guard, and the apply tests for dependent rows.

## Approach

New package `src/game_collections/sources/digiphile/`, following the `fanatical/` pipeline minus the resolver:

- `models.py`: `DIGIPHILE_V1 = SchemaDateVersion(2026, 10, 28)`, `DigiphileArchive` (`machine_name` = slug, `url`, `name`, `bundle_type` Literal `steam-game`/`ebook`, `charities: list[str]`, `curator_tag`, `min_price`, `suggested_price`, `dates`, `tiers`), `DigiphileTier` (`identifier`, `name`, `tier_type` Literal `base|charity|upsell`, `price`, `order`, `items`), `DigiphileItem` (`title`, `product_type`, `price`, `ids`: `steam:<appid>` for Steam products plus the anchor `digiphile:<product ULID>`, see Open point), `DigiphileDates` (`start`/`end` as `ScrapedTimestamp`, confidence 1.0 from `startsAt`/`endsAt`; `first_seen`, `crawled`).
  Base tiers hold cumulative `items` (as in `FanaticalTier`); Charity/Upsell tiers hold only their own, the list writer adds the required tier's games.
  `StrictModel`, `Versioned[...]` as in the sibling models.
- `parser.py`: `extract_flight_json(html, key)` (decode chunks, `raw_decode` from `"<key>":`), `parse_bundle_list(html)` → raw summaries (slugs, verbatim for `source.json`), `parse_bundle(html)` → validated `DigiphileDraft` or `DigiphileParseError` when the payload is missing (soft-404) or the shape changed, `bundle_slug(url)` (https, `digiphile.co`/`www.digiphile.co`, `/collections/<slug>` only, `?linkId=…` query ignored), `page_url(slug)`.
- `crawler.py`: `DigiphileHttpClient` (bounded-retry `httpx`, copy of `FanaticalHttpClient`), `crawl_digiphile_offers(fetch, urls=None, crawled=None, archive_root=None, log, on_offer)` with the usual `Bundle x/y` logging, per-bundle error isolation, `load_cached_archive` resume; `write_digiphile_offer(...)` writes `archives/digiphile/bundle/<slug>/{metadata,source}.json`, then the list.
  `source.json` stores the list summary plus the detail `bundle` object verbatim.
- List writing: games of every Steam product (`Base`, `Charity`, `Upsell`) as `Game(name=title, ids=[steam:<appid>, digiphile:<ULID>])`, non-Steam products skipped, no Steam game at all → archive only.
  `tiers` as described above through `merge_tiered_games`; a bundle with a single Base tier and no add-on (indie-boomer-shooters) stays a plain list without `tiers`.
  Path `lists/digiphile/bundle/<startsAt date>_<slug>.yml`, references: `Digiphile bundle` url, `Crawl metadata`, `Crawl source`; `crawlers: [digiphile]`.
- Dedup: `existing_list_match(lists_root, "digiphile", slug, pool, crawler_name="digiphile")`, also retried with the slugified title; accepted only if `is_same_bundle` (exact slug or exact slugified title, date prefix ignored, same guard as Fanatical against the shared substring match); on a hit `backfill_existing_lists(...)` adds `digiphile:` ids and references and records the crawler.
  The two existing aggregator lists only carry the Base tiers and have no add-on tiers; backfill keeps their structure (adding add-on tiers to a foreign list is out of scope), so their Charity/Upsell games are only in the archive until a fresh list replaces them.
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
- `tests/test_digiphile_crawler.py`: fake `fetch`, caching/resume, explicit `--url`, per-bundle error isolation, list contents (Base ranks first then add-on tiers with `kind` and `requires: [1]`, EBook archive-only, single Base tier without add-ons has no `tiers`), dedup/backfill against pre-existing aggregator lists (exact slug and slugified-title match, no backfill of a similarly named other bundle).
- `tests/test_schema.py` drift check passes after regenerating.

## Verification

1. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests -q -k "digiphile or schema or cli"`, then the full suite; fix anything red in separate commits.
2. `uv run game-collections schema`; the diff must be exactly the new schema file plus the `SourceName` value in the existing archive schemas.
3. Live into a scratch directory (`--lists-root`/`--archive-root` under the scratchpad, not the repo): `scrape digiphile` archives 12 bundles, writes 10 lists (+2 archive-only EBook bundles), a second run resumes from the archive, `--url …/vr-games-showcase-the-new-essentials` and a made-up slug (error, not a crash).
4. Live against a copy of `lists/digiphile`: Orcatober and Social Multiplayer get backfilled (new `digiphile:` ids, `digiphile` in `crawlers`) instead of duplicated; `game-collections validate` passes.
5. No generated `lists/` or `archives/` data is committed with the code (same as the Fanatical commit); the real `scrape --git digiphile` run is a separate manual-scrape commit the user triggers.
6. `sync steam --apply` is not touched.

## Anchor id (decided)

Items carry `steam:<appid>` first and the anchor `digiphile:<product ULID>` (e.g. `digiphile:01M36M4WV5MPFC6XDWAXN0NPT1`), because Digiphile products have no slug and two products can share a title prefix (a game and its soundtrack).

## Deviations found while implementing

- The real `lists/digiphile/` already holds all 10 Steam bundles (written by dekudeals and isthereanydeal), so the dedup matters for every one of them.
  It does not use the shared `existing_list_match` at all: `crawler.find_covering_list` matches the date-stripped file stem exactly against the slug or the slugified title, which avoids both older editions and the interactive fuzzy prompt.
- Backfilling the Planet Coaster list produced duplicate qualified ids (the aggregator lists every DLC of a multi-DLC product separately and the fuzzy name match paired them all with one Digiphile product), so the shared `backfill_existing_lists` now gives an id only to the first game claiming it.
- `source.json` holds just the detail page's raw bundle object, since it is a superset of the list entry.
- Add-on tiers are ordered charity before upsell, each by price, because the payload order is arbitrary.
- The mid-implementation picker/adapter design is as planned; `CollectionEligibility` also gained `tier_name`, `tier_kind` and `tier_requires`, and `LoadedGameList` the originating `tier`.
- The `sync_todo` MCP failed to connect in this session, so the todo could not be completed on CalDAV by the agent.
