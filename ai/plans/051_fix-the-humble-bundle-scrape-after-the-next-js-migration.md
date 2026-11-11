# Fix the Humble Bundle scrape after the Next.js migration

**Commit style:** Skill `/commit-with-lplp-style` is active — auto-commit following it for this implementation.

## Context

Todo `87654de1-5dcf-4b4c-8a7a-391c089e3937` ("Fix Humblebundle", no description).
Reproduced with `game-collections scrape humblebundle --non-interactive` on 2026-11-11: it writes 0 files and reports `bundles page is missing landingPage-json-data` and `Choice page is missing content or marketing JSON`.
The 87 humble unit tests pass, because they run against old saved HTML fixtures.

Root cause: humblebundle.com is now a Next.js (Turbopack, app router) site.
The old `<script id="landingPage-json-data">`, `webpack-bundle-page-data` and `webpack-choice-*-data` JSON blobs are gone from `/bundles`, `/games/<slug>` and `/membership`.
The data is now in React Server Component flight data, pushed through `self.__next_f.push([1,"…"])` script tags, like Digiphile's pages.

## Findings (verified live 2026-11-11, saved under /tmp/hb in the scratchpad session)

- `/bundles`: the flight text holds `{"relationTo":"algolia-hit","value":{…}}` records with `slug`, `url` (`/games/<slug>`), `title`, `productKey`, `endDate`, `itemsCount`, `value` (cent precision), `category`, `productType` (`humble-bundle`) and `includedItemTitles`.
  This replaces the old `landingPage-json-data` `mosaic[].products[]` (`product_url`, …).
- `/games/<slug>`: the flight text holds `"tiers":[{"id":"1","sku":…,"bundleItems":[{"id","key","tpkdSkus":[…steam skus…],"title","description" (HTML),"msrp","developers","publishers","deliveryMethods","platforms","bundleType",…}]}]`, plus the charity and description blocks.
  This replaces `webpack-bundle-page-data` (`bundleData.tier_item_data`, `tier_display_data`, …).
- `/membership`: also flight data now (no `webpack-choice-*` scripts); its shape is not yet inspected.
- The failed run also rewrote two archives (`archives/humblebundle/bundle/2026-10-21_15th-anniversary-scifi-exposure/metadata.json` and `archives/humblebundle/choice/2026-10/metadata.json`, 35 lines changed).
  I have not reverted them; I'll check whether the diff is just a re-observed timestamp and leave the decision to you.
- Reusable: `sources/digiphile/parser.py` already has `flight_text()` (joins and decodes the `__next_f` pushes) and `decode_after_key()` (pulls a JSON value after a key out of the flight text).
  Per the "no `_` prefix, split modules" preference, move these into a shared module (e.g. `sources/flight.py`) in a pure-move commit first, then have both Digiphile and Humble import it.

## Plan

1. **Pure move commit:** `flight_text`/`decode_after_key` from `sources/digiphile/parser.py` to a shared `sources/flight.py`, Digiphile imports it, no behaviour change, Digiphile tests green.
2. **Fixtures:** save real, sanitized-by-nature (public pages) HTML of the three page kinds as new fixtures in `tests/fixtures/` (an active Games bundle, e.g. `15th-anniversary-scifi-exposure`, the bundles index and the membership page), keeping the old fixtures for the legacy parser tests until the legacy code is removed.
3. **Index:** rewrite `parse_bundle_index` in `sources/humblebundle/parser.py` to read `algolia-hit` records from flight data and return the same record shape the crawler consumes (map `url`→`product_url`, etc.), filtering to `/games/` and `productType == humble-bundle`.
4. **Bundle page:** rewrite `extract_bundle_payload`/`_bundle_item` input handling to read `tiers[].bundleItems[]` (steam skus in `tpkdSkus`, `msrp`, platforms, delivery methods, HTML description for the existing DLC-list and edition-component logic) and keep producing the existing `HumbleArchive`/list output so lists and archives stay byte-compatible for already-scraped bundles.
   Anything the new payload no longer carries (e.g. a field that archive models require) is checked live first; no guessing, per the "verify, don't guess external shapes" rule.
5. **Choice (`/membership`):** rewrite `extract_choice_payload`/`build_choice_archive` to read the flight data.
   Verified live (2026-11-11): the page has a CMS block `"blockType":"choice-media-carousel"` ("This Month's Games") whose items are `{"id":"<machine_name>_choice","productType":"humble-choice","title","thumbnail","description":"$NN","displayPrice","genres","deliveryMethods","platforms","developers","endDate"}`.
   There are 8 items today, for November 2026 (`Get November 2026 Humble Choice …` text, plus `2026-10-31` / `2026-11-10` dates in the block).
   - Mapping onto `HumbleItem`: `id`→`machine_name` (as before: the old pages used the same `…_choice` machine names), `deliveryMethods`→`redeem_on`, `platforms`, `genres`, `thumbnail`→cover art, `displayPrice`→retail price (EUR now, the old `msrp` was USD; I'll keep the currency the page states and verify the archive price model copes).
   - `description` is a flight text reference (`"$73"` → a `73:T…,<text>` chunk), so `sources/flight.py` also needs a `resolve_reference()` that follows `$<hex>` ids to their text chunk.
   - Month: parsed from the "`<Month> <year> Humble Choice`" text on the page (replaces the old marketing JSON month); the existing `<month>_<year>_choice` machine-name regex in `crawler.py` (line ~270) stays.
   - **Known gaps, no guessing:** the new page has no pick quota (`tierInfo`/`uses_choices`) and no per-game YouTube links or recommendation copy.
     `choice_pick_options` therefore becomes empty for the live scrape (the old pick-option lists `choice/<key>/…` are only produced from archives that already have them), and the plan is to log a warning rather than invent quotas.
     If you know where the quota shows now (e.g. only visible to members), tell me; otherwise it stays unknown.
   - Past months: `/membership/<month>-<year>` is 404 now, so only the current month can be scraped live; archived months stay as they are.
6. **Archive schema:** if the archive models change, regenerate `schemas/humblebundle-archive.schema.json` via `game-collections schema`; `migrate --type source` handles any version bump.
7. **Docs:** update `sources/README.md` (Humble section: flight data instead of embedded JSON scripts) and the root `README.md` if behaviour text mentions the old format.

## Tests

- Unit tests for the three parsers against the new fixtures, asserting concrete values from the real pages (bundle title, 8 items of the sci-fi bundle, tier ids, steam skus).
- A test that the old "missing JSON" error is still raised for an unrelated HTML page.
- Full suite: `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest`, then `game-collections validate` and `game-collections schema` (drift check).

## Verification

Live run: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --non-interactive` must report >0 offers and no parsing errors, and `git diff` of `lists/`/`archives/` must show only plausible changes (re-observed timestamps, new bundles), not mass rewrites of existing bundles.
The live-run output files are committed separately as a manual-scrape style commit only if you ask for it.
