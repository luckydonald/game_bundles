# Confidence-scored bundle start/end dates + fuzzy dedup + rename migration

## Context

While fixing DekuDeals' list filename date-prefix bug, the underlying cause turned out to be structural, not a one-off: `existing_list_match` (`sources/common.py`) only does a plain substring match, so DekuDeals' own slug `crawling-through-the-dungeons` never matched the dedicated Humble scraper's real slug `crawling-through-dungeons` — dedup silently failed and DekuDeals would have kept a *second*, separately-dated list file for the same real-world bundle.

Digging into "store start and end properly" surfaced that **date retrieval is not uniformly `datetime.now()`, but it also isn't uniformly trustworthy**:

- `crawled` *is* always `datetime.now(UTC)` at scrape time, everywhere — that's intentional (it's "when we observed this," never a stand-in for the bundle's real dates).
- `start`/`end` are pulled from real per-source page/API fields where available, but two live bugs were found in this investigation:
  - **DekuDeals** (already fixed for `start`): the bundles-index page's `created_at` is only read in discovery mode; an explicit `--url` crawl or an older archive has `start = None` even though the index page knows it.
  - **GreenManGaming `end` is dead code**: the bundles index page's `data-end-date="YYYY-MM-DDTHH:MM"` attribute is present in the parser's own test fixture (`tests/test_greenmangaming_parser.py`) but `_ProductCardParser`/`parse_bundle_index_page` never captures it, and `parse_bundle_page` hardcodes `GmgDates(end=None, ...)` (`greenmangaming/parser.py:274`) despite `GmgDates`'s own docstring describing that exact field.
- Some sources compute rather than read a date: DailyIndieGame's `end` is `crawled + parsed countdown timer` (`dailyindiegame/parser.py:213-219`) — real data, but derived and imprecise, not a fixed page timestamp.
- Some fields have no known live source at all: GMG `start`, DIG `start`.

Given that, plain `datetime | None` can't represent "how sure are we, and where did this come from" — needed to decide whether a corrected value should replace what's on disk, and to know when a list file's date-prefixed name needs fixing. The user asked for a confidence-scored timestamp model, a schema migration (v1→v2) for it, a generic rename tool built on top, and the fuzzy/content-aware dedup improvement — all executed with git history kept clean via ≤100-file batched commits with `(NN/N)` counters, migration commits landing before content-change commits.

## Confidence table (per source, per field)

| Source | field | how it's derived | confidence |
|---|---|---|---|
| Humble | `start` | bundle detail page `start_date\|datetime` field / Choice `validFrom` — real field | **1.0** |
| Humble | `end` | bundle detail page `end_date\|datetime`/`end_time\|datetime` / Choice `validThrough` — real field | **1.0** |
| isthereanydeal | `start` | discovery-list API `summary.start` (unix ts) — real field | **1.0** |
| isthereanydeal | `end`/`expiry` | discovery-list API `summary.expiry` (unix ts) — real field | **1.0** |
| DekuDeals | `start` | bundles-index page `created_at` (unix ts) — real field, **only present in discovery-mode crawls** | **1.0** when present, else `None` |
| DekuDeals | `end` | bundle detail page `ends_at` (unix ts) — real field | **1.0** when present, else `None` |
| GreenManGaming | `start` | no known source | `None` (leave unset) |
| GreenManGaming | `end` | bundles-index page `data-end-date` (date+time, **no explicit tz** — assumed UTC, unconfirmed against the server) — currently parsed in the fixture but **not wired**; this plan wires it | **0.7** (real value, but the timezone assumption is unverified) |
| DailyIndieGame | `start` | no known source | `None` (leave unset) |
| DailyIndieGame | `end` | computed: `crawled + parsed "ends in Xd:Xh:Xm:Xs"` countdown — real countdown text, but a derived, second-precision-drifting estimate, not a fixed timestamp | **0.5** |

Legacy (pre-migration) values get confidence **0.0** unconditionally — we never tracked confidence before, so treat every existing value as "unverified" rather than guessing it was actually a 1.0. This makes the replace rule below trivially correct: any freshly-derived, real value always wins over a `0.0` legacy one.

## 1. Shared `ScrapedTimestamp` model — new `sources/timestamps.py`

