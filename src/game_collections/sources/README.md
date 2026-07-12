# Sources

A "source" scrapes a public storefront/bundle page into launcher-neutral `lists/` entries plus a normalized `archives/` record, as opposed to `launchers/`, which synchronizes already-owned lists into a launcher library. Humble Bundle is the only implemented source.

## Humble Bundle (`humblebundle/`)

Backs `game-collections scrape humblebundle`. Pipeline:

- `crawler.py` — `HumbleHttpClient` (small retrying `httpx` client for public HTML) and `crawl_humble_offers(...)`, which either fetches the explicit `--url` list or discovers the current Choice month (`CHOICE_URL`) and every active Games bundle from the bundle index (`BUNDLES_URL`). `write_humble_offer(...)` then atomically writes (temp file + `fsync` + rename, see `_atomic_write`) the normalized `archives/humblebundle/.../metadata.json` + `source.json`, and one `lists/humblebundle/...` YAML per advertised cumulative tier (`choice/YYYY-MM.yml`, or `bundle/<key>/<n>-item-bundle.yml` with `entire-<n>-item-bundle.yml` for tier 0).
- `parser.py` — extracts the embedded JSON payload from Humble's page HTML (`parse_choice_page`, `parse_bundle_page`, `parse_bundle_index`) into a `HumbleArchive` plus the raw source payload; converts descriptions to Markdown.
- `resolver.py` — `StorefrontResolver` matches each Humble product title against real storefronts (Steam, GOG, Epic, Ubisoft, Humble Store) via `STORE_SEARCH_URLS`. Unique exact matches resolve automatically; ambiguous matches prompt for a candidate or canonical URL/ID (or record `unresolved:source:humblebundle:<machine-name>` under `--non-interactive`). Reviewed decisions persist in `config/humblebundle-store-ids.yml` (a `HumbleResolutionMap`) so re-running the scraper doesn't re-prompt for already-resolved titles.
- `models.py` — `HumbleArchive`/`HumbleItem`/`HumbleResolution`: the strict Pydantic shape of the normalized archive, validated against `schemas/humblebundle-archive.schema.json`.

`scripts/backfill_humble_choice.py` is a standalone script (not part of this package) that reuses these same crawler/resolver internals to backfill historical Choice months from a third-party mirror, since Humble's own site only exposes the current month to guests.

### Scheduled scraping

`.github/workflows/weekly-humblebundle-scrape.yml` runs `game-collections scrape humblebundle --non-interactive` every Monday (plus manual `workflow_dispatch`) and opens/updates a pull request with any new offers. It reuses a single rolling branch (`automation/humblebundle-weekly-scrape`) across weeks — rebasing it onto `main` if it survived from last week's still-open PR, or recreating it from `main` if last week's PR was merged/closed — and never fails the job on unresolved storefront IDs, since those are an expected, committable state for later manual `game-collections complete` follow-up.

## Adding a new source (e.g. another bundle shop)

Use `humblebundle/` as the template. A new source is its own package `src/game_collections/sources/<source>/` with the same four pieces, wired into the CLI the same way:

1. **Models** (`<source>/models.py`) — a strict Pydantic archive shape for the offer, analogous to `HumbleArchive`/`HumbleTier`/`HumbleItem`. Base new models on `game_collections.models.StrictModel`/`NonEmptyString` so unknown fields and bad types fail loudly rather than silently rewriting bad data. Add a `schema_version: Literal[1] = Field(alias="schema", ...)` field so the archive is versioned like Humble's.
2. **Parser** (`<source>/parser.py`) — turns the shop's raw page (embedded JSON, HTML, or an API response) into `(archive, source_payload)`, where `source_payload` is the relevant raw data worth preserving verbatim. Raise a source-specific parse error (mirror `HumbleParseError`) on anything unexpected instead of guessing.
3. **Resolver** (`<source>/resolver.py`) — maps each product title to a qualified storefront ID (`steam:<appid>`, `gog:<id>`, etc). Reuse the existing storefront search machinery in `game_collections.search`/`StorefrontResolver`-style matching rather than reinventing per-store search — only the *shop's own* product listing is source-specific; matching a title against Steam/GOG/Epic is not. Persist reviewed decisions to a `config/<source>-store-ids.yml`-style resolution map (mirror `HumbleResolutionMap`/`render_resolution_map`) so re-crawling doesn't re-prompt for already-resolved titles, and record `unresolved:source:<source>:<key>` when nothing matches under `--non-interactive`.
4. **Crawler** (`<source>/crawler.py`) — an HTTP client (mirror `HumbleHttpClient`'s bounded-retry `httpx` wrapper) plus a `crawl_*_offers(...)` function that discovers or fetches explicit offers and returns a report of successes and isolated per-offer errors (mirror `HumbleCrawlReport`) so one bad page doesn't abort the whole run. A `write_*_offer(...)` function then atomically writes (reuse the `_atomic_write`/`_json`/`_game_list_yaml` pattern — temp file, `fsync`, rename) the normalized `archives/<source>/.../metadata.json` + `source.json`, and one `lists/<source>/...` YAML per purchasable tier/offer, each referencing its offer URL and archive files via `Reference`.

Then:

- **CLI**: add a new `@scrape_app.command("<source>")` in `src/game_collections/cli.py` next to `scrape_humblebundle_command`, following the same `--url`/`--lists-root`/`--archive-root`/`--resolution-map`/`--non-interactive` option shape.
- **Schema**: add a `write_<source>_schema(...)` in `src/game_collections/schema.py` and wire it into the `schema` command so `schemas/<source>-archive.schema.json` gets generated and drift-checked the same way `humblebundle-archive.schema.json` is (see `tests/test_schema.py`).
- **Tests**: mirror `tests/test_humblebundle_crawler.py`, `test_humblebundle_parser.py`, and `test_humblebundle_resolver.py` — fixtures under `tests/fixtures/` for sample pages, no live network access.
- **Docs**: document the new verb in the root `README.md` (see its "Humble Bundle imports" section) and add a pipeline section to this file.
- **Scheduling** (optional): copy `.github/workflows/weekly-humblebundle-scrape.yml` for a new `.github/workflows/weekly-<source>-scrape.yml`, swapping the CLI verb, rolling branch name, and `lists/`/`archives/`/config paths touched by the change-detection and `git add` steps.

Keep all of this source-specific parsing/matching out of `game_collections.models`/`lists.py` — those stay source- and launcher-neutral, and only ever see the final `GameList`/`Game`/`Reference` shape.
