# Compound-offer / package-content expansion (Frostpunk GOTY, Dead Cells + DLC)

## Context

Some bundle offers (Humble, and bundles ITAD aggregates) are not single products — they bundle multiple separately-ownable storefront items under one title, e.g.:

- Humble "Dead Cells + The Bad Seed DLC" → should become two Games: Dead Cells (`steam:588650`) and Dead Cells: The Bad Seed (`steam:1204130`).
- Humble "Frostpunk: Game of the Year edition" → has its own Steam bundle page, but must NOT resolve to that bundle id (bundle ids aren't individually ownable) — it must expand to its contents: Frostpunk (`steam:323190`) and Frostpunk: On The Edge (`steam:1147010`).

Today, both `src/game_collections/sources/humblebundle/` and `src/game_collections/sources/isthereanydeal/` do strict 1-offer-item → 1-`Game` writes (confirmed: `humblebundle/crawler.py` `write_humble_offer` L247-352; `isthereanydeal/crawler.py` `write_itad_offer` L444-522). Humble's resolver does pure exact-title storefront search with no compound-title handling at all. ITAD's per-item id resolution comes only from review links on the bundle page itself — it never visits an item's own `/game/<slug>/info/` detail page during a bundle crawl, so it never sees that page's "Contents of this package" section. `Game.ids` (`models.py`) is OR/alternative-identity semantics only (owning any one id counts as owning the whole Game — confirmed via `completion.py:44-62`); there's no existing AND/bundle concept, and this plan does not add one — a package instead expands into N ordinary flat `Game` entries.

ITAD already models packages structurally (a "Contents of this package" section linking to each sub-item's own detail page, which resolves via the same `itad.link` redirect mechanism already used for top-level resolution) and already lists genuinely-flat multi-item bundles (Dead Cells + Bad Seed) as independent flat items with no grouping needed. The dedicated-scraper-vs-ITAD dedup logic (`isthereanydeal/crawler.py` `_existing_choice_match`/`_existing_list_match`, L376-419, invoked L436-442) is currently a binary skip: if a Humble-authored list already exists for a bundle, ITAD never improves it even when ITAD's data is strictly more complete (e.g. Humble dropped the DLC or left it `unresolved:`).

User decisions from discussion:
- Do compound-title detection in **both** places: ITAD (package-content parsing) and Humble (its own resolver, splitting `"A + B"`-style titles directly, falling back to ITAD for non-splittable titles like GOTY editions).
- Add a public `group` field to `Game` linking entries that came from splitting one source offer, carrying **both** a stable id and the original human-readable compound title (e.g. "Frostpunk: Game of the Year Edition") — not just a slug.

## Phase 1 — `src/game_collections/models.py` (public schema)

Add:

```python
class GameGroup(StrictModel):
    """Provenance link for Games split out of one compound source offer."""
    id: NonEmptyString      # stable, locally-scoped label (e.g. Humble machine_name or ITAD package slug) — not globally unique
    name: NonEmptyString    # the original human-readable compound title, verbatim
# end class GameGroup

class Game(StrictModel):
    name: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)
    group: GameGroup | None = None
    ...
```

- `group` is purely descriptive provenance metadata. **No change** to `completion.py:evaluate_completion` or `launchers/steam/adapter.py:SteamAdapter.evaluate` — each `Game.ids` list still independently determines ownership of that one Game (OR semantics unchanged).
- New validator in `GameList.validate_games` (models.py:111-127): within one list, all `Game`s sharing the same `group.id` must have an identical `group.name` (cheap guard against copy/paste drift on manual edits). Do not require `group.id` uniqueness across lists/files — no cross-list registry exists today (`lists.py`'s `discover_game_lists` only dedups list IDs, not qualified game ids, across files).
- Regenerate `schemas/game-list.schema.json` (`uv run game-collections schema`); `tests/test_schema.py` will catch drift if missed.

## Phase 2 — isthereanydeal: package-content detection

**First implementation step: verify the live JSON shape.** Fetch a real GOTY-style ITAD game page (e.g. `frostpunk-game-of-the-year-edition`) through the existing resolver fetch path (not a generic web tool — the embedded `var page = ["Game", {...}]` JSON that `parse_game_detail_json` already parses is likely script-tag-only and won't survive naive HTML→markdown conversion) to confirm the exact key holding package contents before writing the parser.

- `sources/isthereanydeal/models.py`: add `ItadPackageContent(StrictModel)` — `slug`, `title`, `ids: list[NonEmptyString]`. Extend `ItadItem` with `package_contents: list[ItadPackageContent] = Field(default_factory=list)` (empty = flat item, matches 100% of current data — no archive migration needed).
- `sources/isthereanydeal/parser.py`: extend `parse_game_detail_json` (L535-580) to extract package contents when present; add an HTML-fallback parser alongside the existing `parse_bundle_detail_page` (L583+) pattern if the JSON turns out not to carry this data.
- `sources/isthereanydeal/resolver.py`: extend `resolve_game` (L73-110) — when a fetched detail page carries package contents, recursively resolve each sub-item via its own `/game/<slug>/info/` page (same fetch/redirect machinery, one level deep only — packages don't nest). On a sub-item resolution failure, emit `unresolved:source:isthereanydeal:<bundle_id>:<sub_slug>` using the **existing** marker format/regex (`_UNRESOLVED_PATTERN`, L18-35) — `complete --provider isthereanydeal`'s existing `resolve_isthereanydeal_markers` already handles arbitrary slugs, so it needs no changes to pick these up later.
- **Where the fetch happens**: `crawl_itad_offers` (crawler.py L296-371) must start visiting each `ItadItem`'s own detail page during the bundle crawl (today it only reads the bundle page). Always fetch (gated by the existing per-item archive cache, `write_itad_game_archive`, so re-crawls after the first pass are cheap) rather than a title-pattern heuristic — simpler and reuses existing caching infrastructure instead of adding a second heuristic surface. Confirm with the user if this per-item fetch volume is acceptable for the scheduled GitHub Actions scrape cadence (CLAUDE.md) before merging — flagged as a review point, not blocking the plan.
- `sources/isthereanydeal/crawler.py` `write_itad_offer` (L444-522): when `item.package_contents` is non-empty, emit one `Game` per sub-item (`Game(name=content.title, ids=content.ids, group=GameGroup(id=item.slug, name=item.title))`) instead of one `Game` for the package. Empty `package_contents` keeps today's single-`Game` behavior unchanged (Dead-Cells-style flat bundles need no group). `seen_ids` dedup already operates on ids, so it keeps working unchanged across the expanded list.

## Phase 3 — humblebundle: compound-title detection + ITAD delegation

- `sources/humblebundle/resolver.py`: new `is_compound_title(title: str) -> bool` — conservative pattern match: literal `" + "` separator, or `\bDLC\b`, `\bGame of the Year\b`, `\bGOTY\b`, `\bDefinitive Edition\b`, `\bComplete Edition\b` (word-boundary-anchored to avoid false positives on titles that merely contain "edition" as a substring).
- Two-tier resolution when `is_compound_title` is true:
  1. **Splittable case** (`"A + B"`): split on `" + "` and run each half through the *existing* exact-title-match storefront search loop (`resolve_item`, L208-245) independently — no new ITAD dependency needed for this common case (covers Dead Cells + Bad Seed).
  2. **Non-splittable case** (e.g. "Frostpunk: Game of the Year Edition" — no separable substring): delegate to ITAD's package-content resolution from Phase 2. **Gap confirmed**: `sources/isthereanydeal/` has no title→slug search today — only slug→detail (`resolve_game`); `search.py` confirms `"isthereanydeal"` in its provider list only does marker-based resolution, no title search. This tier therefore needs a new ITAD title-search step (new, small function — e.g. hitting ITAD's site search/autocomplete) before it can look up package contents by title. Build this only if case 2 titles are actually encountered in practice; if it proves rare, an acceptable interim fallback is emitting `unresolved:source:humblebundle:<machine_name>` for non-splittable compound titles so a human resolves them via the existing candidate-chooser/manual-review flow, deferring automatic ITAD delegation to a follow-up.
- `sources/humblebundle/models.py`: add `HumbleSubResolution(StrictModel)` — `name`, `ids: list[NonEmptyString]`. Extend `HumbleResolution` with `sub_resolutions: list[HumbleSubResolution] = Field(default_factory=list)` alongside the existing flat `ids`/`unresolved_stores` (empty = today's flat behavior, no archive migration needed).
- `sources/humblebundle/crawler.py` `write_humble_offer` (L247-352): at both `Game(...)` call sites (L274, L312), branch on `item.resolution.sub_resolutions` non-empty → emit one `Game` per sub-resolution with `group=GameGroup(id=item.machine_name, name=item.title)`; else unchanged single-`Game` path.
- `config/humblebundle-store-ids.yml` / `HumbleResolutionMap` (resolver.py L60-81): currently flat `machine_name -> list[ids]`. Needs to support multiple named sub-games per machine_name for manually-reviewed compound entries — extend the value shape to a union (flat `list[ids]`, or `list[{name, ids}]`) and update `load_resolution_map`/`render_resolution_map` + `validate_ids` accordingly. Treat existing flat entries as zero-sub-resolution (backward compatible, no rewrite of the existing file required).

## Phase 4 — skip/prefer logic rework (`isthereanydeal/crawler.py` L376-419, 436-442)

Replace the binary skip with a targeted merge:

- When `_existing_choice_match`/`_existing_list_match` finds a matching dedicated-scraper list file, load its `GameList` and correlate its `Game` entries to this ITAD offer's items by `normalized_title` (`sources/storefronts.py:normalized_title`, already used for Humble's exact-match search — reuse for consistency), comparing against the ITAD package item's own (compound) title.
- **Safe-replacement test** — only replace an existing `Game` when either: (a) its `ids` contains an `unresolved:` marker, or (b) its normalized `name` exactly matches the ITAD package's compound title *and* ITAD found a resolvable `package_contents` expansion (N>1) for it. Never touch an entry with fully-resolved concrete ids that doesn't match this — that's a strong signal of manual curation.
- **Write behavior**: replace only the matched `Game`(s) in place within the existing file's `games` list (list `name`/`tier`/`references`/other games untouched), re-serialize via `render_game_list_yaml`, re-validate via `GameList` before writing. Log every replacement explicitly (e.g. `"Upgraded <path>: '<old name>' -> N package game(s)"`) so it's visible in scrape output and reviewable before commit.
- Anything not meeting the safe-replacement test keeps today's skip-and-archive-only behavior.

## Phase 5 — schema regen + tests

Regenerate: `schemas/game-list.schema.json` (Phase 1), `schemas/humblebundle-archive.schema.json` (Phase 3 models), `schemas/isthereanydeal-archive.schema.json` and, if `ItadGameArchive` needs a mirrored `package_contents` field for later `complete --provider isthereanydeal` use, `schemas/isthereanydeal-game-archive.schema.json`. `dailyindiegame`/`greenmangaming` archive schemas are unaffected — no model changes there.

New/updated tests (fixtures under `tests/fixtures/`):
- `test_models.py` (or wherever `Game`/`GameList` are tested): `group.id`-name-consistency validator, matching and mismatching cases.
- `test_isthereanydeal_parser.py`: synthetic GOTY-style detail-page fixture with package contents; assert extraction.
- `test_isthereanydeal_resolver.py`: `resolve_game` recursively resolving package contents into ids/sub-items; unresolved-sub-item fallback marker format.
- `test_isthereanydeal_crawler.py`: package bundle → N Games sharing one `group`; flat Dead-Cells-style bundle → no `group` (regression guard); Phase 4 merge — existing `unresolved:` entry gets upgraded in place, unrelated entries in the same file untouched, fully-resolved entries never touched.
- `test_humblebundle_resolver.py`: `is_compound_title` true/false table, including a negative case for a title that merely contains "edition" as a substring without being a real compound offer.
- `test_humblebundle_crawler.py`: splittable compound-title fixture (Dead-Cells-style) → 2 Games sharing one `group`.

## Explicitly out of scope

- **Steam bundle pages as their own storefront source**: Steam bundle ids (e.g. bundle 12261 for Frostpunk GOTY) are never stored as `Game.ids` in this plan — they aren't individually ownable, so a compound offer always expands to its *contained* appids instead. A standalone Steam-bundle scraper (treating Steam bundle pages — which appear under at least two URL shapes, `store.steampowered.com/bundle/<id>/...` and `store.steampowered.com/sub/<id>/...` — as their own bundle source, collectable like Humble/GMG/ITAD bundles) would be a reasonable future addition, but is a separate, larger effort (new source module under `sources/steam/` or similar, plus launcher-neutral bundle discovery) and out of scope here. Note for that future effort: ITAD already tracks the reverse relationship (which bundles a given game appears in — e.g. a game's `/game/<slug>/info/` page lists every bundle it was ever part of, potentially dozens), which could be a useful cross-check/seed list rather than crawling Steam bundle pages cold. For now, when Humble/ITAD resolution surfaces a Steam bundle URL for a compound title, treat it only as a *hint/cross-check* that the title is indeed a package (useful for `is_compound_title`-style heuristics or manual review), not as a resolution target.
- **greenmangaming, dailyindiegame**: no evidence gathered that they host compound/package offers; defer until proven needed. GreenManGaming's title-search resolver could reuse the same `is_compound_title`/split heuristic later if it comes up.
- **`isthereanydeal-game-aliases.yml` / `resolve_game_with_aliases`**: untouched — that mechanism is cross-platform slug aliasing for the *same* real game, orthogonal to package-content expansion for *different* bundled games.
- **Retroactive backfill** of `group`/`package_contents` onto already-written archives/lists — this plan covers new crawls only; a backfill would be a separate one-off script (pattern: `scripts/backfill_humble_choice.py`) if wanted later.
- **ITAD title-search infrastructure** (Phase 3, tier 2) is scoped as "build only if non-splittable compound titles are actually encountered" — the interim fallback is a manual-review `unresolved:` marker, not a hard blocker for the rest of this plan.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest` — full suite, including new fixtures above.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` — confirms real `lists/**/*.yml` still validate against the updated schema (including any list files touched by a manual Phase-4 merge test run against real data, if exercised).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema` then `git diff schemas/` — confirm only the expected schema files changed, and `tests/test_schema.py` passes (no drift).
- Manual dry-run: `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape isthereanydeal --refresh` against a known GOTY-style bundle (once Phase 2 is live) and inspect the written list for correct `group`-linked entries; similarly `scrape humblebundle --refresh` against a known "A + B" compound offer for Phase 3's split path.
