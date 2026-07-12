# Verbose progress, incremental writes, and resume-from-disk for both scrapers

## Context

Both `game-collections scrape humblebundle` and `scrape dailyindiegame` currently run silently: `crawl_humble_offers()`/`crawl_dig_offers()` fetch and fully process **every** target (page fetch, per-game enrichment/resolution) into an in-memory list, and only after the *entire* crawl finishes does the CLI loop over `report.offers` calling `write_*_offer()` and printing anything. A crash, interrupt, or Ctrl-C mid-crawl loses all progress, there's no feedback while it runs, and every re-run refetches everything from scratch — expensive for DIG in particular, where every fetch is a full headed-browser page load (~10-15s each) and bundles roll off/on gradually so most of a re-run's targets were already scraped last time.

This plan adds, to both scrapers:
1. **Verbose progress logging** — "Bundle x/y", "Game x/y" style messages as it works, not silence until the end.
2. **Write-as-you-go** — each bundle/offer is written to disk immediately once it's fully processed, not batched until the whole crawl finishes.
3. **Resume from disk** — before doing expensive work for a target, check whether valid on-disk output (matching the current schema) already exists and reuse it instead of re-fetching, unless the schema changed or the user asks for a full refresh.

## Design

### Shared cache-read helper (`sources/common.py`)

Add `load_cached_archive(model_cls, metadata_path, source_path)` alongside the existing `atomic_write`/`dump_json`/`render_game_list_yaml`. Returns `(archive, source_dict)` on success, or `None` if either file is missing, JSON is invalid, or `model_cls.model_validate(...)` raises (covers the `schema_version: Literal[1]` mismatch case — a future schema bump makes old cache entries validate-fail and fall through to a real re-fetch automatically, no separate version-comparison code needed). Both source packages already dump `archive.model_dump(by_alias=True, mode="json")` for `metadata.json` and the raw dict for `source.json`, so this is a straightforward round-trip.

### DailyIndieGame (`sources/dailyindiegame/crawler.py`)

Bundle numbers are known **before any fetch** (from `parse_bundle_index_page` or explicit `--url`), so the cache check can skip the bundle-page fetch *and* every per-game listing-page fetch entirely for cached bundles — this is the main win given bundles don't change once published (only their countdown ticks down).

- `crawl_dig_offers(fetch, urls=None, crawled=None, archive_root: Path | None = None, log: Callable[[str], None] = lambda _msg: None, on_offer: Callable[[CrawledDigOffer], None] | None = None) -> DigCrawlReport`
  - For each target (`log(f"Bundle {i}/{n}: {number}")`): if `archive_root` given, try `load_cached_archive(DigArchive, archive_root/"dailyindiegame/bundle"/number/"metadata.json", .../"source.json")`. On hit, `log(f"Bundle {i}/{n}: {number} (cached)")`, use it directly — **no bundle-page or game-listing fetches at all**. On miss/invalidated, fetch+parse the bundle page, then enrich each item with `log(f"Bundle {i}/{n} Game {j}/{m}: {title}")` per game-listing fetch (replacing the current silent list comprehension with an explicit loop).
  - After each offer (cached or freshly fetched) is fully assembled, call `on_offer(offer)` immediately — this is how writing happens as-you-go without turning the function into a generator (keeps the existing `DigCrawlReport` return shape and all current tests working unchanged when `archive_root`/`log`/`on_offer` are omitted).
- `scrape_dailyindiegame_command` (cli.py) passes `archive_root=archive_root`, `log=typer.echo`, and `on_offer=lambda offer: write_dig_offer(offer, lists_root, archive_root, repository_root)` so each bundle's files land on disk the moment that bundle is done, not after the whole run. Add a `--refresh` flag that passes `archive_root=None` instead, forcing a full re-fetch of everything (explicit escape hatch for correcting a bad scrape).

### Humble Bundle (`sources/humblebundle/crawler.py` + `resolver.py`)

The offer's cache key (`_offer_key`) depends on parsed fields, so the page itself must still be fetched to learn the key — but the *expensive* part (per-game storefront search resolution in `StorefrontResolver.resolve_archive`) can be skipped once the key is known and a valid cache hit is found.

- `crawl_humble_offers(fetch, resolver, mapping, urls=None, crawled=None, archive_root: Path | None = None, log=..., on_offer=None) -> HumbleCrawlReport`: `log(f"Offer {i}/{n}: {url}")` per target; after parsing (before calling `resolver.resolve_archive`), compute the key and try `load_cached_archive(HumbleArchive, ...)`. On hit: `log("... (cached, skipping resolution)")`, use the cached (already-resolved) archive directly — skip `resolve_archive` and its per-item storefront searches entirely. On miss: proceed as today. Call `on_offer(offer)` right after each offer is ready.
- `StorefrontResolver.resolve_archive` gains an optional `log: Callable[[str], None] = lambda _msg: None` param, calling `log(f"Game {j}/{m}: {item.title}")` for each distinct game it resolves — this is the only place that naturally knows the per-game count during resolution.
- `scrape_humblebundle_command` (cli.py): pass `archive_root`, `log=typer.echo`, `on_offer=lambda offer: (write_humble_offer(offer, ...), write_resolution_map(resolution_map, mapping))` — both the offer's files *and* the resolution-map's incremental progress get flushed after every offer, not just once at the very end. Add the same `--refresh` flag (passes `archive_root=None`).

### Why this counts as "resume"

There's no explicit `--resume` flag or state file — re-running the same command *is* the resume mechanism, since already-written, schema-valid output is preferred over re-fetching by default. This matches the existing idempotent-writer guarantee (`test_writer_is_idempotent` et al.) and needs no new persistent state beyond what's already written.

## Tests

- `tests/test_dailyindiegame_crawler.py`: new tests asserting (a) a pre-seeded `archive_root` with valid cached `metadata.json`/`source.json` for one bundle number causes `crawl_dig_offers` to never call `fetch` for that bundle's page or any of its game-listing URLs (use a `fetch` that raises if called with those URLs); (b) a cache entry with a mismatched `schema` value is ignored and falls through to a real fetch; (c) `log` receives the expected `"Bundle x/y"`/`"Game x/y"` messages in order; (d) `on_offer` is invoked once per offer, in target order.
- `tests/test_humblebundle_crawler.py`: mirror the above for the resolution-skip case — assert storefront search URLs are never fetched for a cached offer, while the offer's own page URL still is.
- `tests/test_schema.py`/existing writer tests: unaffected, but confirm `load_cached_archive` round-trips both `DigArchive` and `HumbleArchive` via a small direct unit test in `sources/common.py`'s own coverage (add a `tests/test_sources_common.py` if none fits better) — write via `dump_json`, read back via `load_cached_archive`, assert equality; also assert `None` is returned for missing files and for a deliberately corrupted `schema` field.

## Verification

- `uv run pytest -q` — full suite green, including new cache/log/callback tests.
- Manually re-run `uv run game-collections scrape dailyindiegame --url <a bundle already scraped in this session>` and confirm via the printed log lines that it reports "(cached)" and does **not** open new browser page loads for that bundle or its games (fast, no visible navigation).
- Manually run against a fresh bundle URL and confirm progress lines print incrementally (not all at once at the end) and that `lists/`/`archives/` files for that bundle exist immediately after its log line, before the whole command finishes (check file mtimes/existence mid-run if scraping more than one bundle).
- `uv run game-collections scrape dailyindiegame --refresh --url <cached bundle>` and confirm it re-fetches instead of using the cache.
