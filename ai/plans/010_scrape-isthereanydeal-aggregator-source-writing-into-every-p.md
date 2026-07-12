# `scrape isthereanydeal` — aggregator source writing into every provider's own lists

## Context

isthereanydeal.com (ITAD) runs a bundle aggregator at `/bundles/` that indexes bundles from many
selling platforms (Humble Bundle, Fanatical, GreenManGaming, IndieGala, AllYouPlay, ...). Its own
per-bundle detail page (`/bundles/<id>/`) is server-rendered and — confirmed by fetching a live
example — embeds tiers, prices, and (for most bundles) direct `store.steampowered.com/app/<id>`
links per game, with no title-matching/resolver step needed, unlike our Humble/GreenManGaming
sources. The user wants a new source that crawls ITAD's discovery API/pages and, per bundle,
writes into the *correct existing provider's* `lists/<provider>/...` directory (creating new
provider directories for platforms we don't have a dedicated scraper for yet, e.g. Fanatical,
IndieGala, AllYouPlay), while keeping the raw crawl under `archives/isthereanydeal/...`.

Decisions already confirmed with the user (via AskUserQuestion):
- Write `lists/` for **every** provider ITAD surfaces, not just humblebundle/greenmangaming —
  new provider directories (fanatical/, indiegala/, allyouplay/, etc.) get created too, sourced
  entirely from ITAD's own detail-page data (no per-provider scraper needed for those).
- Where a bundle is **also** covered by an existing dedicated scraper (Humble, GreenManGaming),
  derive the same slug ITAD gives us and **skip** writing it if a matching list already exists on
  disk — avoid two pipelines describing the same real bundle. Best-effort match, not exact-path
  match (see Dedup below).

## Research findings (already verified against the live site — don't re-derive)

### Discovery API — paginated, needs a bootstrap token
- `POST https://isthereanydeal.com/bundles/api/list/?tab={live|expired|pending}` with JSON body
  `{"offset": N, "sort": null, "filter": null}` (N steps by 30) returns
  `{"done": bool, "data": [ ...bundle summaries... ]}`. `done: true` + empty `data` means no more
  pages for that tab.
- **Requires two things from a prior plain GET of `https://isthereanydeal.com/bundles/`:**
  1. The `sess2` cookie Set-Cookie'd on that GET (anonymous session cookie, no login involved).
  2. A `itad-sessiontoken` request header whose value is **the same string** as the `sess2`
     cookie — found embedded in the bootstrap page's inline `<script>` as
     `"token":"<value>"` inside a JSON-like blob. This is a plain anonymous CSRF-style token
     issued to every visitor (verified: matches an anonymous, non-logged-in `user.isLoggedIn:
     false` session) — not any personal credential. Any request missing the header, or an
     `Accept` header that isn't `application/json`, gets a `400`/falls back to the HTML page.
  3. Concretely: `GET /bundles/` → parse cookie jar + regex the `"token":"..."` value out of the
     HTML → reuse both for every subsequent `POST /bundles/api/list/...` and per-bundle detail GET
     in the same crawl run. Bounded-retry `httpx.Client` with a cookie jar (mirror
     `HumbleHttpClient` in `src/game_collections/sources/humblebundle/crawler.py`), refreshing the
     bootstrap once if a call unexpectedly 400s.
