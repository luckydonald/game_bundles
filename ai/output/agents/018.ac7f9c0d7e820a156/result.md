I don't have write access to create the plan file (no Write tool is available in this subagent's toolset), so I'm delivering the plan directly as my final answer, per my task instructions.

# Implementation Plan: Compound-Offer / Package-Content Expansion

## Phase 1 — `src/game_collections/models.py` (public schema)

Add a new nested model and field:

```python
class GameGroup(StrictModel):
    """Provenance link for Games that came from splitting one compound source offer."""
    id: NonEmptyString
    name: NonEmptyString
# end class GameGroup

class Game(StrictModel):
    name: NonEmptyString
    ids: list[NonEmptyString] = Field(min_length=1)
    group: GameGroup | None = None
    ...
```

- `group.id`: locally-scoped label, not globally unique — derive deterministically from the source (e.g. Humble `machine_name` of the compound item, or ITAD package `slug`), so re-crawls are idempotent/stable. Do NOT require cross-offer uniqueness; scope it to "games that trace back to one write" only. Document this explicitly in the field docstring since `GameList.validate_games` will need list-scoped (not repo-scoped) checks only.
- `group.name`: the original compound title verbatim (e.g. "Frostpunk: Game of the Year Edition"), for human traceability — never used for ownership logic.
- **`evaluate_completion`/`SteamAdapter.evaluate` unchanged**: `group` is inert metadata; each `Game.ids` list still independently drives OR-ownership per Game. No changes needed in `completion.py` or `launchers/steam/adapter.py`.
- **New validator in `GameList.validate_games`** (`models.py`): within one list, all `Game`s sharing the same `group.id` must have identical `group.name` (`raise ValueError(f"games in group {group.id!r} have inconsistent group names")`). This is a cheap consistency guard against copy-paste drift when hand-editing. Do not enforce uniqueness of `group.id` across files/lists — same real-world offer could legitimately be represented once (no cross-list registry today, confirmed in `lists.py`).
- Existing dup checks (`names` casefold dedup, `identities` dedup) are unaffected and still correctly prevent group-expansion from producing literal duplicate Games.

## Phase 2 — isthereanydeal: package-content detection

**`src/game_collections/sources/isthereanydeal/models.py`**
- Add `ItadPackageContent(StrictModel)`: `slug: NonEmptyString`, `title: NonEmptyString`, `ids: list[NonEmptyString] = Field(min_length=1)` (mirrors `ItadItem` shape but explicitly namespaced for sub-items, to keep the "is this a bundle-tier item or a package sub-item" distinction visible in the archive).
- Extend `ItadItem` with `package_contents: list[ItadPackageContent] = Field(default_factory=list)` (empty = flat/non-package item, e.g. Dead Cells+Bad Seed stays flat since ITAD already lists it as independent flat items per your stated fact).

**`src/game_collections/sources/isthereanydeal/parser.py`**
- Extend `parse_game_detail_json` (L535-580) to also look for package contents in `payload` (need a live fetch of a known GOTY-style detail page to confirm the exact JSON key — I could not verify this against a live network fetch in this read-only session; flag as **open risk #1** below). Design assuming a `payload["game"]["package_contents"]` or similar list of `{slug, title}` dicts is present (matching the site's "Contents of this package" UI section); if it turns out only rendered in HTML with no JSON backing, add a BeautifulSoup fallback parser `parse_game_detail_package_contents(html) -> list[tuple[slug, title]]` next to the existing `parse_bundle_detail_page` HTML-walking pattern (L583+) for consistency.
- New function `resolve_package_contents(detail_payload) -> list[tuple[str, str]]` (slug, title pairs) kept separate from `parse_game_detail_json` so it stays independently testable with a synthetic fixture even before the exact real JSON shape is confirmed.

**`src/game_collections/sources/isthereanydeal/resolver.py`**
- Extend `resolve_game` (L73-110): after parsing `detail`, if `detail.payload` carries package contents, for each sub-item call `resolve_game(sub_slug, ...)` recursively (bounded depth — packages should not nest further; assert/log if they do) to get each sub-item's own resolved `ids` via its own `/game/<slug>/info/` page — reusing the exact same fetch/deals/redirect machinery already used for top-level game resolution (per your fact confirming ITAD's own sub-item pages resolve through the same `itad.link` redirect mechanism).
- On a sub-item resolution failure, fall back to `unresolved:source:isthereanydeal:<bundle_id>:<sub_slug>` — **reuse the existing marker format as-is** (`UNRESOLVED_PREFIX` + `_UNRESOLVED_PATTERN` in resolver.py L18-19, format `unresolved:source:isthereanydeal:<bundle_id>:<slug>`). This already works generically for any slug, not just top-level bundle-tier slugs, so `complete --provider isthereanydeal`'s existing `resolve_isthereanydeal_markers` (L142-161) needs **no changes** to pick these up later — confirmed by reading `parse_unresolved_marker`/`resolve_isthereanydeal_markers`.

