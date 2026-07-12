# isthereanydeal: parse the embedded `var page` JSON instead of regex/HTML positions

## Context

The just-shipped `isthereanydeal` source (`src/game_collections/sources/isthereanydeal/`) skips
mature-rated bundles because the site visually gates mature content behind a client-side
"confirm" button that sets `localStorage["mature"] = "true"` on `https://isthereanydeal.com`. The
user asked to check whether that gate implies a JS `fetch`/API call revealing full data, since
that data would be useful for every bundle, not just mature ones.

Confirmed by fetching a real mature bundle page (`https://isthereanydeal.com/bundles/16299/`)
with a plain unauthenticated `curl` (no cookies, no JS, no `localStorage`): the full bundle data —
tiers, prices, every game with its storefront review/link — is **already present** in the raw
HTML response, inside an inline `<script>var page = ["Bundle", {"liveData": {...}}];</script>`
block. The mature-content button is a pure client-side visual overlay; it does not gate the data
at all, and there is no separate XHR/fetch endpoint to find — this *is* effectively "the API" the
user suspected, just delivered via SSR rather than a second request. This means:

1. Mature bundles can be fully parsed like any other bundle — the current skip is unnecessary.
2. This same JSON blob is a much more robust primary data source than the current positional
   HTML-regex parser (`parse_bundle_detail_page` in `parser.py`) for **every** bundle, not just
   mature ones — no DOM-order inference, no regex over rendered markup.
3. Per the user's explicit instruction, the existing HTML-regex parser must be **kept**, not
   deleted, as a fallback for if/when the JSON blob's shape or presence ever changes.

Additionally: `var g = {...}` on the bootstrap page (`/bundles/`) — already used today only for
its `"token"` — also carries a `"shops": {"<id>": ["<name>", <flag>], ...}` table (~77 entries,
game-store id → display name, e.g. `"61":["Steam",0]`, `"35":["GOG",1]`, `"16":["Epic Game
Store",1]`) that isn't captured anywhere yet. The user wants this filled into a config file.

## Research findings (verified against real fetched pages, don't re-derive)

- `var page = ["Bundle", {"liveData": {...}, "revision": ..., "revisionData": ..., "diff": ...,
  "thread": ...}];` appears on every `/bundles/<id>/` detail page. `liveData` keys: `title`,
  `page` (same `{id,name,shopId}` shape as the list API), `mature`, `byob`, `tiers`, `id`, `url`,
  `message`, `publishedAt`, `lastUpdate`, `start`, `expiry`, `createdBy`, `isPending`,
  `isPublished`, `isRejected`, `isExpired`.
- `liveData.tiers` is a list of `{"price": [amount_cents, "CUR"] | null, "addon": bool, "games":
  [...], "note": ...}`. **Confirmed per-tier EXCLUSIVE, not cumulative**: a live 3-tier
  GreenManGaming bundle (16316) has `tiers[0].games` = the 2 Bronze-only games, `tiers[1].games` =
  the 2 *additional* Silver games, `tiers[2].games` = the 2 *additional* Gold games — the crawler
  must accumulate tiers in order to reproduce the cumulative `ItadTier.items` shape the rest of
  the pipeline already expects (same cumulative-building idea the current positional parser does,
  just from clean structured data instead of DOM order). A flat-price bundle (Humble/IndieGala,
  e.g. 16381, 16339) has exactly one tier with `price` set and all games. A Build-Your-Own
  bundle (Fanatical, e.g. 16375) has exactly one tier with `price: null` and all games, plus a
  top-level `liveData.byob` list of `{"count": N, "price": [..., "CUR"]}` picks (already
  intentionally unmodeled today — `ItadTier.price` is `None` for this shape, matches as-is).
  **Tier display name**: `tiers[i].note` *does* carry it when the provider sets one — confirmed
  `note: "Bronze"/"Silver"/"Gold"` for the GreenManGaming bundle, `note: null` for the Humble/
  Fanatical/IndieGala fixtures. So: use `tier.note` when non-null/non-empty; when null, use
  `f"Tier {index + 1}"` — **except** for Humble-provider bundles, where the ITAD JSON never
  carries a name but the dedicated Humble scraper's own convention is well known and should be
  matched for consistency (`src/game_collections/sources/humblebundle/crawler.py:279-284`): the
  tier whose `item_count` equals the bundle's total game count is named `entire-{item_count}-item-bundle`,
  every other tier is named `{item_count}-item-bundle` (match by item_count, not tier index —
  Humble's own tier list order isn't guaranteed to line up with ours).
