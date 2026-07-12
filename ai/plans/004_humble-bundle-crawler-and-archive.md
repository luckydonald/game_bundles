# Humble Bundle crawler and archive

## Summary

Implement `game-collections scrape humblebundle` to crawl current [Humble Choice](https://www.humblebundle.com/membership) and active [Games bundles](https://www.humblebundle.com/bundles), generate standard game lists, and retain normalized metadata plus canonical embedded source JSON. Convert all descriptions from HTML to normalized Markdown.

## Implementation and commits

- Activate `commit-with-lplp-style` before any implementation work.
- Begin by checking repository status and the last two commits. Preserve substantive plan revisions as separate, properly renamed `ai: Plan:`/`ai: Plan update:` commits; fold nearby prompt/decision auto-commits according to the skill.
- Commit every completed implementation task. Before each commit:
  - Inspect status and changed paths.
  - Stage only explicit task-owned files.
  - Remove and recreate `ai/git/pending-commit.md`.
  - Commit with `-F ai/git/pending-commit.md`, amending an applicable nearby auto-commit when required.
- Use scoped commits for:
  1. Humble parsing, archive models, Markdown conversion, and fixtures.
  2. Store resolution, reviewed mapping, interactive selection, and tests.
  3. CLI orchestration, deterministic writers, schemas, and integration tests.
  4. Documentation and the verified initial live crawl.
- Never include unrelated dirty-tree changes in these commits.

## Key changes

- Add a launcher-neutral Humble source module with typed fetching, parsing, normalization, storefront resolution, and atomic output writing.
- Default command behavior crawls Choice and every active Games bundle while skipping Books and Software. Repeated `--url` options allow focused reruns; options also configure list, archive, and resolution-map roots.
- Generate:
  - `lists/humblebundle/choice/YYYY-MM.yml`
  - `lists/humblebundle/bundle/YYYY-MM-DD_<url-slug>/entire-<count>-item-bundle.yml`
  - Lower tiers as `<count>-item-bundle.yml`
- Use the bundle start date for its prefix, falling back to its end date. Fail an offer if neither exists.
- Standard tier lists contain cumulative real games only. Coupons, subscriptions, and bonuses remain in metadata but are excluded from `.yml` game lists.
- Resolve qualified IDs through each advertised store’s own search:
  - Automatically accept only a unique normalized-title match.
  - Otherwise show ranked candidates.
  - Allow “Other…” to accept a canonical store URL or direct ID.
  - Blank input records `unresolved:humblebundle:<machine-name>`.
  - Support `steam:<appid>`, `gog:<slug>`, `epic:<slug>`, `ubisoft:<slug>`, and `humble:<store-slug>`.
  - Persist reviewed selections in a strict checked-in YAML map keyed by Humble machine name.
  - Preserve multiple real storefront IDs; use the unresolved fallback only if no real identity was found.
- Store archives under:
  - `archives/humblebundle/choice/YYYY-MM/{metadata.json,source.json}`
  - `archives/humblebundle/bundle/YYYY-MM-DD_<url-slug>/{metadata.json,source.json}`
- Write canonical JSON with sorted keys, two-space indentation, UTF-8, and a trailing newline. Preserve complete relevant embedded payloads rather than full HTML.
- Normalized metadata records:
  - URL, Humble identifier, headline, Markdown description, Games category, UTC start/end/crawl timestamps, charities, and expiration text.
  - Every tier’s name, advertised count, localized minimum price, and complete repeated item list.
  - Item title, retail price, video and cover-art URLs, developers, publishers, redemption stores, platforms, Markdown description, tags, genres, ratings, regional information, and resolution results.
  - Prices as `{raw, value, currency, currency_code}`.
- Existing archives are atomically updated but never automatically deleted.
- Add `markdownify`, strict normalized archive models, a generated Humble archive schema, and backward-compatible Humble output support in `game-collections schema`.
- Update the root and lists documentation with crawling, resolution, archive, rerun, and unresolved-ID behavior.
- Finish by running a live crawl and committing the resulting current Choice and active Games data.

## Test plan

- Parse sanitized fixtures for the bundle index, a multi-tier Games offer, and Choice.
- Verify category filtering, date fallback, paths, cumulative tiers, advertised counts, coupon exclusion, Markdown conversion, prices, charities, expiration text, and all requested item metadata.
- Mock each store search and test exact matches, ranked ambiguity, manual selection, pasted URLs/IDs, invalid hosts, blank unresolved fallback, multiple IDs, and persisted overrides.
- Verify sorted two-space JSON, deterministic YAML, idempotent reruns, atomic writes, retained archives, and isolated per-offer failures.
- Validate every generated `.yml`, test archive/schema drift, then run the full pytest, list validation, and schema commands.
- Treat unresolved identities as successful output with warnings; network, parsing, validation, or write failures produce a final nonzero exit after other offers finish.

## Assumptions

- Canonical embedded JSON is the archival source; complete HTML pages are not committed.
- Standard lists contain games only, while metadata preserves every advertised item.
- Store ranking supplies candidates but never permits silently accepting a fuzzy or ambiguous result.
- Reviewed and explicitly unresolved decisions remain durable until the checked-in resolution map is edited.