- One list-summary entry (verbatim shape, **store this whole object as-is** per the user's ask):
  ```json
  {
    "id": 16316, "title": "Metroidvania Madness",
    "page": {"id": 4, "name": "GreenManGaming", "shopId": 36},
    "url": "https://greenmangaming.sjv.io/c/.../?u=https%3A%2F%2Fwww.greenmangamingbundles.com%2Fbundles%2Fmetroidvania-madness%2F",
    "isMature": false, "isPending": false, "start": 1783715387, "expiry": 1785556800,
    "counts": {"games": 6, "media": 0, "waitlist": 0, "collection": 0, "comments": 0}, "byob": false
  }
  ```
  `page.name` is the aggregator's display name for the origin platform — the mapping to our
  `lists/<provider-slug>/` naming (`"Humble Bundle"→humblebundle`, `"Fanatical"→fanatical`,
  `"GreenManGaming"→greenmangaming`, `"IndieGala"→indiegala`, `"AllYouPlay"→allyouplay`) should
  live in a small reviewable `config/isthereanydeal-providers.yml` (mirroring
  `config/humblebundle-store-ids.yml`'s reviewed-mapping pattern) keyed by ITAD's own `page.id`/
  `page.name`/`shopId`, with a slugify fallback + a logged warning for any unseen provider so new
  platforms don't silently get a guessed slug forever. `url` is an affiliate redirect; the real
  provider URL is the decoded `u=` query parameter — its last path segment is the **same slug**
  the provider's own site (and our GMG scraper) uses (`metroidvania-madness`,
  `lego-at-the-movies`, humble's `squad-goals`, etc.) — this is the key to naming/dedup.

### Bundle detail page — SSR HTML, no extra token needed
- `GET https://isthereanydeal.com/bundles/<id>/` is plain server-rendered HTML (curl-fetchable,
  no Cloudflare/JS challenge observed). Confirmed structure for bundle 16316: tiers/pricing
  present, and `<a href="https://store.steampowered.com/app/<id>/">` links present for every one
  of its 6 games. Games also render as `<a href="/game/<slug>/info/">` — that ITAD-internal
  info page could be a fallback for a non-Steam id if ever needed, but is out of scope for v1
  (only chase it if a bundle turns out to have zero direct storefront links — otherwise mark
  `unresolved:source:isthereanydeal:<bundle-slug>:<game-slug>`).
  A shop-id → name table (`"61":"Steam"`, `"35":"GOG"`, `"16":"Epic Game Store"`,
  `"36":"GreenManGaming"`, `"37":"Humble Store"`, `"6":"Fanatical"`, `"42":"IndieGala Store"`,
  `"2":"AllYouPlay"`, ...) is also embedded in the same bootstrap page's inline script (next to
  the token) as `"shops":{"<id>":["<name>",<flag>], ...}` — fetch/parse it once per crawl and use
  it only as corroboration/logging (which shop a `keys` id maps to), not as the primary Steam-id
  source; the literal `store.steampowered.com` link on the detail page remains authoritative.
- Exact tier/price DOM structure and per-game markup still need a close read during
  implementation (grep the fetched detail HTML by hand or via a quick script) — this plan
  doesn't hand-derive the parser's exact selectors, mirror how `dailyindiegame/parser.py` and
  `greenmangaming/parser.py` extract per-game blocks and adapt.

### Pagination confirmed
- `tab=live`, offset 0 → 30 results, `done: false`. offset 30 → 0 results, `done: true`. So the
  live tab currently has fewer than 60 entries; the crawler must still page until `done: true`
  rather than assuming a fixed count. Same mechanism for `expired`/`pending`.

## Design

**0. Extract shared storefront-identity parsing first.** `STORE_ROOTS`/`parse_store_identity`/
   `StoreName`/`normalized_title` currently live only in
   `src/game_collections/sources/humblebundle/resolver.py`, but they're storefront-URL parsing
   with nothing Humble-specific about them — GreenManGaming's resolver already duplicates the same
   `StoreName`/`STORE_SEARCH_URLS`/`STORE_ROOTS` constants, and isthereanydeal needs the URL→id
   parsing half (`parse_store_identity`, `STORE_ROOTS`) without any of the title-search machinery.
   Move `StoreName`, `STORE_ROOTS`, `parse_store_identity`, and `normalized_title` into a new
   `src/game_collections/sources/storefronts.py` (name TBD at implementation time), keep
   `STORE_SEARCH_URLS`/`parse_store_candidates`/`StorefrontResolver`/`_StoreLinkParser` (the
   title-search-specific half) in `humblebundle/resolver.py` since only Humble/GMG need active
   searching. Update `humblebundle/resolver.py` and `greenmangaming/resolver.py` to import the
   moved names from the shared module instead of redefining them — this is a pure move+re-import,
   not a behavior change, so the existing Humble/GMG tests must still pass unmodified. Do this as
   its own first step/commit before writing any isthereanydeal code, so isthereanydeal's detail-page
   link parsing (`store.steampowered.com/...`, `gog.com/...`, etc.) reuses
   `parse_store_identity(provider, url)` directly instead of a fourth copy of the same logic.

New package `src/game_collections/sources/isthereanydeal/`, mirroring the pattern in
`src/game_collections/sources/README.md` ("Adding a new source"), reusing
`sources/common.py`'s `atomic_write`/`dump_json`/`render_game_list_yaml`/`load_cached_archive`,
and the `log`/`on_offer`/`archive_root` conventions used by both existing sources.

1. **`models.py`** — `ItadArchive` (bundle id, title, provider name + slug, url, dates, tiers),
   `ItadTier`/`ItadItem` (cumulative, each item holding every qualified id we could resolve — not
   just `steam:<appid>`: the detail page's per-game links should be checked for any recognized
   storefront domain, same domains `humblebundle/resolver.py`'s `STORE_ROOTS` already knows about
   (GOG, Epic, Ubisoft, Humble Store) — resolve each one found, no title-search needed since these
   are direct links; `unresolved:source:isthereanydeal:...` only for games with zero recognized
   links). Also a **strict `ItadListSummary` model** for the verbatim list-API entry shape (`id`,
   `title`, `page{id,name,shopId}`, `url`, `isMature`, `isPending`, `start`, `expiry`, `counts{...}`,
   `byob`) — "store verbatim" means *validated through this model* (unknown/changed fields fail
   loudly like every other source here), not an unchecked JSON passthrough; `schema_version:
   Literal[1] = Field(alias="schema", ...)`. Base everything on `StrictModel`/`NonEmptyString` per
   `game_collections/models.py`.

2. **`parser.py`** — `ItadParseError`; `parse_list_page(json_body) -> (done, [raw bundle summary
   dicts])` (trivial — the API already returns clean JSON, just validate the two top-level keys
   exist); `parse_bootstrap_page(html) -> (session_token, shop_names: dict[int, str])` (regex/HTML
   extraction of the inline `"token":"..."` and `"shops":{...}` blobs — treat this as ordinary
   page scraping, not touching any browser/user session); `parse_bundle_detail_page(html, bundle_id)
   -> (tiers, source_payload)` extracting cumulative tier names/prices and, per game, every
   recognized storefront link (`store.steampowered.com`, `gog.com`, `store.epicgames.com`,
   `store.ubisoft.com`, `humblebundle.com`) via the shared `parse_store_identity` from step 0
   above (else leave unresolved). `provider_slug(page_name:
   str) -> str` — small lookup dict + slugify fallback. `real_provider_url(redirect_url: str) ->
   str | None` — decode the `u=` query param from the affiliate-redirect `url` field.

3. **`crawler.py`** — `ItadHttpClient` (bounded-retry `httpx.Client` with a cookie jar, mirroring
   `HumbleHttpClient`; a `bootstrap()` method that GETs `/bundles/`, parses the token/shops via
   `parse_bootstrap_page`, and caches them on the client for reuse; refreshes once on an
   unexpected `400`). `crawl_itad_offers(fetch, ..., tabs=("live",), archive_root=None,
   log=_NO_LOG, on_offer=None)` — for each tab, pages `list/` until `done`, verbatim-storing each
   summary; for each bundle id, fetches the detail page (skippable via
   `sources.common.load_cached_archive` on a cache hit, same resume semantics as the other two
   sources) and builds the tier/item data. Returns an `ItadCrawlReport` (successes + isolated
   per-bundle errors, same shape as `HumbleCrawlReport`/`DigCrawlReport`).

4. **Dedup + provider-aware writer** — `write_itad_offer(...)`:
   - Always writes `archives/isthereanydeal/bundle/<id>/{metadata.json,source.json}` via the
     existing `atomic_write`/`dump_json` helpers (already sorted-key, `indent=2` JSON — same as
     Humble/GMG, good diffs). `source.json` holds the list-API summary **validated through
     `ItadListSummary`** (fails loudly on an unexpected/changed field, like every other source
     here) dumped back out via `model_dump(mode="json")`, not an unchecked passthrough of raw
     JSON — plus the parsed tier/detail-page payload worth preserving.
   - Computes `provider_slug` (from `page.name`) and `real_slug` (from the decoded `url`, last
     path segment) for the `lists/<provider_slug>/...` write.
   - Dedup check: before writing any `lists/<provider_slug>/...yml`, glob
     `lists/<provider_slug>/**/*{real_slug}*` (or scan directory names, case-insensitive substring
     match — Humble's own directories are date-prefixed, e.g. `2026-07-10_squad-goals`, so this
     must be substring/fuzzy, not an exact path check) — if anything matches, **skip** the list
     write for that bundle entirely (log `"  Skipped <slug>: already covered by lists/<provider>/..."`),
     but still write the ITAD archive record (the archive is the aggregator's own view and stays
     complete regardless of what already exists in `lists/`).
   - Otherwise write `lists/<provider_slug>/bundle/<date-prefix>_<real_slug>/<tier-name>.yml` per
     cumulative tier, mirroring the GreenManGaming writer's per-tier-file convention
     (`src/game_collections/sources/greenmangaming/crawler.py`) since that's the shape closest to
     ITAD's own tier data; each list's `references` points back to the ITAD bundle URL and this
     bundle's own archive files. **Date-prefix granularity, matching Humble's own convention in
     `lists/humblebundle/bundle/<YYYY-MM-DD>_<slug>/`**: default to day precision
     (`YYYY-MM-DD`) derived from the bundle's `start` epoch — this is the default for one-off
     bundle drops (Fanatical/IndieGala/AllYouPlay/GreenManGaming/one-off Humble bundles). Only
     drop to coarser precision for a bundle that's inherently fixed to that cadence: a recurring
     monthly bundle (like Humble Choice, which is `YYYY-MM` with no day — already fully owned by
     the dedicated Humble scraper and thus always deduped away here, but keep the rule general
     for any other provider's monthly-cadence bundle ITAD might surface) drops to `YYYY-MM`, and
     a yearly-cadence bundle would drop to `YYYY` — detect cadence from the bundle title/type if
     ITAD signals it, otherwise default to day precision.

5. **`src/game_collections/schema.py`** — add `write_isthereanydeal_schema(...)`, wire into the
   `schema` command, generate `schemas/isthereanydeal-archive.schema.json`.

6. **`src/game_collections/cli.py`** — `@scrape_app.command("isthereanydeal")`: `--tab` (repeatable,
   default `live` only — `expired`/`pending` opt-in, mirroring how the other sources default to
   "currently available" rather than historical), `--refresh`, `--lists-root`, `--archive-root`,
   `log=typer.echo`, `on_offer` closure writing immediately.

7. **Tests** — `tests/test_isthereanydeal_parser.py` (bootstrap-page token/shops extraction,
   list-page pagination parsing, detail-page tier/steam-link extraction, provider slug mapping +
   affiliate-URL decoding, using small inline HTML/JSON fixtures built from the real structures
   above), `tests/test_isthereanydeal_crawler.py` (fake injectable `fetch`, pagination-until-done,
   resume-from-cache, the dedup-skip logic against a fixture `lists/` tree). Extend
   `tests/test_schema.py` for the new schema.

8. **Docs** — root `README.md` "isthereanydeal.com imports" section (note the bootstrap-token
   mechanism briefly, the dedup-skip behavior, and that unresolved games fall back to
   `unresolved:source:isthereanydeal:...` for later `game-collections complete`), and a matching
   pipeline section in `src/game_collections/sources/README.md`. No GitHub Actions schedule unless
   confident it runs unattended cleanly (should be fine, plain HTTP throughout) — lower priority
   than the core feature, add only if time permits.

## Out of scope

- No use of ITAD's official public price-comparison API (api.isthereanydeal.com, needs its own
  API key) — everything here uses the same public, unauthenticated `/bundles/` pages a browser
  gets.
- No chasing the `/game/<slug>/info/` fallback page for non-Steam ids in v1 — only implement if
  real crawls show a bundle has zero recognized direct storefront links otherwise.
- GOG/Epic/Ubisoft/Humble Store links found directly on the detail page ARE in scope and should
  be resolved into the list's `ids:` alongside Steam (see models.py note above) — just no
  title-search resolver for stores that aren't directly linked.
- No changes to the existing humblebundle/greenmangaming/dailyindiegame pipelines themselves —
  isthereanydeal only reads what's already on disk under their `lists/` trees to decide whether
  to skip.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` full suite green.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` regenerates the new schema with
  no drift on a second run.
- Manual smoke test against the live site: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections
  scrape isthereanydeal`, confirm: bundles already covered by `lists/greenmangaming/bundle/lego-at-the-movies`
  and `.../metroidvania-madness` are correctly skipped (logged, not rewritten); at least one
  Fanatical/IndieGala/AllYouPlay bundle produces new `lists/<provider>/...` files with real
  `steam:<appid>` ids; `archives/isthereanydeal/bundle/<id>/source.json` contains the verbatim
  list-API summary. Re-run once more to confirm cache resume skips already-archived bundles.
