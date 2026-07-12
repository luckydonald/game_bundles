# Add DailyIndieGame as a scraper source

## Context

Add `https://www.dailyindiegame.com/site_content_bundles.html` as a new scraped source, alongside Humble Bundle, following the pipeline shape and "adding a new source" guide already written in `src/game_collections/sources/README.md`. Live-site investigation (via a real browser tab, since plain `httpx`/`curl` get a Cloudflare JS-challenge 403 — confirmed with `curl` returning a "Just a moment..." challenge page) found the site's actual structure differs from Humble in three important ways that change the implementation shape:

1. **Cloudflare bot protection**: the whole site sits behind a Cloudflare managed challenge. `HumbleHttpClient` (plain `httpx`) cannot reach it. User chose **Playwright** (headless Chromium) for this source's HTTP layer instead.
2. **No resolver needed**: every game on a DailyIndieGame (DIG) bundle page links directly to `https://store.steampowered.com/app/<id>` — the Steam app ID is already given, no title search/matching/resolution-map/`unresolved:*` machinery like Humble's `StorefrontResolver` is required. This source only ever produces `steam:<id>` IDs.
3. **No structured dates**: there's no embedded JSON or `<time>`/meta date anywhere. The only signal is a live countdown string next to the price block, e.g. `"Bundle ends in 20 days : 03 : 09 : 13"`. The parser computes an approximate end timestamp as `crawled + parsed duration`, mirroring how `HumbleDates.crawled` anchors Humble's own observed-time model.

### Page structures observed

- **Index** (`site_content_bundles.html`): one table section "STEAM GAME BUNDLES — STEAM game bundles currently available for sale" containing thumbnail `<img>`s wrapped in `<a href="site_weeklybundle_<N>.html">` links — this is the discovery index, equivalent to Humble's `BUNDLES_URL`. Observed a run of consecutive recent numbers (e.g. 2351 down to 2330) plus a handful of much older stragglers mixed into the same list (2135, 1230, 2, 1) — the crawler must isolate per-offer parse/fetch failures (mirror `HumbleCrawlReport`'s `errors` tuple) rather than aborting the whole crawl if one of those turns out stale/unparseable.
- **Bundle page** (`site_weeklybundle_<N>.html`): a plain HTML table layout (no CSS classes). Bundle title lives in a small table as free text, e.g. `"DIG Bundle 2351 - ADULT"` (the `- ADULT` suffix appears for 18+ content bundles; no filtering needed — archive as-is, same as Humble does no genre filtering). A sentence gives the summary: `"9 awesome STEAM games , worth a total of $105.91. Grab them now for only $0.99 and save 100% ($104.92)"` — parse game count, total value, bundle price, and savings from this via regex. It's always **one flat price tier** (not Humble Choice's cumulative tiers) — get all N games for one price. Each game is one `<td>` whose first text node is the title, followed by a `view on STEAM` link (`href="https://store.steampowered.com/app/<id>"`) and a second link to `site_gamelisting_<id>.html`.
- **Per-game page** (`site_gamelisting_<id>.html`) — followed per user's choice for richer metadata: gives the game's own price/region line (`"$7.99 ( $7.99 ) You save: $0.00 (0%)Region: WORLDWIDE"`), a description paragraph, and a cover image at `dig3-images-steam/<id>.jpg` (relative to site root).

## New source package: `src/game_collections/sources/dailyindiegame/`

Mirror the Humble package shape (`models.py`, `parser.py`, `crawler.py`, `__init__.py`), but flatter since there's no resolver stage:

- **`models.py`** — `DigItem(StrictModel)`: `title`, `ids: list[str]` (always `["steam:<id>"]`), `cover_art_url: HttpUrl | None`, `description: str = ""`, `individual_price: HumblePrice`-shaped or a simpler `DigPrice` (raw/value/currency) reused/shared if convenient. `DigArchive(StrictModel)`: `schema_version: Literal[1]`, `machine_name` (the bundle number as a string, e.g. `"2351"`), `url`, `name` (e.g. `"DIG Bundle 2351 - ADULT"`), `is_adult: bool`, `dates` (`crawled: datetime`, `end: datetime | None` computed from the countdown), `game_count: int`, `total_value` / `bundle_price` / `savings` price fields, `items: list[DigItem]` (`min_length=1`). Base everything on `game_collections.models.StrictModel`/`NonEmptyString` like Humble's models do.
- **`parser.py`** — `parse_bundle_index_page(html: str) -> list[str]` (extract `site_weeklybundle_<N>.html` numbers via the anchor/img gallery), `parse_bundle_page(html: str, crawled: datetime) -> tuple[DigArchive, dict]` (extract name/adult-flag/summary-sentence/per-game td cells; compute `end` from the `"ends in D days : HH : MM : SS"` regex relative to `crawled`), `parse_game_listing_page(html: str) -> dict` (price/region/description/cover image for one game, used to enrich each `DigItem` after the bundle page identifies its games). Raise a `DigParseError` (mirror `HumbleParseError`) on unexpected structure.
- **`crawler.py`** — `DigBrowserClient`: thin Playwright wrapper exposing `fetch(url) -> str` (launch headless Chromium once per crawl run, navigate, wait for the challenge/network to settle, return `page.content()`), with the same bounded-retry/backoff shape as `HumbleHttpClient.fetch`. `crawl_dig_offers(fetch: Callable[[str], str], urls: Iterable[str] | None = None, crawled: datetime | None = None) -> DigCrawlReport` — takes an **injectable `fetch` callable** exactly like `crawl_humble_offers(fetch, ...)` does, so unit tests exercise the parsing/orchestration logic with a fake `fetch` and never launch a real browser; only the CLI wires the real `DigBrowserClient.fetch` in. Discovers offers via the index page (or explicit `--url` bundle pages), fetches each bundle page, then fetches each game's listing page to enrich it, isolating per-offer errors into `DigCrawlReport.errors` like Humble's report. `write_dig_offer(...)` atomically writes `archives/dailyindiegame/bundle/<N>/{metadata.json,source.json}` and one `lists/dailyindiegame/bundle/<N>.yml`.

