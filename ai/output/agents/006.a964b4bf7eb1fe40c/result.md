I have everything needed for a complete research report. Here is the full findings summary.

## Summary of findings

### 1. The "unresolved solver" — mechanism and dispatch

There is **no per-source dispatch table/registry** for `unresolved:source:<source>:<key>` markers. Two distinct id-marker families exist, both defined in `src/game_collections/search.py`:

- `unresolved:store:<provider>:<slugified-title>` — written by `complete_game_list` itself (line 172) when a title search against a given storefront provider fails.
- `unresolved:source:<source>:<key>` — written by each *source's own* parser/resolver during scraping (not by `complete`), e.g. `unresolved:source:humblebundle:<machine-name>` (`src/game_collections/sources/humblebundle/resolver.py:241`), `unresolved:source:greenmangaming:<product-id>` (`src/game_collections/sources/greenmangaming/resolver.py:157`), `unresolved:source:isthereanydeal:<bundle-id>:<slug>` (`src/game_collections/sources/isthereanydeal/parser.py:328`).

The "solver" for `unresolved:source:*` today is indirect and generic: `game-collections complete <file> --mode <blank|missing|unresolved|refetch_all> --provider <store>` runs `complete_game_list` (`src/game_collections/search.py:115-185`), which does a **title-based search** against a chosen storefront (`resolve_title`, line 86) — completely independent of which source produced the entry. If that search succeeds, `unresolved:source:*` markers get stripped opportunistically (line 176: `current = [value for value in current if not value.startswith("unresolved:source:")]`), regardless of source. There is no source-name parsing/branching anywhere (confirmed by grep — no `match`/dict keyed by source name that reads the 3rd colon-segment of `unresolved:source:...`). Key signatures:

```python
CompletionMode = Literal["blank", "missing", "unresolved", "refetch_all"]
def selected_providers(values: str | list[str] | None, *, default: str) -> tuple[StoreName, ...]
def completion_mode(value: str) -> CompletionMode
def resolve_title(title: str, providers: tuple[StoreName, ...], resolver: StorefrontResolver, choose: SearchChooser) -> list[str]
def complete_game_list(raw: object, providers: tuple[StoreName, ...], resolver: StorefrontResolver, choose: SearchChooser, mode: CompletionMode = "blank") -> tuple[dict[str, Any], list[str]]
```

Test confirming the strip-on-success behavior: `tests/test_search.py:181` `test_success_removes_source_unresolved_marker` — a Humble-sourced `unresolved:source:humblebundle:portal` gets replaced by `steam:400` purely via title search, with no source-specific logic involved.

The CLI entry point is `complete_command` in `src/game_collections/cli.py:241-292`, flags: `FILE` (positional draft YAML), `--provider/--store/-p` (repeatable/comma-separated, default `steam`), `--mode` (blank/missing/unresolved/refetch_all, default `blank`). It writes back the completed YAML in place and echoes `unresolved: <title>` to stderr, exiting 1 if anything remains unresolved.

**Implication for a new feature**: adding a genuine "isthereanydeal detail-page solver" (fetch `https://isthereanydeal.com/game/<slug>/info/` to find a direct storefront link for entries currently marked `unresolved:source:isthereanydeal:<bundle-id>:<slug>`) would be new functionality — there is no existing per-source unresolved-marker parser/dispatcher to hook into; it would need its own resolver module and probably its own CLI mode or flag, following the `sources/<source>/resolver.py` convention used by Humble/GreenManGaming, or a new solving path added into `complete`/`search.py`.

### 2. isthereanydeal source module (`src/game_collections/sources/isthereanydeal/`)