```python
class ScrapedTimestamp(StrictModel):
    iso: NonEmptyString      # original precision preserved: "YYYY-MM-DD", or with time/ms/offset
    timestamp: float         # unix epoch seconds, always cross-checked against `iso`
    confidence: float = Field(ge=0.0, le=1.0)
    source: NonEmptyString   # crawler name: "humblebundle" | "greenmangaming" | "dailyindiegame" | "isthereanydeal" | "dekudeals"
```
- `model_validator(mode="after")`: parse `iso` (accepting date-only, date+time, date+time+fraction, date+time+offset) and confirm it's consistent with `timestamp` (bounded tolerance); reject naive time-of-day `iso` strings without an explicit offset unless date-only.
- `build_scraped_timestamp(value: datetime, source: str, confidence: float) -> ScrapedTimestamp` — convenience constructor from an already-parsed `datetime`, preserving its precision in `iso`.
- `merge_scraped_timestamp(existing: ScrapedTimestamp | None, fresh: ScrapedTimestamp | None) -> tuple[ScrapedTimestamp | None, str | None]` — encodes the resolution rules the user specified, returns `(value_to_keep, warning_or_None)`:
  1. `fresh is None` → keep `existing` unchanged, no warning.
  2. `existing is None` → adopt `fresh` unconditionally, no warning.
  3. `existing.confidence == 0.0` → adopt `fresh` unconditionally; if `fresh`'s value differs from `existing`'s, return a warning string with both old and new (`iso`/`source`) for the end-of-run summary.
  4. `existing.confidence == fresh.confidence == 1.0` and both represent the *same* moment (within tolerance) → keep whichever `iso` string encodes more precision (date+time+offset > date+time+ms > date+time > date-only); no warning either way.
  5. Otherwise (values disagree and neither case above applies) → keep `existing` as-is, but return a warning identifying the conflict (`existing` vs `fresh`, both sources) for manual review — never silently pick a side.

## 2. Per-source `Dates` models: `start`/`end` become `ScrapedTimestamp | None`

- `HumbleDates`, `ItadDates` (`start`/`expiry`), `DekuDates` (`start`/`end`): switch both fields from `datetime | None` to `ScrapedTimestamp | None`; bump `schema_version: Literal[1]` → `Literal[2]` on `HumbleArchive`, `ItadArchive`, `DekuArchive`.
- `GmgDates`, `DigDates`: same field-type change, same schema bump on `GmgArchive`/`DigArchive`. `start` stays permanently `None` for both (no known source — documented in the docstring, not fabricated).
- `crawled` stays a plain `datetime` everywhere — it's an observation timestamp, not a claim needing confidence.
- Update each source's crawler/parser call sites to build `ScrapedTimestamp` via `build_scraped_timestamp(value, source="<crawler-name>", confidence=<table above>)` instead of a bare `datetime`.
  - **GMG fix included here**: extend `_ProductCardParser`/`parse_bundle_index_page` (`greenmangaming/parser.py`) to also capture `data-end-date` per slug (mirroring DekuDeals' `created_at_by_slug` pattern added in `crawler.py`'s discovery branch), thread it into `crawl_gmg_offers`, and stop hardcoding `GmgDates(end=None, ...)`.
- Regenerate all 5 `schemas/<source>-archive.schema.json` files (`tests/test_schema.py` enforces this).

## 3. Fuzzy + content-similarity dedup — `sources/common.py`

Extend `existing_list_match` to take an optional `fresh_games: list[Game] | None` parameter:
- Exact substring match (current behavior) is unchanged and still trusted without a content check — it's already a strong signal.
- When no substring match is found and `fresh_games` is given, additionally score every existing bundle-directory/file name (date-prefix and extension stripped) against `slug` using `rapidfuzz.fuzz` (already imported in this file, same `FUZZY_MATCH_THRESHOLD` convention used by `find_matching_game`) with dashes normalized to spaces.
- A fuzzy-only candidate is accepted **only if content also matches**: load its `GameList`(s) and check that a meaningful fraction of `fresh_games` resolve via `find_matching_game` against its roster (e.g. reuse the same cascade already used by `backfill_existing_lists`, requiring at least half of `fresh_games` to match) — this is what prevents a false-positive purely from similar naming.
- Both `isthereanydeal/crawler.py` and `dekudeals/crawler.py` pass their already-flattened game pool (`_flatten_itad_games`/`_flatten_deku_games`) into the new parameter at their `existing_list_match(...)` call sites.
- Add tests reproducing the real "crawling-through-the-dungeons" vs "crawling-through-dungeons" case, plus a fuzzy-name/dissimilar-content case that must *not* match.

## 4. Migration module — `src/game_collections/migrations/archive_dates.py`

