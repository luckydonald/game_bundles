# Confidence-scored bundle dates, generic version-envelope migrations, and fuzzy dedup

## Context

Fixing DekuDeals' list filename date-prefix bug exposed two structural gaps:

1. **Dedup can silently miss the same real-world bundle.** `existing_list_match` (`sources/common.py`) only does a plain substring match, so DekuDeals' own slug `crawling-through-the-dungeons` never matched the dedicated Humble scraper's real slug `crawling-through-dungeons` — DekuDeals would have kept a *second*, separately-dated list file for the same bundle.
2. **Date retrieval is real-but-uneven across sources, and nothing records how sure we are.** `crawled_at` (renamed from `crawled`) is always `datetime.now(UTC)` — that part really is a plain "when did we look at this," by design. But `start`/`end` come from a real page/API field on some sources and are either missing or computed/estimated on others, and two live bugs surfaced during this investigation:
   - DekuDeals' `start` (already fixed) is only readable in discovery mode from the bundles-index page's `created_at`; an explicit `--url` crawl or an older archive has it as `None`.
   - **GreenManGaming's `end` is dead code**: the bundles-index page's `data-end-date="YYYY-MM-DDTHH:MM"` attribute is present in the parser's own test fixture (`tests/test_greenmangaming_parser.py:17,26`) but never captured by `_ProductCardParser`, and `parse_bundle_page` hardcodes `GmgDates(end=None, ...)` (`greenmangaming/parser.py:274`) despite `GmgDates`'s own docstring describing exactly that field.
   - DailyIndieGame's `end` is *computed* (`crawled + parsed "ends in Xd:Xh:Xm:Xs"` countdown, `dailyindiegame/parser.py:213-219`) — real data, but an estimate, not a fixed timestamp.

A plain `datetime | None` can't express "how sure are we, and where did this come from," which is exactly what's needed to decide whether a corrected value should ever replace what's already on disk, and whether a list file's date-prefixed name needs correcting. This plan adds a confidence-scored timestamp type, a generic version-envelope + migration-runner so every archive/source file can carry that new shape (and any future shape) without hand-rolled per-file schema bumps, and the fuzzy/content-aware dedup improvement — with migrations auto-applied to touched files before every write and grouped into a small number of clean commits, never a dedicated "run this migration" step per file.

## Live-verified: DekuDeals bundles-index shape

Fetched `https://www.dekudeals.com/bundles` directly and parsed its `data-page` JSON. `props.bundles[i]` (31 entries live) has this full shape — everything below is confirmed, nothing guessed:

```json
{
  "created_at": 1789045237,             // unix ts - already used as `start`
  "created_at_formatted": null,          // human string, often null - not modeled
  "ends_at": 1792047600,                 // unix ts - the index ALSO carries `end`, same field the detail page exposes
  "ends_at_formatted": "Ends October 15",
  "ends_at_label": "Ends Oct 15, 2026",
  "image": "https://cdn.dekudeals.com/...",
  "name": "Build your own Special Editions Bundle (Fall 2026)",
  "price": 699, "price_formatted": "€6,99",
  "size": 22,
  "slug": "build-your-own-special-editions-bundle-fall-2026",
  "store": "fanatical_us",
  "tiering_style": "price_per_item",
  "top_items": [ { "name": ..., "platform": "steam", "hotness": 1.61, "horizontal_image": {...}, "vertical_image": {...} }, ... ]
}
```

`DekuIndexEntry` (`dekudeals/parser.py`) currently only keeps `slug`/`created_at`. Expand it to also keep `name`, `store`, `tiering_style`, `price`/`price_formatted`, `size`, `ends_at`, `ends_at_label` — every field with a stable, typed meaning. `image`/`top_items`/`created_at_formatted`/`ends_at_formatted` are decorative/redundant; leave them unmodeled but note in the dataclass docstring that they're known-and-skipped (matching this project's existing "known field, intentionally unmodeled" convention), not silently dropped without acknowledgement. `ends_at` here means discovery mode can now also cross-check `end` the same way it already supplies `start`, at the same 1.0 confidence as the detail page (see confidence table).

## Confidence table (per source, per field)