- `crawler.py` — `ItadHttpClient` (bounded-retry httpx wrapper: `bootstrap()`, `list_page(tab, offset)`, `fetch(url)`); `crawl_itad_offers(fetch, list_page, provider_config, tabs=("live",), shop_names=None, archive_root=None, log=_NO_LOG, on_offer=None)` (`crawler.py:216`); `write_itad_offer(offer, *, lists_root, archive_root, repository_root, log=_NO_LOG)` (`crawler.py:367`) — writes `archives/isthereanydeal/bundle/<id>/{metadata.json,source.json}` and, unless a substring-match against existing `lists/<provider>/...` paths says the bundle's already covered, one `lists/<provider>/bundle/<date>_<slug>/<tier-id>.yml` per cumulative tier.
- `parser.py` — `parse_bootstrap_page`, `parse_list_page`, `parse_bundle_detail_json` (primary; extracts `var page = ["Bundle", {"liveData": {"tiers": [...]}}]`), `parse_bundle_detail_page` (BeautifulSoup DOM fallback), `real_provider_url`/`real_provider_slug`, and the key helper `_resolve_urls(urls, bundle_id, slug)` (`parser.py:307-331`) which is where the `unresolved:source:isthereanydeal:<bundle_id>:<slug>` marker gets appended when no `reviews[].url` resolves to a known `STORE_ROOTS` prefix. Also `GAME_HREF_PATTERN = re.compile(r"^/game/([a-z0-9-]+)/info/$")` (line 204) — this is the DOM anchor pattern already used to discover each game's own ITAD detail-page slug (`https://isthereanydeal.com/game/<slug>/info/`), the natural target URL for a new per-game resolver.
- `models.py` — `ItadArchive`/`ItadTier`/`ItadItem`/`ItadPrice`/`ItadDates` (normalized, resolved shape) and `ItadListSummary`/`ItadPageInfo`/`ItadCounts` (list-API validated shape). `ItadItem.ids: list[NonEmptyString] = Field(min_length=1)` holds either resolved qualified ids or a single `unresolved:source:...` entry (docstring at `models.py:26-32` states this explicitly).
- `provider_config.py` / `shop_config.py` — reviewed lookup tables (`config/isthereanydeal-providers.yml`, `config/isthereanydeal-shops.yml`), used only for slug mapping / corroboration logging, never for resolution.

**Shape of the embedded `var page` JSON** (from `tests/test_isthereanydeal_parser.py:242-293`):
```json
["Bundle", {"liveData": {"tiers": [
  {"price": [800, "EUR"], "addon": false, "note": "Bronze", "games": [
    {"slug": "laika", "title": "Laika",
     "reviews": [{"source": "Steam", "url": "https://store.steampowered.com/app/1796220/"}],
     "keys": [61]}
  ]}
]}}]
```
Each game's storefront id is read from `reviews[].url` via `game_collections.sources.storefronts.parse_store_identity`, not from an `appid` field directly — no fixture in the repo shows a literal `detail.appid` key.

Because ITAD is a bundle *aggregator*, tier-list YAMLs live under `lists/<provider>/...` (not `lists/isthereanydeal/`), e.g. `lists/humblebundle/bundle/2015-06-15_twitche3/tier-1.yml`. An example with unresolved entries: `lists/humblebundle/bundle/2015-06-15_twitche3/tier-1.yml` contains entries like:
```yaml
- name: WildStar
  ids:
  - unresolved:source:isthereanydeal:2126:wildstar
```
There are currently **4,548 list files** containing at least one `unresolved:source:isthereanydeal:*` marker (roughly 15,145 total occurrences via grep -c sum, though that count includes duplicate lines per file) — a sizable backlog a solver feature would target.

### 3. Analogous per-source resolver conventions (Humble / GreenManGaming)

`src/game_collections/sources/humblebundle/resolver.py` is the template:
- `StorefrontResolver.__init__(self, fetch: Fetcher, choose: CandidateChooser)`
- `resolve_item(self, item: HumbleItem, mapping: HumbleResolutionMap) -> list[str]` (lines 208-245) — checks a durable `HumbleResolutionMap` cache first, else searches each candidate store, falls back to `f"unresolved:source:humblebundle:{item.machine_name}"` if nothing resolves (line 241).
- `resolve_archive(self, archive, mapping, log=_NO_LOG) -> HumbleArchive` (lines 247-299) — dedupes distinct games, resolves each once, applies results back across all cumulative tiers.
- Persisted resolution map: `config/humblebundle-store-ids.yml`, rendered via `render_resolution_map(mapping)` (line 180).

