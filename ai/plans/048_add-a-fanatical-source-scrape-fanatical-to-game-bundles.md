# Add a Fanatical source (`scrape fanatical`) to game_bundles

## Context

The earlier plan targeted `luckydonald-utils` by mistake.
Everything (code, plan, `ai/` prompt logging, exploration notes) belongs in `~/Documents/programming/Python/game_bundles`, which already has a crawler pipeline per storefront (`src/game_collections/sources/<name>/`: models, parser, crawler, resolver, migrations).
Fanatical is currently only covered indirectly: `lists/fanatical/bundle/*.yml` come from isthereanydeal/dekudeals, and `config/*-providers.yml` already map `Fanatical` to the slug `fanatical`.
A dedicated scraper gives first-hand tiers, prices, dates and Steam IDs, and lets the aggregators dedupe against it through the existing `existing_list_match` / `backfill_existing_lists`.
Targets: a single bundle (e.g. https://www.fanatical.com/en/bundle/coppafeel-charity-bundle) and the list https://www.fanatical.com/en/bundle/games.

## Findings (verified live)

- The pages are a client-rendered SPA, so HTML parsing is the wrong tool.
  Only `window.preloadedName/Slug/Cover` is in the HTML.
- `GET https://www.fanatical.com/api/algolia/bundles` returns plain JSON (HTTP 200, no auth, needs only a browser-like `User-Agent`), one list of 63 currently listed items.
  That is exactly what backs `/en/bundle/games`: 33 `type: "bundle"`, 30 `type: "pick-and-mix"` (Build-Your-Own).
  There is no per-slug detail endpoint (`/api/product|bundle|bundles/<slug>` give 404, `/api/products/<slug>` gives a 403 WAF block), so a single bundle is looked up by filtering the list by slug.
  Expired bundles are therefore not fetchable, which matches the "currently listed" semantics of the other crawlers.
- `type: "bundle"` items carry `bundle_tiers[]`: each has `price` (per currency), `displayTotal`, and `products[]` with `name`, `slug`, `type`, `steamId`, `steamIdType`, `drm`.
  Tiers are cumulative by count (e.g. 4 / 25 / 63) but the `products` arrays are per-tier, so merge them with the shared `sources.common.merge_tiered_games`.
  Single-tier items (12 of 33) with `pay_what_you_want: true` model flat/PWYW bundles such as CoppaFeel (10 games, £5.99 minimum, full price £126.46).
- `type: "pick-and-mix"` items carry `bundle_covers[]` (the whole pick pool, name/slug/type only, no Steam IDs, 30 of them nested `type: "bundle"` sub-collections) plus tiered prices, and no `bundle_tiers`.
- Timestamps `available_valid_from` / `available_valid_until` are real unix epochs, so `ScrapedTimestamp` confidence is high (unlike DailyIndieGame's countdown estimate).
- Product mix: games with `steamId` (~178 plus 63 with an empty `steamIdType`), 51 games with `steamId: null`, and many `book` / `comic` / `software` products with no Steam ID.
  Games without an ID need resolution; books/comics/software are not collectible on Steam.
- Confirmed with the user: use a **title-search resolver** for games without a Steam ID, and handle **bundles plus pick-and-mix (as `pick_quota`)**, archiving books/comics-only bundles without writing a list.

## Approach

Follow the `dekudeals` / `greenmangaming` package pattern, using the JSON API like DekuDeals' embedded Inertia JSON (no browser, no BeautifulSoup).

New package `src/game_collections/sources/fanatical/`:

- `models.py`: strict Pydantic models `FanaticalArchive`, `FanaticalTier`, `FanaticalItem`, `FanaticalPrice` (per-currency dict), `FanaticalDates` (`start`/`end` as `ScrapedTimestamp` with `source=SourceName.FANATICAL`, `first_seen`, `crawled`), plus the version constants `FANATICAL_V1` and `CurrentVersion` / `VersionedFanaticalArchive` like `dailyindiegame/models.py`.
  Unknown fields are errors (`StrictModel`).
- `parser.py`: `parse_bundles_json(text)` returns the validated raw items and splits them into `bundle` and `pick-and-mix`.
  `parse_bundle(item, observed)` builds the `FanaticalArchive` and the `source` payload (the raw item, kept verbatim in `source.json`).
  A `FanaticalParseError` covers shape changes.
- `resolver.py`: Steam ID from `steamId` when `steamIdType` is `app` (or empty with a numeric id, to be checked against a sample when implementing), otherwise the title-search path modelled on `greenmangaming/resolver.py` and `sources/storefronts.py`, cached in `config/fanatical-store-ids.yml` (`FanaticalResolutionMap`, same load/write helpers as `dekudeals/resolver.py`).
  Anything still unresolved becomes `unresolved:source:fanatical:<bundle>:<slug>`.
  Books, comics, audio and software get `fanatical:<slug>` ids only and, for a bundle without a single game, no list is written (archive only).
- `crawler.py`: `FanaticalHttpClient` (a `requests` session with a browser-like `User-Agent`, `fetch(url) -> str`, `close()`, same shape as `DekuHttpClient`), `crawl_fanatical_offers(fetch, mapping, urls=None, crawled=None, archive_root=None, log=..., on_offer=...)`, and `write_fanatical_offer(...)`.
  - `--url` accepts `https://www.fanatical.com/<locale>/(bundle|pick-and-mix)/<slug>` and is validated like `_validated_explicit_url` in the DailyIndieGame crawler (https and `fanatical.com` / `www.fanatical.com` only).
  - Resume behaviour via `load_cached_archive`, per-offer `on_offer` writes, "Bundle x/y" / "  Game x/y" logging, isolated per-bundle errors collected in a `FanaticalCrawlReport`.
  - `write_fanatical_offer` writes `archives/fanatical/bundle/<slug>/{metadata,source}.json` and `lists/fanatical/bundle/<YYYY-MM-DD>_<slug>.yml` (date from `available_valid_from`, matching the existing date-prefixed names).
    Pay-what-you-want or flat bundles become one tier; tiered bundles use `merge_tiered_games`; pick-and-mix uses `pick_quota` tiers like `write_deku_offer`'s `price_per_item` branch.
  - Before writing a list it runs `existing_list_match(lists_root, "fanatical", slug, games, crawler_name="fanatical")` and, on a hit, `backfill_existing_lists(...)`, so lists previously created from isthereanydeal/dekudeals get cross-checked instead of duplicated (and the reverse works too once this source's lists exist).
- `migrations.py`: empty `METADATA_MIGRATIONS` / `SOURCE_MIGRATIONS` lists (v1 only), registered the same way the other sources are.
- `__init__.py` re-exporting the public names, as in the other packages.

Wiring:

- `sources/names.py`: add `SourceName.FANATICAL = "fanatical"`.
- `schema.py`: `generate_/render_/write_fanatical_schema`, and `schemas/fanatical-archive.schema.json` generated via `game-collections schema` (never hand-edited).
- `cli.py`: `scrape fanatical` with `--url` (repeatable), `--lists-root`, `--archive-root`, `--resolution-map` (default `config/fanatical-store-ids.yml`), `--refresh/--no-cache`, and the existing `--git` session via `git_ops.finish_scrape_git_session(session, ["lists", "archives/fanatical", str(resolution_map)], message)` using `_git_commit_message`, mirroring `scrape_dekudeals_command`; also add the schema option to `schema_command`.
- `migrations/schema_versions.py` (or wherever the per-source registry lives): register the Fanatical source so `migrate --type metadata|source` knows it.
- Also check that `config/isthereanydeal-providers.yml` / `dekudeals-providers.yml` need no changes (they already map to the `fanatical` slug).
- Docs: new "Fanatical" section in `src/game_collections/sources/README.md` (JSON endpoint, tiers vs pick-and-mix, resolver, dedup), the `scrape` verb list in the root `README.md`, and the one-line CLI/architecture mentions in `CLAUDE.md` (= `AGENTS.md` symlink).
  Optional weekly GitHub Action is **not** added (only Humble and ITAD have one); can follow later.
- Repo process: save the plan under `ai/plans/048_<slug>.md` and the prompt in `ai/query.md` as the hooks do, and commit per the active `commit-with-lplp-style` skill (explicit paths, message via `ai/git/pending-commit.md`).
  Python style per `AGENTS.md`: full annotations, early returns, `# end …` after every block, no `_`-prefixed new modules, keep existing comments.

## Tests (offline, `tests/`)

- `tests/test_fanatical_parser.py`: fixtures trimmed from the live list JSON (the CoppaFeel item, a 3-tier multi-tier item, one pick-and-mix item, one books-only item) under `tests/fixtures/fanatical/`; asserts tiers, prices, dates, and strict failure on unknown fields.
- `tests/test_fanatical_resolver.py`: `steamId` fast path, title-search fallback with a fake search, unresolved marker, books/comics ids.
- `tests/test_fanatical_crawler.py`: fake `fetch`, explicit `--url` validation, caching/resume, dedup against an existing `lists/fanatical/bundle/...` file, written list and archive content (pattern from `tests/test_dekudeals_crawler.py`).
- `tests/test_schema.py` drift check passes after regenerating the schema.

## Verification

1. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests -q -k "fanatical or schema or cli"`, then the full suite.
2. `uv run game-collections schema` and confirm only the new `schemas/fanatical-archive.schema.json` plus intended schema changes appear.
3. Live: `uv run game-collections scrape fanatical --url https://www.fanatical.com/en/bundle/coppafeel-charity-bundle` writes `archives/fanatical/bundle/coppafeel-charity-bundle/` and a `lists/fanatical/bundle/2026-…_coppafeel-charity-bundle.yml` with 10 games (Haste … Completely Stretchy) and Steam IDs (Critter Café resolved or unresolved-marked), then `uv run game-collections validate`.
4. Live: `uv run game-collections scrape fanatical` over the full list (about 63 items): check that it resumes from the archive on a second run, that tiered bundles and a pick-and-mix show the right tiers / `pick_quota`, and that existing ITAD/Deku-created Fanatical lists are backfilled rather than duplicated.
5. Do not run `sync steam --apply` (not part of this change).

## Deviations found while implementing

- `pick-and-mix` items *do* carry `bundle_tiers` (the whole pick pool on the first tier, `products: null` on the rest, `displayTotal` = pick count), so Build-Your-Own bundles get real `pick N` tiers with a `pick_quota` after all; `bundle_covers` is not used.
- `steamId` is an int, `""` or `null`; only an int is trusted, the other two go through the Steam title search.
- The shared `sources.common.existing_list_match` treated the provider's own `bundle/` directory as a fuzzy candidate and, once a list written by the same crawler lived in it, as "already confirmed" for every later slug; it now ignores a provider's top-level type directories (regression test in `tests/test_sources_common.py`).
- Its substring match also hits older editions (`all-stars-bundle-2`, `fall-bundle-2023`), so the Fanatical writer only trusts a match named exactly after the slug (`crawler.is_same_bundle`).
- `software` products are only listed when they resolved to a Steam id (e-learning courses and asset packs are not on Steam).
