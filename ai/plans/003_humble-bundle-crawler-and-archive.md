# Humble Bundle crawler and archive

## Summary

Add a `game-collections scrape humblebundle` workflow that reads embedded structured data from [Humble Bundles](https://www.humblebundle.com/bundles), active Games offers, and [Humble Choice](https://www.humblebundle.com/membership). It will generate standard launcher-neutral game lists, normalized metadata archives, and canonical source JSON without changing the existing game-list contract.

Descriptions will be converted from HTML to normalized Markdown.

## Key changes

- Add a Humble source module with typed fetching, parsing, normalization, storefront resolution, and atomic output writing.
- Default crawl discovers current Choice plus every active Games bundle; Books and Software are skipped. Repeated `--url` options limit a run to specific offers.
- Add CLI options for `--lists-root`, `--archive-root`, `--resolution-map`, and non-interactive operation. Network or parsing failures continue with other offers but produce a final nonzero exit; unresolved identities produce warnings without failing the crawl.
- Generate these standard lists:
  - `lists/humblebundle/choice/YYYY-MM.yml`
  - `lists/humblebundle/bundle/YYYY-MM-DD_<url-slug>/entire-<count>-item-bundle.yml`
  - Lower tiers use `<count>-item-bundle.yml`.
  - Bundle dates use the offer start date, falling back to the end date; fail that offer if neither exists.
  - Tier files contain cumulative real games only. Coupons, subscriptions, and other bonuses remain archived but are excluded from standard lists.
- Resolve qualified IDs using each advertised redemption store’s own search:
  - Automatically accept only a unique normalized-title match.
  - Otherwise show ranked candidates and let the user select one.
  - The final “Other…” choice accepts a canonical store URL or direct ID.
  - Blank input records `unresolved:humblebundle:<machine-name>`.
  - Parse canonical identities such as `steam:<appid>`, `gog:<slug>`, `epic:<slug>`, `ubisoft:<slug>`, and `humble:<store-slug>`.
  - Persist reviewed results in a checked-in, strict YAML resolution map keyed by Humble machine name. A game may carry multiple storefront IDs; the unresolved fallback is used only when no real identity was resolved.
- Archive each offer separately:
  - `archives/humblebundle/choice/YYYY-MM/{metadata.json,source.json}`
  - `archives/humblebundle/bundle/YYYY-MM-DD_<url-slug>/{metadata.json,source.json}`
  - JSON uses sorted keys, two-space indentation, UTF-8, and a trailing newline.
  - `source.json` preserves the complete relevant embedded payloads: listing record plus `bundleData` for bundles; JSON-LD, Choice content, marketing, and charity payloads for Choice.
  - Existing archives are updated atomically but never automatically deleted.
- Strict normalized metadata includes:
  - URL, Humble machine name, headline, Markdown description, Games category, start/end/crawl timestamps, charities, and key-expiration text.
  - Every tier’s name, advertised item count, localized minimum price, and complete repeated item list.
  - Every item’s Humble machine name, title, retail price, YouTube and cover-art URLs, developers, publishers where available, redemption stores, platforms, Markdown description, tags such as `Coupon`, genres/ratings/region data when exposed, and resolution results.
  - Prices use `{raw, value, currency, currency_code}`, preserving forms such as `€5.11`, numeric `5.11`, symbol `€`, and ISO code `EUR`.
  - Dates are normalized to UTC ISO-8601 while original representations remain in `source.json`.
- Add `markdownify` for consistent HTML-to-Markdown conversion.
- Add a generated Humble archive JSON Schema and extend `game-collections schema` with a Humble schema output while preserving the existing game-list `--output` behavior.
- Document crawling, interactive resolution, archive layout, unresolved IDs, reruns, and generated tier semantics in the root and lists READMEs.
- After verification, run one live crawl to seed the current Choice and active Games bundle archives/lists, resolving ambiguities interactively.

## Test plan

- Parse sanitized fixtures for the bundles index, a multi-tier game bundle, and Choice.
- Verify category filtering, start/end fallback, date-prefixed paths, cumulative tier membership, advertised counts, and coupon exclusion from standard lists.
- Verify all requested metadata, Markdown conversion, expiration extraction, localized prices, charities, platforms, developers, and duplicate items across archived tiers.
- Mock Steam, GOG, Epic, Ubisoft, and Humble searches; test unique matches, ranked ambiguity, candidate selection, pasted URLs/IDs, invalid hosts, blank unresolved fallback, multiple IDs, and persisted overrides.
- Verify canonical sorted two-space JSON, deterministic YAML, idempotent reruns, atomic writes, preservation of previous archives, and per-offer failure isolation.
- Validate every generated `.yml` through the existing loader and add archive/schema drift tests.
- Run focused crawler tests followed by the full `uv run pytest`, `game-collections validate`, and schema checks.

## Assumptions

- “Archive” means canonical structured source JSON rather than full HTML.
- Standard tier lists contain games only; archived metadata retains every advertised item.
- Store search ranking supplies candidates but never justifies silently accepting a non-unique or fuzzy match.
- Human-approved and explicitly unresolved decisions are durable until the checked-in resolution map is edited.