GreenManGaming's `resolver.py` mirrors this exactly (re-exports `StorefrontResolver` machinery from Humble's module rather than reimplementing), persisting to `config/greenmangaming-store-ids.yml`.

There is **no existing per-game-detail-page fetch/resolve module** anywhere in the repo (confirmed: no other file references `/game/<slug>/info/` besides the parser's regex and tests) — a new ITAD per-game-detail resolver would be a genuinely new addition, not a variant of an existing one.

### 4. Schema generation (`schemas/*.json`, `tests/test_schema.py`)

- `src/game_collections/schema.py` already has isthereanydeal support: `generate_isthereanydeal_schema()` / `render_isthereanydeal_schema()` / `write_isthereanydeal_schema(path)` (lines 106-127), generating `ItadArchive`'s JSON Schema straight from the Pydantic model — same pattern as `write_humblebundle_schema`/`write_dailyindiegame_schema`/`write_greenmangaming_schema`.
- `tests/test_schema.py:41-44` — `test_committed_isthereanydeal_schema_matches_pydantic_models` compares `schemas/isthereanydeal-archive.schema.json` byte-for-byte against `render_isthereanydeal_schema()`; drift fails CI.
- **No new schema file is needed** unless the new feature changes `ItadArchive`/`ItadItem`/`ItadTier` shape (e.g. adding a new field to record per-game-detail resolution provenance) — in that case, bump `schema_version`/regenerate the existing `isthereanydeal-archive.schema.json` rather than create a new schema file; there's no established convention for a second schema per source.

### 5. Existing tests/fixtures for isthereanydeal

- `tests/test_isthereanydeal_parser.py` — inline HTML/dict fixtures built as small Python helper functions (`_detail_json_html`, `_game_block`, `_tier_block`, `_list_entry`, `BOOTSTRAP_HTML`), not separate fixture files — this repo's convention is programmatically-constructed fixture strings inline in the test module, not `tests/fixtures/*.html` files (the `tests/fixtures/` directory currently contains no isthereanydeal-specific files at all — it was empty in this search, meaning ITAD tests don't use the fixtures dir).
- `tests/test_isthereanydeal_crawler.py` — crawler-level tests injecting fake `fetch`/`list_page` callables (no live network).
- **No dedicated `unresolved solver` tests exist** — `tests/test_search.py` only covers the generic store-title-search completion flow (`test_complete_game_list_*`, `test_missing_does_not_retry_a_store_failure_but_unresolved_does`, `test_success_removes_source_unresolved_marker`); nothing tests a source-specific detail-page resolution for `unresolved:source:isthereanydeal:*` because that machinery doesn't exist yet.

### Architecture takeaway for the planned feature

Building an "isthereanydeal unresolved solver" that fetches each game's own ITAD detail page (`/game/<slug>/info/`) to find a real storefront link is new work with no existing dispatch point to hook into. It should likely:
1. Live in a new `src/game_collections/sources/isthereanydeal/resolver.py` (or similarly named module) mirroring Humble's `StorefrontResolver` shape but keyed by ITAD game slug instead of title search.
2. Need a new CLI surface (either a new `complete`-adjacent verb, or a new `--mode`/flag on `scrape isthereanydeal`, or a standalone command) since `complete_game_list`'s current dispatch is purely storefront-title-search-based and has zero awareness of `unresolved:source:<source>:` internals beyond stripping them on unrelated success.
3. Should follow the `sources/README.md` "Adding a new source" checklist conventions (models/parser/resolver/crawler split, `# end` comment style, strict Pydantic `StrictModel`, atomic writes via `sources/common.py`) even though it's augmenting an existing source rather than adding a new one.