**Where the fetch happens**: `crawl_itad_offers` (crawler.py L296-371) currently never visits `/game/<slug>/info/` during a bundle crawl — only `parse_bundle_detail_json`/`parse_bundle_detail_page` off the bundle page. Two design options:
- **(a) Always fetch** each `ItadItem`'s own detail page during bundle crawl, to check `package_contents`. Simpler, uniform, matches "archives already cache/resume" reasoning in your prompt — recommend this as the default given `archive_root` caching already exists (`_archive_paths`/`load_cached_archive`, crawler.py) and per-item archives are separately cacheable via `write_itad_game_archive` (resolver.py). Cost: N extra HTTP fetches per bundle (was 1 fetch/bundle, becomes 1 + item_count).
- **(b) Heuristic-gated fetch** only when title matches package patterns (`"Game of the Year"`, `"Definitive Edition"`, `"Complete Edition"`, `" + "`, `"Bundle"` in the *item* title, case-insensitive) — cheaper but risks false negatives (a GOTY edition without package contents costs one wasted fetch; a package without a matching title pattern silently stays unexpanded).
- **Recommendation**: (a), gated behind a per-item archive cache (`archives/isthereanydeal/game/<slug>/...`, already written by `write_itad_game_archive`) so re-crawls are cheap after the first pass — this reuses existing infrastructure rather than adding a second heuristic surface to maintain.

**`src/game_collections/sources/isthereanydeal/crawler.py`** `write_itad_offer` (L444-522)
- Where it currently does `pool_games.append(Game(name=item.title, ids=item.ids))` / the per-tier equivalent, branch: if `item.package_contents` is non-empty, emit one `Game` per sub-item (`Game(name=content.title, ids=content.ids, group=GameGroup(id=item.slug, name=item.title))`) instead of one `Game` for the package item itself. If empty, keep current single-`Game` behavior unchanged (Dead-Cells-style flat multi-item bundles are already correct without any group).
- Keep `seen_ids` dedup logic working across sub-item-expanded ids too (already id-based, not item-based, so no change needed there beyond iterating the expanded list).

## Phase 3 — humblebundle: compound-title detection + ITAD delegation

**`src/game_collections/sources/humblebundle/resolver.py`**
- New pure function `is_compound_title(title: str) -> bool`: conservative regex/keyword heuristic — matches literal `" + "` separator, or trailing `"DLC"`, `"Game of the Year"`, `"GOTY"`, `"Definitive Edition"`, `"Complete Edition"` as a suffix pattern (avoid over-matching legitimate single-word titles containing "edition" as a substring — anchor patterns to word boundaries and known suffix positions, e.g. compile as `re.compile(r"(?i)\s\+\s|\bDLC\b|\bGame of the Year\b|\bGOTY\b|\bDefinitive Edition\b|\bComplete Edition\b")`).
- New `resolve_item` branch: when `is_compound_title(item.title)` is true, delegate to a new function `resolve_via_itad(item, itad_client) -> list[HumbleSubResolution]` instead of the existing per-store exact-title search loop. This calls into `sources/isthereanydeal/resolver.py`'s `resolve_game` machinery — **but note the confirmed gap**: ITAD's resolver only has slug→detail (`resolve_game`), no title→slug search function today. Search-by-title on ITAD would need either (i) a new function using ITAD's site search/autocomplete endpoint (not currently modeled anywhere — genuinely new surface), or (ii) reusing `search.py`'s existing cross-storefront ranked search (`src/game_collections/search.py`) if it already covers ITAD as a provider (need to check `search.py`'s provider list — **not verified in this session, open risk #2** below).
- **Simplify recommendation**: rather than building ITAD title-search from scratch, prefer having the Humble resolver directly reuse the *same conservative compound-splitting heuristic output* to attempt per-substring exact-match storefront search first (e.g. split "Dead Cells + The Bad Seed DLC" on `" + "` into ["Dead Cells", "The Bad Seed DLC"] and run each half through the *existing* `resolve_item` exact-match loop) — this avoids the new ITAD-search dependency entirely for the common `"A + B"` case, and only fall back to ITAD delegation (once that search capability exists) for titles that don't split cleanly (e.g. "Frostpunk: Game of the Year Edition", which has no separable substring — this case fundamentally needs ITAD's package-content data, not a title split). Flag this fallback-tiering explicitly to the user as a design choice trade-off.