| Source | field | how it's derived | confidence |
|---|---|---|---|
| Humble | `start` | bundle detail page `start_date\|datetime` / Choice `validFrom` — real field | **1.0** |
| Humble | `end` | bundle detail page `end_date\|datetime`/`end_time\|datetime` / Choice `validThrough` — real field | **1.0** |
| isthereanydeal | `start` | discovery-list API `summary.start` (unix ts) — real field | **1.0** |
| isthereanydeal | `end`/`expiry` | discovery-list API `summary.expiry` (unix ts) — real field | **1.0** |
| DekuDeals | `start` | bundles-index page `created_at` — real field, only present in discovery mode | **1.0** when present, else `None` |
| DekuDeals | `end` | bundle detail page `ends_at` (also cross-checkable against the index's own `ends_at`) | **1.0** when present, else `None` |
| GreenManGaming | `start` | no known source | `None` (left unset, not fabricated) |
| GreenManGaming | `end` | bundles-index page `data-end-date` (date+time, **no explicit tz** — assumed UTC, unconfirmed against the server) — parsed in the fixture today but **not wired**; this plan wires it | **0.7** (real value, timezone assumption unverified) |
| DailyIndieGame | `start` | no known source | `None` |
| DailyIndieGame | `end` | computed: `crawled_at + parsed countdown` — real countdown text, but a derived, second-precision-drifting estimate | **0.5** |

Legacy (pre-migration) values get confidence **0.0** unconditionally — we never tracked confidence before, so every existing value is "unverified," never assumed to have been a real 1.0. That makes the replace rule below unambiguous: any freshly-derived real value always beats a `0.0` legacy one.

## 1. `ScrapedTimestamp` — new shared model, `game_collections/sources/timestamps.py`

```python
class ScrapedTimestamp(StrictModel):
    iso: NonEmptyString      # original precision preserved: "YYYY-MM-DD", or with time/ms/offset
    timestamp: float         # unix epoch seconds, cross-checked against `iso`
    confidence: float = Field(ge=0.0, le=1.0)
    source: NonEmptyString   # crawler name: "humblebundle" | "greenmangaming" | "dailyindiegame" | "isthereanydeal" | "dekudeals"
```
- `model_validator(mode="after")` parses `iso` (date-only / date+time / date+time+fraction / date+time+offset) and confirms it's consistent with `timestamp`; a naive time-of-day `iso` (no explicit offset) is only allowed when it's the date-only case.
- `build_scraped_timestamp(value: datetime, source: str, confidence: float) -> ScrapedTimestamp` — convenience constructor preserving `value`'s own precision in `iso`.
- `merge_scraped_timestamp(existing: ScrapedTimestamp | None, fresh: ScrapedTimestamp | None) -> tuple[ScrapedTimestamp | None, ConflictReport | None]`:
  1. `fresh is None` → keep `existing`, no report.
  2. `existing is None` → adopt `fresh`, no report.
  3. `existing.confidence == 0.0` → adopt `fresh` unconditionally; if the value actually changed, return an **info** report (old → new) for the end-of-run summary — not a conflict, just visibility.
  4. `existing.confidence == fresh.confidence == 1.0` and both represent the same moment (within tolerance) → keep whichever `iso` encodes more precision (date+time+offset > date+time+ms > date+time > date-only); no report.
  5. Otherwise (real disagreement) → **interactive TTY**: prompt with both candidates (value, confidence, source, plus every URL on record for the bundle) and let you pick; **non-interactive** (no TTY, or `--git`/CI runs): keep the chronologically **older** value automatically and log it. Either way, the end-of-run summary gets a line like:

     ```
     CONFLICT crawling-through-the-dungeons.start:
       existing (older): 2026-09-08T00:00:00Z (confidence 1.0, source=dekudeals)
       fresh    (newer): 2026-09-09T18:10:21Z (confidence 1.0, source=humblebundle)
       kept: existing (older) — resolve by hand if wrong
       urls: https://dekudeals.com/bundles/... , https://humblebundle.com/...
     ```

## 2. Generic version envelope — new `game_collections/versioning.py`

Every on-disk `metadata.json` **and** `source.json` (currently `source.json` has no version field at all) gets wrapped the same way, replacing each source's old embedded `schema_version: Literal[N] = Field(alias="schema", ...)`:

```python
class SchemaDateVersion(NamedTuple):
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    fraction: float  # sub-second, 0.0 if unspecified

class Versioned[VERSION, DATA](BaseModel):
    version: VERSION
    data: DATA

DateVersioned = Versioned[SchemaDateVersion, DATA]  # generic alias, DATA bound per use
```

(`Literal[...]` technically accepts tuple *values* as parameters, but every new version would then have to be added to a growing `Literal[(2026,9,11,...), (2026,9,12,...), ...]` union just to type-check — unworkable for a value that's meant to be bumped freely by hand. `version: SchemaDateVersion` as a plain (non-`Literal`) field sidesteps that entirely: any tuple of the right shape is valid, and "is this current" is answered by comparing against each source's own `CURRENT_VERSION` constant, not by the type system.)

Each source declares, next to its Archive model, a hand-bumped constant and a concrete alias, e.g. in `dekudeals/models.py`:

```python
CURRENT_VERSION = SchemaDateVersion(2026, 9, 11, 14, 30, 0, 0.0)  # bump to "now" on every edit to this file
VersionedDekuArchive = DateVersioned[DekuArchive]
```

`DekuArchive` itself drops its `schema_version`/`schema`-alias field entirely — versioning now lives only in the envelope. On disk:
```json
{"version": [2026, 9, 11, 14, 30, 0, 0.0], "data": {"machine_name": "...", "url": "...", ...}}
```
Same wrapper is used for `source.json` (`Versioned[SchemaDateVersion, dict]`, since it's a raw untyped dump — versioned mainly so a future shape change to what we *capture* as source data can still be migrated instead of just discarded).

**Reading**: peek `version` cheaply (a tiny `_VersionPeek(BaseModel)` with `model_config = ConfigDict(extra="ignore")`, just the `version` field) before attempting full validation, since older raw data won't validate against the current `DATA` model. If `version < CURRENT_VERSION`, migrate the raw `data` dict first (§3), then validate. `load_cached_archive` (`sources/common.py`) is updated to this two-step peek→migrate→validate flow; its external return shape (`(ArchiveT, source_dict)`) is unchanged for callers.

*Implementation note to verify early*: confirm the installed Pydantic version supports PEP 695 `class Versioned[VERSION, DATA](BaseModel)` generics directly (Pydantic ≥2.11 does); fall back to classic `Generic[VERSION, DATA]` syntax if not.

## 3. Migration runner — critique + chosen design

Your own sketch (`if old_version < 2: ...; if data.version < 3: ...`) works but has three real problems: it couples the pure data transform with the commit-grouping side effect inline (hard to dry-run without guarding every step behind a flag), it's not a reusable value-returning function (every future consumer re-copies the same `if` skeleton), and there's no clean return value describing *which* steps actually fired — exactly what's needed to group commits and print the dry-run report.

**Chosen: one ordered step-list per source/file-kind + one shared, pure runner.**

```python
# game_collections/versioning.py
def migrate_to_latest(
    raw: dict, current_version: SchemaDateVersion, steps: list[tuple[SchemaDateVersion, Callable[[dict], dict]]]
) -> tuple[dict, list[SchemaDateVersion]]:
    version = tuple(raw["version"])
    data = raw["data"]
    applied: list[SchemaDateVersion] = []
    for target_version, migrate_fn in steps:
        if version < target_version:
            data = migrate_fn(data)
            version = target_version
            applied.append(target_version)
        # end if
    # end for
    assert version == current_version, "migration steps do not reach the declared current version"
    return {"version": list(version), "data": data}, applied
# end def migrate_to_latest
```
Each source declares its own step list (e.g. `dekudeals/migrations.py`: `MIGRATIONS: list[tuple[SchemaDateVersion, Callable[[dict], dict]]]`), pure dict→dict, no I/O, no git awareness — trivially unit-testable per step. `migrate_to_latest`'s `applied` return value is what the CLI/scrape orchestration layer (not the migration functions) uses to decide commit grouping and dry-run diff output — a clean separation between "what changed" and "how to commit it."

**Two other approaches considered, not chosen:**
2. *One tiny module/class per step, auto-discovered* (mirrors this repo's existing one-file-per-migration convention in `migrations/tiers.py`/`migrations/bundle_variations.py`): each step lives in its own file (`TARGET_VERSION`, `migrate(data)`), collected by scanning a package and sorting by `TARGET_VERSION`. Keeps each bump's diff isolated in its own reviewable file, at the cost of one-file-per-bump ceremony — reasonable if bumps become frequent, unnecessary at today's cadence.
3. *Frozen versioned Pydantic model chain* (`DekuArchiveV1`, `DekuArchiveV2`, ... each with `.upgrade()`): strongest type safety, since every historical shape is itself a validated model, not an assumed-shaped dict — but a permanently growing set of frozen classes forever. Overkill for 5 sources with infrequent bumps.

## 4. Fuzzy + content-similarity dedup — `sources/common.py`

`existing_list_match(lists_root, provider_slug, slug, fresh_games: list[Game] | None = None) -> Path | None`:

- **Exact substring match** (current behavior, unchanged) — e.g. DekuDeals slug `metroidvania-madness` is a substring of the existing `lists/greenmangaming/bundle/2026-06-01_metroidvania-madness.yml` → matched immediately, no content check needed (a substring hit on a real slug is already a strong signal).
- **Fuzzy name match** (new): when no substring hit, and `fresh_games` was passed, score every existing bundle file/directory name in that provider's tree (date-prefix and extension stripped, dashes→spaces) against `slug` via `rapidfuzz.fuzz` (already imported here, same `FUZZY_MATCH_THRESHOLD` convention `find_matching_game` uses). Example: DekuDeals slug `crawling-through-the-dungeons` vs. the real Humble file `2026-09-09_crawling-through-dungeons.yml` → substring check fails both directions, but `fuzz.WRatio("crawling through the dungeons", "crawling through dungeons")` scores well above threshold (differs by one stopword, not a number/edition word) → candidate accepted for the content check below.
- **Content check gate** (new, required before trusting any *fuzzy-only* candidate — never applied to a substring hit): load the candidate's `GameList`(s) and run each of `fresh_games` through the existing `find_matching_game` cascade against its roster; accept the match only if at least half of `fresh_games` resolve. Example (true positive): DekuDeals' resolved roster for `crawling-through-the-dungeons` (Crawl, The Bard's Tale Trilogy, ...) matches nearly 1:1 against the existing Humble list's own games by id → accepted, backfilled. Example (rejected false positive): a fresh `indie-bundle-2026` scored fuzzily similar to an unrelated existing `indie-bundle-2025` file, but their game rosters share zero ids/names → content check fails → treated as a genuinely new bundle, list written normally.
- Both `isthereanydeal/crawler.py` and `dekudeals/crawler.py` pass their already-flattened pool (`_flatten_itad_games`/`_flatten_deku_games`) at their `existing_list_match(...)` call sites.
- New tests: the real `crawling-through-the-dungeons`/`crawling-through-dungeons` true-positive case, and a fuzzy-name/dissimilar-roster false-positive rejection case.

## 5. Wiring `start`/`end`/`crawled_at`/`first_seen` per source

- Rename `crawled` → `crawled_at` in every `*Dates` model (plain `datetime`, unchanged semantics: "last time this was actually crawled," updated on every re-crawl that touches the file).
- Add `first_seen: datetime | None = None` to every `*Dates` model: set once, the first time an archive is ever written for that key, and never overwritten afterward. The v1→v2 migration backfills it from the pre-migration `crawled` value (the only timestamp we have for "when did we first see this"), since that's the closest available proxy — documented as a proxy, not a guess at the true first-seen date.
- `start`/`end` (and ITAD's `expiry`) become `ScrapedTimestamp | None`, built via `build_scraped_timestamp(value, source="<crawler-name>", confidence=<table above>)` at each crawler's construction site.
- **GMG fix included here**: extend `_ProductCardParser`/`parse_bundle_index_page` (`greenmangaming/parser.py`) to also capture `data-end-date` per slug (mirroring the `created_at_by_slug` pattern `dekudeals/crawler.py` already uses), thread it into `crawl_gmg_offers`, and stop hardcoding `GmgDates(end=None, ...)`.
- Regenerate all 5 `schemas/<source>-archive.schema.json` (`tests/test_schema.py` enforces this) plus a schema for the new shared `ScrapedTimestamp`/`Versioned` envelope if `schema.py` renders one standalone.

## 6. Auto-migration wired into every write path (no dedicated migration command needed for scrapers)

`load_cached_archive`/the write helpers in `sources/common.py` migrate a touched file to `CURRENT_VERSION` *in place, before* writing fresh crawl data to it — never a separate manual step. The `--git` scrape flow (`git_ops.py`, already exposes `commit_changed_paths` as a standalone reusable call, not just inside `finish_scrape_git_session`) is extended so one `scrape --git <source>` run produces:
1. Zero or more **schema-migration commits**, one per distinct version step actually applied across this run's touched files (not per file, not batched by 100 — see §7) — e.g. 10 files spanning v1→v2→v3 becomes exactly 2 migration commits, not 10 or 20.
2. Exactly one final **crawl-content commit** with the run's own new/updated data, via the existing `finish_scrape_git_session` call, unchanged in shape.

## 7. Standalone `migrate schema` CLI command (for migrating without crawling)

New subcommand under the existing `migrate` Typer group (alongside `tiers`/`bundle-variations`), for running all outstanding migrations without triggering a crawl:

- `--path` (repeatable): a directory (recursed) or a single file to restrict the scan to; no `--path` at all means the whole repo.
- `--type` (repeatable, AND'd): `metadata` | `source` | `bundle` — which file kind(s) to touch. `bundle` (the `lists/**/*.yml` GameList files) has no pending migration yet in this plan but the filter and the underlying engine are file-kind-agnostic, so it's wired now for whenever a `GameList` schema bump happens.
- `--git`/`--git-style`: identical flag shape to `scrape`'s group-level callback, reusing `git_ops.begin_scrape_git_session`/`commit_changed_paths`/`finish_scrape_git_session`.
- **Default (dry-run)**: prints every pending change grouped by the commit it would become — each schema-migration step's file list plus a diff-style before/after of the fields that changed, then (if any) the batched rename groups from a rename pass equivalent to §8 below.
- `--apply`: performs the writes/renames and (with `--git`) commits them following the same commit-shape rules as §6/§8.

## 8. Commit shape rules

- **Schema-migration commits**: one commit per version step actually applied (not batched by file count — these are cheap, mechanical dict transforms even if they touch many files), message subject exactly:
  `[lists] metadata: Migrating v1 → v2.` (adjust the bracketed scope/file-kind to whatever's actually being migrated, e.g. `[lists] source:` for `source.json`).
- **Rename/content commits** (the actual list-file renames once a corrected `start`/`end` implies a different date prefix): always batched, **max 100 files per commit**, subject prefixed with a zero-padded `(NN/N)` counter, e.g. `(01/03) [lists] dekudeals: Renamed bundle list files to their corrected start date.`
- The tool itself never invokes the `commit-with-lplp-style` skill process (`ai/git/pending-commit.md`, etc.) — that workflow is for *my* commits while implementing this plan. The tool's own generated commits still follow the same message conventions (bracketed `[where]`, sentence-terminated subject, informative body) so history stays consistent either way.

## Verification

- `uv run pytest tests/test_common.py tests/test_versioning.py tests/test_dekudeals_*.py tests/test_isthereanydeal_*.py tests/test_greenmangaming_*.py tests/test_dailyindiegame_*.py tests/test_humblebundle_*.py -q`
- New migration tests run the real per-source `MIGRATIONS` step list against a handful of **actual existing files** copied from `archives/<source>/bundle/**/metadata.json` (not synthetic fixtures), asserting the migrated shape validates against the current model and that no data was silently dropped.
- `uv run game-collections schema` then `git diff --stat schemas/` to confirm every archive schema (plus the new shared envelope/timestamp schema, if standalone) regenerates cleanly; `tests/test_schema.py` also catches drift.
- `uv run game-collections migrate schema` (dry-run, no `--path`/`--type` filters) against the real repo to sanity-check the reported migration/rename plan and commit grouping before ever passing `--apply`.
- Manually run one real `scrape dekudeals --git --url <a currently-archived bundle>` against a scratch clone to confirm the two-commit shape (migration commit, then content commit) appears exactly as designed.
