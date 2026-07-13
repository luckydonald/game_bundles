Committed clean as `180767d`. Directive complete.

## Report

**Built:**
- `parser.parse_bundle_detail_json` — primary parser, reads the `var page = ["Bundle", {"liveData": {...}}];` script every detail page embeds (mature-gated or not). Accumulates per-tier-exclusive `games` into cumulative tiers, names tiers via `note` → Humble's `entire-{n}-item-bundle`/`{n}-item-bundle` convention → generic `Tier N`, resolves ids from `reviews[].url`.
- `parser.parse_bundle_detail_page` — rewritten from regex onto a BeautifulSoup4 tree, kept as fallback (unchanged public behavior/tests).
- `crawler.crawl_itad_offers` — tries JSON path first, falls back to BS4 path on `None`/`ItadParseError` (logs a note either way); removed the `isMature` skip branch entirely.
- New `config/isthereanydeal-shops.yml` (77-entry shop-id→name table, re-extracted live from the fixture, not hand-copied) + `shop_config.py` loader, wired into the CLI (`--shop-config`) purely for a corroboration log line (shop-key vs. resolved-provider mismatches) — never used for resolution.
- Docs (root + sources README) updated to match.

**Tests:** 141 passing (was 131) — all prior isthereanydeal tests pass unmodified against the BS4 rewrite; added JSON-path coverage (cumulative tiers, Humble naming, BYOB, count-mismatch, mature-bundle end-to-end, shop-mismatch logging) and crawler-level fallback/preference/both-fail cases.

**Live smoke test:** re-ran `scrape isthereanydeal --refresh` against the real site. Both previously-skipped mature bundles now archive and produce real lists: `lists/indiegala/bundle/2026-06-24_sensual-clinic-bundle/` and `lists/allyouplay/bundle/2025-08-23_high-on-life-dlc-bundle/`. Second run (no `--refresh`) confirmed full cache-resume.

**Surprise worth flagging:** for the Sensual Clinic bundle, 3/16 games resolved to real `steam:<appid>` ids and 13 fell back to `unresolved:...` — those 13 are individual DLC packs that simply have no `reviews[]` entry of their own in ITAD's data (not a parsing bug; the corroboration logging surfaced it correctly, since their `keys:[61]` claimed Steam with no matching resolved id). Chasing that via the `/game/<slug>/info/` fallback was explicitly out-of-scope for this plan, so left as-is.

**Commit:** `180767d` on `mane`. Left the earlier `ai: updated prompt`/`ai: save plan …` auto-commit chain and the user's own `fix plan` commit untouched — per the lplp skill's rule against rewriting history behind a real user-authored commit without asking first — and added this as a clean new commit on top instead.