- Each `game` entry: `id` (ITAD uuid), `slug`, `title`, `type`, `mature`, `assets`, `tags`,
  `features`, `reviews`, `note`, `drmfree`, `keys` (shop-id ints, e.g. `[61]`), `platforms`,
  `bundled`. `reviews` is a list of `{"source": "Steam", "count", "positive", "neutral",
  "negative", "url": "https://store.steampowered.com/app/<id>/"}` — **`url` is the same kind of
  direct storefront link** the current parser already scans for in raw HTML, just handed to us
  structured. Across all 4 fixture bundles checked (GreenManGaming/Fanatical/Humble/IndieGala), no
  game had more than one `reviews`/`keys` entry — single-store is the common case, but the
  code must not assume exactly one.
- Confirmed present and unaffected by the mature flag: `bundle_16299_mature.html` (IndieGala,
  "Sensual Clinic Bundle", `liveData.mature: true`) parses identically via the same JSON path —
  16 games, real Steam review URLs, no gating in the raw response at all.

## Design

**Prefer BeautifulSoup4 over regex for HTML structure wherever there's a choice** (already a
locked project dependency via `uv.lock`, not a new addition). Concretely:
- `parse_bootstrap_page`'s `<script>` lookup: use BS4 to find the right `<script>` tag (e.g.
  `soup.find("script", string=re.compile(r"^\s*var g ="))`) instead of a regex scan over the
  whole raw HTML document; the JSON-substring extraction *inside* that script's text (balanced-
  brace scanning, since it's a JS variable assignment, not markup) stays as today — that part
  isn't HTML structure, so BS4 doesn't apply to it.
- The **legacy fallback** `parse_bundle_detail_page`: rewrite it against a BS4 tree
  (`BeautifulSoup(html, "html.parser")`, `soup.select("a[href*='/game/']")`,
  `soup.select_one(".tier-name")`, `.get_text(strip=True)`, etc.) instead of `TITLE_PATTERN`/
  `TIER_HEADER_PATTERN`/`TIER_PRICE_PATTERN`/`GAME_LINK_PATTERN`/`STORE_LINK_PATTERN`. Same
  cumulative-building logic and same invariant checks, just walking real DOM nodes instead of
  regex-matching serialized markup — this is the whole point of keeping this path around as a
  fallback: it should be *more* resilient to markup changes than today's version, not equally
  fragile in a different way.
- The **new JSON path** doesn't touch HTML structure at all once the blob is extracted (it's
  already parsed JSON), so BS4 isn't relevant there beyond locating the `<script>` tag itself.

1. **`parser.py`**: add `parse_bundle_detail_json(html, bundle_id, expected_game_count) ->
   list[ItadTier] | None`. Returns `None` (not a raised error) when `var page = ` isn't found at
   all (locate via BS4 the same way as the bootstrap token, see above), so the crawler can
   cleanly try the legacy path next; raises `ItadParseError` same as today for anything
   found-but-malformed (bad JSON, wrong tuple tag, missing `liveData`, tier/game-count mismatch,
   etc. — reuse the existing invariant checks at the bottom of `parse_bundle_detail_page`:
   `len(cumulative) == expected_game_count`, non-empty tiers). Extract the `[...]` blob the same
   way `_extract_balanced_object` already does for `{...}` (add a bracket-matching sibling, or
   generalize the existing helper to take the opening delimiter). Refactor the current
   `_resolve_item_ids(html, start, end, bundle_id, slug)` into a small `_resolve_urls(urls:
   list[str], bundle_id, slug) -> list[str]` used by **both** parsers: the legacy (BS4) path
   calls it with the `href`s it collects from the relevant DOM slice, the new JSON path calls it
   with `[r["url"] for r in game["reviews"]]`. Keep `parse_bundle_detail_page` (the legacy
   parser, now BS4-based per above) completely intact and present as the fallback — never remove
   it, per explicit instruction.