**`src/game_collections/sources/humblebundle/models.py`**
- Add `HumbleSubResolution(StrictModel)`: `name: NonEmptyString`, `ids: list[NonEmptyString] = Field(min_length=1)`.
- Extend `HumbleResolution`: add `sub_resolutions: list[HumbleSubResolution] = Field(default_factory=list)` alongside existing flat `ids`/`unresolved_stores` (keep both — empty `sub_resolutions` means "flat/single game," matching today's 100% of existing data, so this is backward compatible for archive schema regen purposes and requires no migration of existing archives).

**`src/game_collections/sources/humblebundle/crawler.py`** `write_humble_offer` (L247-352)
- At both `Game(name=item.title, ids=item.resolution.ids)` call sites (L274 choice-pool, L312 bundle-tier), branch: if `item.resolution.sub_resolutions` non-empty, emit one `Game` per sub-resolution with `group=GameGroup(id=item.machine_name, name=item.title)`; else keep the current single-`Game` path.

**Resolution map** (`config/humblebundle-store-ids.yml`, `HumbleResolutionMap`, resolver.py L60-81): currently `dict[machine_name, list[ids]]` (flat). For compound items this needs to become able to hold multiple named sub-games per machine_name. Either (i) extend the value type to a discriminated union (flat `list[ids]` vs. `list[{name, ids}]`), which is a breaking change to the reviewed YAML config's shape requiring `load_resolution_map`/`render_resolution_map` updates and a migration note in `config/README` (does it exist? not checked) or CLAUDE.md; or (ii) keep the map's on-disk key granularity at machine_name but store a JSON-ish nested value — recommend (i) since it's a small, self-contained reviewed file (not a runtime schema in `schemas/`), and the existing `HumbleResolutionMap.validate_ids` model-validator can be extended to validate each shape.

## Phase 4 — skip/prefer logic rework (`isthereanydeal/crawler.py` L376-419, 436-442)

- Today: `_existing_choice_match`/`_existing_list_match` cause a **binary skip** of `write_itad_offer`'s list-writing whenever a dedicated-scraper list already exists for the same real offer (matched by month for Humble Choice, or filename substring on `real_slug` generically).
- New design: when a match is found, instead of skipping outright, **load and inspect** the existing `GameList` (via `lists.py`'s loader) for the matched file(s):
  - Correlate specific existing `Game` entries to this ITAD offer's items by `normalized_title` (`sources/storefronts.py:normalized_title`, already used for Humble's exact-match search — reuse directly for consistency) comparing existing `Game.name` against each `ItadItem.title` (and, for expanded packages, against the package item's original title, not the sub-item titles, since the existing list would only have the compound title as one entry).
  - **"More detailed" test**: an existing `Game` is a *safe replacement candidate* only if (a) its `ids` list contains any `unresolved:` marker, OR (b) its `name` (casefolded/normalized) exactly matches the ITAD package item's compound title AND the ITAD side has `package_contents` expansion available (i.e., ITAD found N>1 resolvable sub-items vs. the existing single unresolved/flat entry). Never touch an existing `Game` whose ids are already fully resolved concrete ids that don't overlap the ITAD data — that's a strong signal of manual curation, not staleness.
  - **Merge write behavior**: replace just the matched `Game` entries in-place within the existing `GameList.games` list (same file, same list `name`/`tier`/`references`/other games untouched), re-serialize via the same `render_game_list_yaml` used elsewhere, re-validate with `GameList.model_validate`/`validate_games` before writing (catches accidental new duplicate ids/names).
  - Log every replacement explicitly (`log(f"  Upgraded {existing_path}: {old.name!r} -> {len(new_games)} package game(s)")`) so it's visible in `scrape` output diffs and reviewable before commit — never silent.
  - **Explicitly out of scope for auto-merge**: any existing `Game` without an `unresolved:` marker and without an exact compound-title match — always skip-preserve those, matching current conservative behavior, to avoid clobbering manual edits (this directly answers your "safe merge strategy" ask).

## Phase 5 — schema regen + tests

**Regenerate** (`uv run game-collections schema`, or equivalent internal generator — check `cli.py`'s `schema` command target list): 
- `schemas/game-list.schema.json` (public `Game.group`/`GameGroup` addition — required, drift-checked by `tests/test_schema.py`)
- `schemas/humblebundle-archive.schema.json` (new `HumbleSubResolution`, `HumbleResolution.sub_resolutions`)
- `schemas/isthereanydeal-archive.schema.json` (new `ItadPackageContent`, `ItadItem.package_contents`)
- `schemas/isthereanydeal-game-archive.schema.json` — check if `ItadGameArchive` (resolver.py) also needs a `package_contents` field mirrored onto the per-game archive record for `complete --provider isthereanydeal` to pick up later; if so, regen this too.
- `dailyindiegame`/`greenmangaming` archive schemas: **unaffected**, no model changes proposed there (see out-of-scope below).

**New test fixtures/cases**:
- `tests/test_isthereanydeal_parser.py`: synthetic "Frostpunk GOTY" detail-page fixture (`fixtures/isthereanydeal/...`) with package_contents present; assert `parse_game_detail_json`/new parser function extracts both sub-items correctly.
- `tests/test_isthereanydeal_resolver.py`: assert `resolve_game` recursively resolves package contents into `ids`/sub-items, and produces `unresolved:source:isthereanydeal:<bundle_id>:<slug>` on a sub-item fetch failure, verified against `parse_unresolved_marker`.
- `tests/test_isthereanydeal_crawler.py`: `write_itad_offer` case for a package-content bundle asserting N `Game`s share one `group.id`/`group.name`; and a flat Dead-Cells-style bundle asserting **no** `group` is added (regression guard).
- `tests/test_isthereanydeal_crawler.py`: new case for Phase 4's skip-vs-merge logic — existing list with an `unresolved:` marker entry gets upgraded in place, unrelated entries in the same file untouched; existing fully-resolved entry is never touched.
- `tests/test_humblebundle_resolver.py`: `is_compound_title` true/false table (including negative cases: single-word titles with "edition" substring that shouldn't false-positive — need to pick a real example, e.g. a game literally named "The Edition" would be an edge case worth a test even if synthetic).
- `tests/test_humblebundle_crawler.py`: compound-title Humble offer fixture (Dead Cells + Bad Seed-style, splittable) producing 2 `Game`s sharing one `group`.
- `tests/test_models.py` (or wherever `Game`/`GameList` validators are tested): new cases for the `group.id`-name-consistency validator (matching + mismatching names within one group.id → error).

## Explicitly out of scope

- **greenmangaming, dailyindiegame**: defer package-content detection there. GreenManGaming resolves off free-text DRM labels via title search similar to Humble (per CLAUDE.md), so the same compound-title heuristic *could* apply later, but no evidence was gathered in this session that GMG or DailyIndieGame actually host compound/package offers — treat as a follow-up once this Humble+ITAD path is proven. No model/schema changes proposed for either in this plan.
- **`isthereanydeal-game-aliases.yml`/`resolve_game_with_aliases`**: intentionally untouched — cross-platform slug aliasing for the *same* real game is orthogonal to package-content expansion for *different* real games bundled together; do not conflate the two mechanisms.
- **Migrating/backfilling existing archived offers** retroactively to add `group`/`package_contents` to already-written lists is not designed here — only new crawls going forward. If backfill is wanted later it would be a separate `scripts/` one-off similar to `scripts/backfill_humble_choice.py`.

## Open risks / ambiguities for the coordinator to confirm with the user

1. **Unverified live JSON shape**: I could not fetch a live ITAD `/game/<slug>/info/` page for a known package item (e.g. Frostpunk GOTY) in this read-only session to confirm the exact `payload` key holding package contents. The parser design above is a best-guess structure matching the site's existing JSON-embedding pattern (`var page = ["Game", {...}]`) but needs live-page verification before implementation — recommend the implementing agent do a one-off `curl`/fetch of a real GOTY-style ITAD game page first.
2. **No confirmed title→slug search on ITAD**: `sources/isthereanydeal/` only has slug→detail resolution (`resolve_game`) today; whether `search.py`'s existing cross-storefront search already covers ITAD as a queryable provider was not verified in this session — needs a quick grep of `search.py`'s provider list before deciding whether Phase 3's ITAD-delegation fallback needs new search infrastructure or can reuse existing code.
3. **Humble resolution-map schema migration**: changing `config/humblebundle-store-ids.yml`'s value shape from flat `list[str]` to a union type is a breaking format change to a hand-maintained reviewed file — decide whether to keep backward-compat parsing (old flat entries treated as zero-sub-resolution) or require one-time manual migration; not fully resolved in this plan.
4. **Cost of Phase 2's "always fetch"**: adds one HTTP fetch per bundle item during every ITAD bundle crawl (previously zero beyond the bundle page itself) — worth confirming with the user whether this fetch volume is acceptable for the scheduled GitHub Actions scrape cadence mentioned in CLAUDE.md, or whether the heuristic-gated variant (option b) should be preferred despite its false-negative risk.

### Critical Files for Implementation
- /home/user/git/luckydonald/game_collections/src/game_collections/models.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/parser.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/resolver.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/crawler.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/resolver.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/crawler.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/humblebundle/models.py
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/isthereanydeal/models.py