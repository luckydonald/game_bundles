# Fix scrape errors in ai/errors/9.md

## Context

The latest `scrape --git humblebundle` and `scrape --git dekudeals` runs each aborted whole bundles on conditions that should be handled gracefully.
Five distinct causes were traced to code (Humble: 2, Deku Deals: 3 distinct raise sites covering 9 error lines).
Per the repo memory "verify, don't guess external shapes", the Deku `all_one_price` semantics and the Humble Dying Light 2 input must be confirmed against live data before the parsers change.

## Workflow

- Invoke `/code-style` before writing any Python or Markdown, and apply its rules throughout.
- Invoke `/commit-with-lplp-style` and commit each numbered fix below as its own completed task (code, tests, schema and docs for that fix together).
  Stage explicit paths only and write messages via `ai/git/pending-commit.md`.
- Commit order: Humble 1-2, Deku Deals 3-5, DailyIndieGame 6, each preceded by its Step 0 verification.

## Step 0: verify live shapes first

- Fetch `https://www.dekudeals.com/bundles/nuntius-games-bundle` (and one more `all_one_price` bundle) and inspect the Inertia props: does each item carry `tiers`, is there a single tier, what do `item_minimum`/price fields look like?
- Fetch `https://www.humblebundle.com/games/make-play-games-in-godot-software` and confirm it contains only non-game items (software/books), so zero games is legitimate.
- For Dying Light 2, check the archived/parked payload under `archives/humblebundle/` if present, to see which item triggered the non-`store.steampowered.com` URL.
  The code trace says the only uncaught path is a manually pasted URL in `resolver.py:412`.

## Fixes

### Humble

1. **Empty bundle** (`src/game_collections/sources/humblebundle/crawler.py`, `write_humble_offer` around lines 405-461).
   When no tier contains a game, skip writing the list, log a clear "no games (non-game bundle)" message, and do not record it as an error.
   The archive is still written so the offer resumes as already-handled.
   Mirror the existing `kind == "choice"` empty guard.
2. **Invalid pasted store URL** (`humblebundle/resolver.py:412`, `ids.append(parse_store_identity(...))`).
   Catch `ValueError` from the manual "Other…" value, report it, and re-prompt (or fall back to the `unresolved:source:humblebundle:{cache_key}` marker in `--non-interactive`), instead of losing the whole offer.
   If Step 0 shows a non-pasted cause, adjust accordingly.

### Deku Deals

3. **`all_one_price`** (`dekudeals/parser.py:164,200-202`, `dekudeals/models.py:107` and docs 53-59, `dekudeals/crawler.py:250,338,366`).
   Accept it as a third `tiering_style`, modeled per Step 0 findings.
   Expected: one flat price, so a single tier containing every item, with no `pick_quota`.
   Make item inclusion at `crawler.py:250` include all items for this style, and keep `pick_quota` only for `price_per_item`.
   Regenerate `schemas/dekudeals-archive.schema.json` (if it exists) via `game-collections schema`, since the archive model changes.
4. **Item page without storefront links** (`dekudeals/parser.py:285-286`, caller `crawler.py:162`).
   Return an empty store-URL list instead of raising, so the item resolves to just `dekudeals:{slug}` (already always appended at `crawler.py:163-166`).
   This matches the README's "unrecognized stores are silently skipped", and goodies/art packs are not storefront products.
5. **Bundle item with no slug/name** (`dekudeals/parser.py:237-240`, `garbage-dwellers`).
   Skip such items with a warning instead of raising, and re-check that at least one item remains.
   This needs a log hook on `parse_bundle_page` or returning the skipped count to the crawler for logging.

### DailyIndieGame

6. **Missing title span** (`dailyindiegame/parser.py:198`, `TITLE_PATTERN` at lines 30-32; crawler catch at `dailyindiegame/crawler.py:245`; `site_weeklybundle_2420.html`).
   Step 0 addition: fetch bundle 2420 once through the real browser flow and save the HTML to tell apart a Cloudflare/"Loading" interstitial (`DigBrowserClient.fetch`, crawler.py:84-123, returns `page.content()` unchecked), an expired/stub page, and a layout variation (the regex needs the exact class attribute).
   Bundles 2412-2420 are absent from `archives/dailyindiegame/`, and 2421+ parse fine, so an expired or stub page is the likely cause.
   Fix depending on the finding:
   - Interstitial: detect challenge markers in `fetch` and retry or raise a real error.
   - Layout variation: loosen `TITLE_PATTERN` to tolerate extra classes/attributes.
   - Expired/stub page: add `DigBundleUnavailableError(DigParseError)` in `parser.py`, catch it in `crawl_dig_offers` before the generic handler, log "skipped (no title span)" and do not add to `errors`, so the exit code stays 0.

## Tests and docs

- `tests/test_dailyindiegame_parser.py`: update `test_bundle_page_requires_a_title` (lines 96-103) for the chosen behavior.
- `tests/test_dailyindiegame_crawler.py`: add a case where a fetched page has no title span and the report has no errors (existing isolation test is lines 154-167).
- `src/game_collections/sources/README.md` lines 47-58: note how unavailable bundle pages are handled.

- `tests/test_dekudeals_parser.py`: add an `all_one_price` bundle case, change `test_item_page_requires_at_least_one_store_link` (lines 198-205) to assert an empty URL list, and add a no-slug item skip case.
  `test_bundle_page_rejects_unrecognized_tiering_style` keeps passing with `"something_new"`.
- `tests/test_dekudeals_crawler.py`: add a crawl for `all_one_price` and for an item without links.
- `tests/test_humblebundle_crawler.py`: add a software-only bundle that is skipped without error.
- `tests/test_humblebundle_resolver.py`: add a bad pasted URL through `resolve_item` (existing coverage is lines 81-85, 157-165).
- Update `src/game_collections/sources/README.md` (lines ~100-101) for `all_one_price`, linkless items, skipped nameless items and non-game Humble bundles.
- Follow `CLAUDE.md` style: full annotations, early returns, bare `# end …` comments, no private-prefixed new names.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_dekudeals_parser.py tests/test_dekudeals_crawler.py tests/test_humblebundle_crawler.py tests/test_humblebundle_resolver.py tests/test_schema.py -q`, then the full suite.
- `uv run game-collections schema` leaves no drift, and `uv run game-collections validate` passes.
- Re-run `scrape dekudeals` for the failing slugs (e.g. `nuntius-games-bundle`, `garbage-dwellers`, `dying-light-2-stay-human-complete-dlc-bundle`) and `scrape humblebundle --url` for the two failing Humble URLs, without `--git`, to confirm the errors are gone.
- Commit per repo workflow (`commit-with-lplp-style`, explicit paths, message via `ai/git/pending-commit.md`).
  `ai/errors/9.md` is untracked and should be sanitized with the `sanitize-error-logs` skill if it is to be committed.