2. **`crawler.py`**: change the per-bundle step to call `parse_bundle_detail_json` first; if it
   returns `None` or raises `ItadParseError`, log one line (e.g. `"  <slug>: no embedded page data,
   falling back to HTML parsing"`) and call `parse_bundle_detail_page` same as today. **Remove**
   the `summary.is_mature` skip-branch (around line 249) entirely — mature bundles now go through
   the normal parse path like any other bundle.

3. **New shop-id config**, filled from the real `var g.shops` table already captured during this
   investigation (~77 entries) — extend `provider_config.py`'s loading pattern with a sibling
   `config/isthereanydeal-shops.yml` (`schema: 1`, `shops: {"<id>": "<name>", ...}`), loaded once
   per crawl alongside the bootstrap token/shops call that already exists in `parse_bootstrap_page`
   (that function *returns* `shop_names` today — check whether it's already threaded through to
   the crawler or silently discarded; if discarded, wire it through). Use this **only** for a
   corroboration log line: for each game, compare its `keys` shop ids' names against which
   provider(s) its resolved `ids` actually belong to, and log a one-line mismatch warning (e.g. a
   `keys: [35]` GOG entry with no resolved GOG id) — never use it to resolve/construct an id
   itself; `reviews[].url` + `parse_store_identity` remains the sole source of truth for ids, per
   the original plan.

4. **Tests**: add JSON-blob fixtures trimmed from the real fetched pages (GMG 3-tier cumulative,
   Fanatical BYOB, the mature IndieGala bundle) to `tests/test_isthereanydeal_parser.py`/
   `tests/test_isthereanydeal_crawler.py`. Cover: JSON path produces the same `ItadTier`/`ItadItem`
   shape as the legacy path did for an equivalent fixture; fallback triggers correctly when the
   `var page` script is stripped from an HTML fixture (legacy parser still succeeds); a bundle
   that fails both paths still raises `ItadParseError`; the previously-skipped mature bundle now
   produces a full parsed result end-to-end; the shops-config mismatch log line fires without
   raising.

5. **Docs**: update the isthereanydeal section of root `README.md` to describe the dual-path
   parser (embedded-JSON primary, HTML-regex fallback) and that mature bundles are now included
   (remove the "mature bundles are skipped" line).

## Out of scope

- No behavior change to bundles already dedup-skipped against Humble/GreenManGaming's own
  scrapers — this is purely about *how* a bundle's own detail page gets parsed once we've decided
  to write it.
- No modeling of `reviews[].count/positive/neutral/negative`, `tags`, `features`, or `bundled` —
  not asked for, keep `ItadItem` as-is (slug/title/ids).
- No change to `ItadTier`/`ItadItem`/`ItadPrice` models — verified the JSON maps onto the existing
  shapes without changes.
- `ai/pending.tmp.md` has a note "we need to add support for BYOB" — as implemented today, BYOB
  bundles already produce one synthetic all-games tier with `price: None` (the per-pick pricing
  table in `liveData.byob`/the list API's `byob` flag is intentionally not modeled). If that note
  means something more than this, it's a separate ask — not folded into this plan; flag it back
  to the user rather than guessing scope.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` full suite green.
- Live smoke test: re-run `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape
  isthereanydeal --refresh` and confirm the two previously-skipped mature bundles (16299 "Sensual
  Clinic Bundle" / IndieGala, 15363 "High on Life: DLC Bundle" / AllYouPlay) now produce real
  `lists/indiegala/...`/`lists/allyouplay/...` entries instead of being logged as skipped, while
  everything else's output is unchanged from the prior run (diff the `lists/`/`archives/` trees
  before/after to confirm no regression).