Mirrors the existing `migrations/tiers.py`/`migrations/bundle_variations.py` shape (`plan_migration`/`apply_migration_step`), but operates on `archives/<source>/bundle/**/metadata.json` instead of `lists/`:
- `migrate_v1_to_v2(source: str, raw: dict) -> dict`: per-source dispatch (registry keyed by the `archives/<source>/...` directory name) that moves `dates.start`/`dates.end`(/`expiry`) from bare ISO strings into `{iso, timestamp, confidence: 0.0, source}` and bumps `schema: 1 → 2`. Pure dict transform, no network access, fully deterministic — safe to run over the whole archive tree.
- `plan_migration(archive_root: Path) -> list[ArchiveMigrationStep]` / `apply_migration_step(...)` following the existing two-phase (plan, then apply) convention so the CLI stays dry-run-by-default like `migrate tiers`/`migrate bundle-variations`.

## 5. Generic rename tool — `migrate bundle-dates` CLI command

New Typer command in the existing `migrate` subgroup (`cli.py`), source-agnostic (per your answer: build it generic, wire up real derivation only for the sources that have one today):
1. **Schema migration pass** (uses module in step 4): any `archives/**/metadata.json` still at `schema: 1` gets migrated to `schema: 2` first — either just the ones this run's rename pass will touch (default) or the entire archive tree (`--migrate-all`).
2. **Re-derivation pass**: for each archive, re-run just that source's date-extraction logic against a fresh fetch (reusing the real crawler `fetch`/`parse_*` functions — no new scraping code) to compute a fresh `ScrapedTimestamp` for `start`/`end`, and combine it with the on-disk value via `merge_scraped_timestamp`.
3. **Rename planning**: if the resolved `start` (or `end`/`crawled` fallback, matching each source's existing `_bundle_date_prefix` logic) implies a different date prefix than the list file currently has, stage a rename of that `lists/<provider>/bundle/<old-date>_<slug>.yml` (or directory) to the corrected prefix.
4. **Conflict reporting**: any `merge_scraped_timestamp` conflict warning (case 5, disagreeing non-zero-confidence values) is collected and printed in the end-of-run summary together with every URL on record for that bundle (`archive.url`, `archive.real_url`, and any `Reference.url` on the affected list file) so you can resolve it by hand — never auto-picked.
5. **`--apply`**: writes the migrated/updated `metadata.json` files and performs the planned renames; without it, the command only prints the plan (dry-run default, matching `migrate tiers`/`migrate bundle-variations`).
6. End-of-run summary always lists: how many archives were schema-migrated, how many dates were replaced from a `0.0`-confidence legacy value (with old→new), how many renames were staged/applied, and every unresolved conflict.

The tool itself never calls `git` — committing follows the repo's normal `commit-with-lplp-style` process (below).

## 6. Execution order (once the above is implemented and reviewed)

Run `migrate bundle-dates` (dry-run) to see the real counts, then, per your explicit process requirement:
1. **Schema-migration commits first**: stage the `archives/**/metadata.json` files changed by step 4 in batches of ≤100 files each, one commit per batch, message subject prefixed `(01/N)`, `(02/N)`, … up to the batch count.
2. **Then rename/content commits**: once schema migration is fully committed, run `--apply` for the rename pass and commit the renamed `lists/**/*.yml` files (plus their updated `metadata.json`) the same way — ≤100 files/commit, `(NN/N)` counters — as separate commits after the schema-migration commits, not interleaved.
3. Both sets follow the existing `commit-with-lplp-style` conventions otherwise (explicit-path staging, `ai/git/pending-commit.md`, `tag_backup.py` after each).

## Verification

- `uv run pytest tests/test_common.py tests/test_dekudeals_crawler.py tests/test_isthereanydeal_crawler.py tests/test_greenmangaming_*.py tests/test_dailyindiegame_*.py tests/test_humblebundle_*.py tests/test_migrations_*.py -q`
- `uv run game-collections schema` then `git diff --stat schemas/` to confirm all 5 archive schemas regenerated cleanly (`tests/test_schema.py` also catches drift).
- `uv run game-collections migrate bundle-dates` (dry-run) against the real `archives/`/`lists/` trees to sanity-check the reported counts before ever passing `--apply`.
- New unit tests: `ScrapedTimestamp`/`merge_scraped_timestamp` round-trip and all 5 resolution cases; GMG `data-end-date` wiring; the fuzzy+content dedup match/no-match cases; the v1→v2 dict migration for each source's sample archive.