**Reuse, don't duplicate**: `_atomic_write`, `_json`, and `_game_list_yaml` in `sources/humblebundle/crawler.py` are already source-agnostic file-writing helpers. Extract them into a new `src/game_collections/sources/common.py` (or `_atomic_write.py`) and import from both `humblebundle/crawler.py` and `dailyindiegame/crawler.py`, rather than copy-pasting. Update `sources/README.md`'s "Adding a new source" guide's file-writing bullet to point at the shared module once extracted.

## Wiring

- **CLI** (`src/game_collections/cli.py`): add `@scrape_app.command("dailyindiegame")` next to `scrape_humblebundle_command`, with `--url` (repeatable), `--lists-root`, `--archive-root`. No `--non-interactive`/resolution-map flags — there's no resolution ambiguity to suppress, so don't add flags that would be meaningless.
- **Schema**: add `write_dailyindiegame_schema(...)` in `src/game_collections/schema.py`, wire into the `schema` command next to `write_humblebundle_schema`, generating `schemas/dailyindiegame-archive.schema.json`.
- **Dependency**: add `playwright` to `pyproject.toml` `[project]` dependencies. Document the one-time browser install (`uv run playwright install --with-deps chromium`) in `CLAUDE.md`'s Commands section and the root `README.md` Setup section.
- **Tests**: `tests/test_dailyindiegame_parser.py` and `tests/test_dailyindiegame_crawler.py`, mirroring the Humble test files — HTML fixtures under `tests/fixtures/`, fake `fetch` callables, no real network/browser access. Add `tests/test_schema.py` coverage for the new schema file (drift check, matching the existing pattern).
- **Docs**: add a "Daily Indie Game" section to `src/game_collections/sources/README.md` (mirroring the Humble section — pipeline pieces, the Cloudflare/Playwright note, the "no resolver needed" note), extend root `README.md`'s CLI command list, add a `lists/README.md` note about `dailyindiegame/bundle/<N>.yml` generated lists, and update `CLAUDE.md`'s architecture bullet for `sources/` to mention both source packages plus the new shared `common.py` helper module.

## Scheduled scraping

Add `.github/workflows/weekly-dailyindiegame-scrape.yml`, copied from `weekly-humblebundle-scrape.yml` with:
- CLI verb swapped to `scrape dailyindiegame`.
- An added `uv run playwright install --with-deps chromium` step before the scrape step.
- Rolling branch renamed to `automation/dailyindiegame-weekly-scrape`.
- Change-detection/`git add` paths swapped to `lists/dailyindiegame/` + `archives/dailyindiegame/` (no resolution-map path, since none exists for this source).
- Same rebase-onto-main / abort-and-continue-on-conflict / never-fail-on-scrape-exit-code behavior as the Humble workflow.

## Verification

- `uv run pytest tests/test_dailyindiegame_parser.py tests/test_dailyindiegame_crawler.py -q` against fixture HTML (captured from the real site during this investigation) — confirms bundle/index/game-listing parsing without needing a live browser in CI-less local runs.
- `uv run game-collections schema` — confirms `dailyindiegame-archive.schema.json` generates without drift.
- Manually run `uv run game-collections scrape dailyindiegame --url https://www.dailyindiegame.com/site_weeklybundle_2351.html` locally (after `playwright install --with-deps chromium`) and inspect the written `lists/dailyindiegame/bundle/2351.yml` + `archives/dailyindiegame/bundle/2351/*.json` for correctness against what was observed live (9 games, all `steam:<id>`, name `"DIG Bundle 2351 - ADULT"`).
- `uv run game-collections validate` — confirms the generated list passes the existing Pydantic list contract.
