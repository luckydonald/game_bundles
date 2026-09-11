# Confidence-scored bundle dates, generic version-envelope migrations, and fuzzy dedup

## Context

Fixing DekuDeals' list filename date-prefix bug exposed two structural gaps:

1. **Dedup can silently miss the same real-world bundle.** `existing_list_match` (`sources/common.py`) only does a plain substring match, so DekuDeals' own slug `crawling-through-the-dungeons` never matched the dedicated Humble scraper's real slug `crawling-through-dungeons` — DekuDeals would have kept a *second*, separately-dated list file for the same bundle.
2. **Date retrieval is real-but-uneven across sources, and nothing records how sure we are.** `crawled` is always `datetime.now(UTC)` at scrape time, by design — that part is genuinely just "when did we look at this." But `start`/`end` come from a real page/API field on some sources and are either missing or computed/estimated on others, and two live bugs surfaced during this investigation:
   - DekuDeals' `start` (already fixed) is only readable in discovery mode from the bundles-index page's `created_at`; an explicit `--url` crawl or an older archive has it as `None`.
   - **GreenManGaming's `end` is dead code**: the bundles-index page's `data-end-date="YYYY-MM-DDTHH:MM"` attribute is present in the parser's own test fixture (`tests/test_greenmangaming_parser.py:17,26`) but never captured by `_ProductCardParser`, and `parse_bundle_page` hardcodes `GmgDates(end=None, ...)` (`greenmangaming/parser.py:274`) despite `GmgDates`'s own docstring describing exactly that field.
   - DailyIndieGame's `end` is *computed* (`crawled + parsed "ends in Xd:Xh:Xm:Xs"` countdown, `dailyindiegame/parser.py:213-219`) — real data, but an estimate, not a fixed timestamp.

A plain `datetime | None` can't express "how sure are we, and where did this come from" — needed to decide whether a corrected value should ever replace what's on disk, and whether a list file's date-prefixed name needs correcting. This also can't happen as a one-off retrofit: every source's archive/source-payload files need a real, generic version envelope so *this* shape change — and any future one — migrates itself automatically, grouped into a small number of clean commits, with no dedicated "run this migration" step ever required by hand.

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

`DekuIndexEntry` (`dekudeals/parser.py`) currently only keeps `slug`/`created_at`. Expand it to also keep `name`, `store`, `tiering_style`, `price`/`price_formatted`, `size`, `ends_at`, `ends_at_label` — every field with a stable, typed meaning. `image`/`top_items`/`created_at_formatted`/`ends_at_formatted` are decorative/redundant; leave them unmodeled but note in the dataclass docstring that they're known-and-skipped, not silently dropped without acknowledgement. The index's `ends_at` means discovery mode can now cross-check `end` the same way it already supplies `start`, at the same 1.0 confidence as the detail page.

## Confidence table (per source, per field)

| Source | field | how it's derived | confidence |
|---|---|---|---|
| Humble | `start` | bundle detail page `start_date\|datetime` / Choice `validFrom` — real field | **1.0** |
| Humble | `end` | bundle detail page `end_date\|datetime`/`end_time\|datetime` / Choice `validThrough` — real field | **1.0** |
| isthereanydeal | `start` | discovery-list API `summary.start` (unix ts) — real field | **1.0** |
| isthereanydeal | `end`/`expiry` | discovery-list API `summary.expiry` (unix ts) — real field | **1.0** |
| DekuDeals | `start` | bundles-index page `created_at` — real field, only present in discovery mode | **1.0** when present, else `None` |
| DekuDeals | `end` | bundle detail page `ends_at` (cross-checkable against the index's own `ends_at`) | **1.0** when present, else `None` |
| GreenManGaming | `start` | no known source | `None` (left unset, not fabricated) |
| GreenManGaming | `end` | bundles-index page `data-end-date` (date+time, **no explicit tz** — assumed UTC, unconfirmed against the server) — parsed in the fixture today but **not wired**; this plan wires it | **0.7** (real value, timezone assumption unverified) |
| DailyIndieGame | `start` | no known source | `None` |
| DailyIndieGame | `end` | computed: `crawled + parsed countdown` — real countdown text, but a derived, second-precision-drifting estimate | **0.5** |

Legacy (pre-migration) values get confidence **0.0** unconditionally — we never tracked confidence before, so every existing value is "unverified," never assumed to have been a real 1.0. That makes the replace rule below unambiguous: any freshly-derived real value always beats a `0.0` legacy one.

## 1. `ScrapedTimestamp` — new shared model, `game_collections/sources/timestamps.py`

```python
class ScrapedTimestamp(StrictModel):
    iso: NonEmptyString      # original precision preserved: "YYYY-MM-DD", or with time/ms/offset
    timestamp: float         # unix epoch seconds, cross-checked against `iso`
    confidence: float = Field(ge=0.0, le=1.0)
    source: SourceName       # see §9 - shared crawler-name type, not a bare string
```
- `model_validator(mode="after")` parses `iso` (date-only / date+time / date+time+fraction / date+time+offset) and confirms it's consistent with `timestamp`; a naive time-of-day `iso` (no explicit offset) is only allowed for the date-only case.
- `build_scraped_timestamp(value: datetime, source: SourceName, confidence: float) -> ScrapedTimestamp` — convenience constructor preserving `value`'s own precision in `iso`.
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

## 2. `SchemaDateVersion` — a comparable, precision-honest version tuple

```python
class SchemaDateVersion(NamedTuple):
    year: int
    month: int
    day: int
    hour: int | None = None
    minute: int | None = None
    second: int | None = None
    fraction: float | None = None

    def render(self) -> str:
        """Human string at whatever precision this value actually carries."""
        if self.hour is None:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        # end if
        text = f"{self.year:04d}-{self.month:02d}-{self.day:02d} {self.hour:02d}:{self.minute:02d}"
        if self.second is None:
            return text
        # end if
        text += f":{self.second:02d}"
        return text + f"{self.fraction:.6f}".lstrip("0") if self.fraction else text
    # end def render

    def sort_key(self) -> tuple[int, int, int, int, int, int, float]:
        """A total-ordering key so two values of different precision still compare sanely."""
        return (self.year, self.month, self.day, self.hour or 0, self.minute or 0, self.second or 0, self.fraction or 0.0)
    # end def sort_key
# end class SchemaDateVersion
```

**Precision rule you specified** (validated via `AfterValidator`, since `NamedTuple` itself can't run field validators): a value is either date-only (`hour`/`minute`/`second`/`fraction` all `None`), or has **at least hour+minute together** (never hour alone, never minute alone), optionally extended by `second`, optionally further extended by `fraction` — each finer field requires every coarser field to also be present:

```python
def _validate_precision(value: SchemaDateVersion) -> SchemaDateVersion:
    has_hour, has_minute = value.hour is not None, value.minute is not None
    if has_hour != has_minute:
        raise ValueError("hour and minute must be given together - minute-accurate time, or no time at all")
    # end if
    if value.second is not None and not has_minute:
        raise ValueError("second requires hour and minute")
    # end if
    if value.fraction is not None and value.second is None:
        raise ValueError("fraction requires hour, minute, and second")
    # end if
    return value
# end def _validate_precision
```
Rejects `ymd,h` / `ymd,m` / `ymd,f` / `ymd,ms` alone; accepts `ymd` / `ymd,hm` / `ymd,hms` / `ymd,hmsf`. `LEGACY_VERSION = SchemaDateVersion(1970, 1, 1)` (a shared constant in `versioning.py`) is the sentinel for "pre-envelope flat file, no version info at all" — passes this rule trivially (date-only).

**Per-source version enumeration** (your call: start with an explicit `Literal[...]` of every version a source has ever declared, not an unconstrained field — cheap today, and it's a standing reminder to add a migration step whenever you bump it; revisit only if the list ever gets unwieldy):

```python
# dekudeals/models.py
DEKU_V1 = SchemaDateVersion(2026, 7, 20)                       # original schema=1 shape
DEKU_V2 = SchemaDateVersion(2026, 9, 11, 14, 30)                # confidence-scored dates + version envelope (this plan)
DekuVersions = Literal[LEGACY_VERSION, DEKU_V1, DEKU_V2]        # every version ever seen for this source's archives
DekuCurrentVersion = Literal[DEKU_V2]                            # single value: "this object is definitely fully migrated"
CURRENT_VERSION: DekuCurrentVersion = DEKU_V2
VersionedDekuArchive = Versioned[DekuCurrentVersion, DekuArchive]
```
On your question **"will `Literal[CURRENT_VERSION]` fill the default value?"** — no. `Literal[X]` only constrains *allowed* values to `X`; it never supplies a default. A field typed `DekuCurrentVersion` (or any `Literal[...]`) still needs an explicit value at construction time, or `Field(default=CURRENT_VERSION)` if you want one to fall out of `Model()` with no arguments. In practice the writer always passes `version=CURRENT_VERSION` explicitly, so a default is a nice-to-have, not load-bearing. (Separately: `Literal[...]` does technically accept tuple *values* like `SchemaDateVersion(...)` as parameters — that's exactly what's used above — the thing that doesn't work is trying to type the field as an open-ended, ever-growing union that the type-checker enforces membership against; that's fine here specifically because it's a short, deliberately-visible list.)

## 3. `Versioned` envelope + migration trajectory — new `game_collections/versioning.py`

```python
class Versioned[VERSION, DATA](BaseModel):
    version: VERSION
    data: DATA
```
Every on-disk `metadata.json` **and** `source.json` (currently `source.json` has no version field at all) gets wrapped this way, replacing each source's old embedded `schema_version: Literal[N] = Field(alias="schema", ...)` entirely — `DekuArchive` etc. drop that field; versioning lives only in the envelope. On disk:
```json
{"version": [2026, 9, 11, 14, 30, null, null], "data": {"machine_name": "...", ...}}
```

**Reading pre-envelope files**: peek the raw JSON for top-level `version`+`data` keys. If both are present, it's already enveloped. **Otherwise the entire raw JSON *is* `data`, and its version is `LEGACY_VERSION`** — today's files have no `version`/`data` wrapper at all (only the *old* embedded `schema: 1` field, itself now obsolete and dropped once migrated), so this is the real, common case for everything currently on disk, not a hypothetical edge case.

**Wrapping a legacy flat file into the envelope is itself migration step 0** — `LEGACY_VERSION → <source>_V1` — done **as its own separate first commit per (source, file-kind)** (so: a `metadata.json`-envelope commit and a `source.json`-envelope commit, for each of the 5 sources, ten commits total the first time this runs across the whole repo), before any of the confidence-dates content changes land. This step also deletes the old `schema`-aliased field from `data`, since the new model no longer declares it.

**Migration trajectory (critique of the `if v1: ...; if v2: ...` sketch, and the design that replaces it):**

The if-chain's real problem isn't correctness, it's that it computes a **file's entire end-to-end result in one call** — it can only ever go 1→N in one shot, which is exactly what you flagged ("your example does 1→4, instead of 1→2, 2→3, 3→4, which should be separate commits"). Grouping *across many files* by "which step they're currently on" needs each file's migration to be resumable one step at a time, not computed all at once. It's also impure by construction — the "commit this" side effect lives inside the same block as the data transform, which is exactly why the sketch's own dry-run TODO comment is stuck.

**Chosen design — a lazy per-file trajectory generator, driven by an outer wavefront that groups across files by version:**

```python
def trajectory[VERSION, DATA](
    initial_version: VERSION,
    initial_data: DATA,
    steps: Sequence[tuple[VERSION, Callable[[DATA], DATA]]],  # sorted ascending by target version
) -> Iterator[Versioned[VERSION, DATA]]:
    """Yield one Versioned snapshot per outstanding step for one file - lazily, one at a time."""
    version, data = initial_version, initial_data
    for target_version, migrate_fn in steps:
        if version.sort_key() >= target_version.sort_key():
            continue  # already past this step
        # end if
        data = migrate_fn(data)
        version = target_version
        yield Versioned(version=version, data=data)
    # end for
# end def trajectory
```
No `current_version` parameter — you're right that it's redundant: the loop just runs every step ahead of the file's own version, in the step list's own order, and "latest" is simply the list's last entry. Returning a *generator* (not a dict, and not the single collapsed end-state) directly answers "the return type shall be a NamedTuple, not a dict" — each yielded item *is* the `Versioned[VERSION, DATA]` NamedTuple-backed model, and the trajectory as a whole is what lets a caller diff consecutive steps for the dry-run report instead of only seeing a final flattened result.

**Outer wavefront** (this is your own algorithm, validated - see critique below):
1. Build one `trajectory(...)` generator per candidate file (candidates come from either an explicit `list[Path]` the caller already knows it's about to touch, or `None` meaning "every file matching `--path`/`--type`," which the standalone `migrate schema` command resolves into an explicit list itself before doing the same thing).
2. Pull `next()` once per file to get each one's *first* pending snapshot; drop any file whose generator is immediately exhausted (already fully migrated).
3. Group the still-pending files by `(source, file_kind, version)` — **the key must include `source` and `file_kind`, not just the bare version tuple**, since e.g. DekuDeals' v2 and GreenManGaming's v2 are unrelated migrations that happen to share a coincidental version label; grouping by bare version alone would wrongly merge them into one commit.
4. Pick the group whose version sorts earliest; apply it (content overwrite for `metadata.json`/`source.json`, or a real rename for a list-file path — see below) and commit it (§8's rules: content = one commit, path/rename = batched ≤100 with a counter).
5. For every file in the group just processed, pull `next()` on its generator again (advancing it one more step, or exhausting it); re-merge into the pending set per step 3.
6. Repeat 3-5 until nothing is pending.

This is memory-bounded to "the current frontier," not every file's full trajectory at once (your concern about 5k files × many versions), because each generator only ever computes one step ahead of where the wavefront currently is.

**Unifying path-renames and content-migrations under one mechanism** (your idea, adopted): a rename is just a migration whose `DATA` is `Path` instead of `dict` — `PathMigrationVersion = Versioned[VERSION, Path]` alongside `DataMigrationVersion = Versioned[VERSION, DATA]`. A rename "step" computes the corrected target `Path` (from the file's resolved `start`/`end`) without touching the filesystem; the wavefront driver's step-4 `apply` callback is the *only* place that does real I/O, and it's parameterized by which kind it's handling (`git mv` for `Path`, atomic overwrite for `dict`) — same generator/grouping/commit-driving code either way, only the leaf `apply` differs.

**Is unifying the final crawl-content write into this same machinery worth it?** Conceptually clean (as one more `kind="crawl"` step after the schema wavefront finishes), but its "group" is trivially "everything this run touched" — there's no shared version value across files to group crawl output by, since each bundle's freshly-crawled data is independent. Forcing it through the same version-keyed grouping wouldn't simplify anything further, so it stays what §6 already does: the schema/rename wavefront finishes and commits first, then exactly one ordinary `finish_scrape_git_session` commit for the run's own crawl output, unbatched, as today.

## 4. Fuzzy + content-similarity dedup — `sources/common.py`

`existing_list_match(lists_root, provider_slug, slug, fresh_games: list[Game] | None = None) -> Path | None`:

- **Exact substring match** (current behavior, unchanged, no content check needed): e.g. DekuDeals slug `metroidvania-madness` is a substring of the existing `lists/greenmangaming/bundle/2026-06-01_metroidvania-madness.yml` → matched immediately.
- **Fuzzy name match** (new): when no substring hit and `fresh_games` was passed, score every existing bundle file/directory name (date-prefix and extension stripped, dashes→spaces) against `slug` via `rapidfuzz.fuzz` (already imported here, same `FUZZY_MATCH_THRESHOLD` convention `find_matching_game` uses). Example: DekuDeals slug `crawling-through-the-dungeons` vs. the real Humble file `2026-09-09_crawling-through-dungeons.yml` — substring check fails both directions, but `fuzz.WRatio("crawling through the dungeons", "crawling through dungeons")` scores well above threshold (one stopword differs, not a number/edition word) → candidate goes to the content check.
- **Content check** (required before trusting any *fuzzy-only* candidate; never applied to a substring hit): load the candidate's `GameList`(s) and run each of `fresh_games` through the existing `find_matching_game` cascade against its roster; require at least half of `fresh_games` to resolve. Example (true positive): DekuDeals' resolved roster for `crawling-through-the-dungeons` matches nearly 1:1 against the existing Humble list's games by id. Example (rejected): a fresh `indie-bundle-2026` scored fuzzily similar to an unrelated `indie-bundle-2025`, but their rosters share zero games → rejected, written as a new bundle.
- **Confirmation before backfilling a fuzzy-only match** (interactive/non-interactive split, same shape as §1's timestamp conflicts): on a TTY, always prompt — show both bundle names/slugs, the fuzzy score, and the content-overlap fraction, and let you confirm or reject before any backfill happens. Non-interactive (`--git`/CI): only auto-accept when the match is *very* strong — a stricter pair of thresholds than the baseline (e.g. fuzzy score ≥97 **and** ≥90% of `fresh_games` resolving, vs. the baseline `FUZZY_MATCH_THRESHOLD`/50% used to even consider a candidate); anything weaker than that is skipped (treated as a new, separate bundle) rather than guessed.
- Both `isthereanydeal/crawler.py` and `dekudeals/crawler.py` pass their already-flattened pool (`_flatten_itad_games`/`_flatten_deku_games`) at their `existing_list_match(...)` call sites.
- New tests: the real `crawling-through-the-dungeons`/`crawling-through-dungeons` true-positive case, a fuzzy-name/dissimilar-roster rejection case, and the non-interactive stricter-threshold boundary.

## 5. Wiring `start`/`end`/`first_seen` per source

- `crawled` stays named as-is (no rename) — it's fine.
- Add `first_seen: datetime | None = None` to every `*Dates` model: set once, the first time an archive is ever written for that key, never overwritten afterward. The legacy→v1-envelope migration (§3) backfills it from the pre-migration `crawled` value — the only timestamp available for "when did we first see this," documented as a proxy, not the true first-seen date.
- `start`/`end` (and ITAD's `expiry`) become `ScrapedTimestamp | None`, built via `build_scraped_timestamp(value, source=SourceName.X, confidence=<table above>)` at each crawler's construction site.
- **GMG fix included here**: extend `_ProductCardParser`/`parse_bundle_index_page` (`greenmangaming/parser.py`) to also capture `data-end-date` per slug (mirroring the `created_at_by_slug` pattern `dekudeals/crawler.py` already uses), thread it into `crawl_gmg_offers`, and stop hardcoding `GmgDates(end=None, ...)`.
- Regenerate all 5 `schemas/<source>-archive.schema.json` (`tests/test_schema.py` enforces this) plus one for the shared `ScrapedTimestamp`/`Versioned` envelope.

## 6. Auto-migration wired into every scrape run — no dedicated migration command needed

The scrape flow already knows **every archive path it's about to touch immediately after discovery**, before fetching a single bundle's content: `_archive_paths(archive_root, slug)` for every slug the index/discovery fetch returns. That answers "how do we detect changed files before writing without already having the new crawl data" — order becomes:

1. Discover slugs (index fetch only, no per-bundle fetch yet).
2. Build the candidate `metadata.json`/`source.json` path list from those slugs.
3. Run the §3 wavefront over exactly those paths — this produces zero or more schema-migration commits (envelope-wrapping + any confidence-dates content migration), fully separate from crawling.
4. *Then* proceed with each bundle's normal fetch/cache/write logic exactly as today (cache hits now read already-migrated files; a cache miss fetches and overwrites as usual).
5. One final ordinary crawl-content commit via `finish_scrape_git_session`, unchanged in shape.

`git_ops.py`'s existing `commit_changed_paths` (already usable standalone, not only from inside `finish_scrape_git_session`) is called once per migration-wavefront group in step 3, before the single step-5 commit — no changes needed to `git_ops.py` itself.

## 7. Standalone `migrate schema` CLI command

New subcommand under the existing `migrate` Typer group, for running all outstanding migrations without crawling:

- `--path` (repeatable): a directory (recursed) or a single file; no `--path` at all scans the whole repo.
- `--type` (repeatable, AND'd): `metadata` | `source` | `bundle` (the last has no pending migration yet, but the filter and engine are file-kind-agnostic and ready for whenever a `GameList` schema bump happens).
- `--source` (repeatable, AND'd): filter by `SourceName` (§9) — free with the shared type now existing.
- `--git`/`--git-style`: same flag shape as `scrape`'s group callback, reusing `git_ops.begin_scrape_git_session`/`commit_changed_paths`/`finish_scrape_git_session`.
- **Flags**: default = dry run (equivalent to explicit `--dry-run`); `--apply` writes changes without committing; `--git` **implies** `--apply` and also commits. `--dry-run` is invalid together with `--apply`/`--git`.
- **Dry-run output**: groups pending changes exactly the way they'd be committed (§3's wavefront groups, in order), each with a diff of what would change — for content migrations, a structural before/after of the changed fields; for renames, old path → new path.

## 8. Commit shape rules

- **Schema-migration commits** (content, `DATA = dict`): one commit per `(source, file_kind, version)` group, not batched by file count. Subject line:
  `` [lists] metadata: Migrating Model `2026-09-11 23:40:24` → `2026-09-12`. ``
  (bracketed scope adapted to what's migrating, e.g. `[lists] source:` for `source.json`; each backtick-quoted value is `SchemaDateVersion.render()` at whatever precision it actually carries — mixed precision between "from" and "to" is expected and fine, as shown.)
- **Rename/content commits** (`DATA = Path`): always batched, **max 100 files per commit**, counter padded to the width of the total (`(1/3)`, not `(01/3)`; `(03/22)`, not `(3/22)`): `` (1/3) [lists] dekudeals: Renamed bundle list files to their corrected start date. ``
- Every commit subject ends with a `.` (or other sentence-terminator), matching the repo's existing convention.
- The tool's own commits don't go through the `commit-with-lplp-style` skill's manual steps (`ai/git/pending-commit.md` etc.) — that workflow is for *my* commits while implementing this plan — but the generated messages still follow the same shape (bracketed `[where]`, sentence-terminated subject, informative body) so history reads consistently either way.

## 9. Shared `SourceName` type — new `game_collections/sources/names.py`

```python
class SourceName(StrEnum):
    HUMBLEBUNDLE = "humblebundle"
    GREENMANGAMING = "greenmangaming"
    DAILYINDIEGAME = "dailyindiegame"
    ISTHEREANYDEAL = "isthereanydeal"
    DEKUDEALS = "dekudeals"
```
One place naming every crawler, reused for: `ScrapedTimestamp.source` (§1), the new `migrate schema --source` filter (§7, Typer accepts enums as choices natively), and available wherever a bare crawler-name string is passed around today (e.g. `backfill_existing_lists`' `crawler_name` parameter) — not retrofitting every existing `list[str]`/`crawlers` field in this pass, just giving future code one canonical source of truth instead of a new ad-hoc string each time.

## Verification

- `uv run pytest tests/test_common.py tests/test_versioning.py tests/test_dekudeals_*.py tests/test_isthereanydeal_*.py tests/test_greenmangaming_*.py tests/test_dailyindiegame_*.py tests/test_humblebundle_*.py -q`
- New migration tests run each source's real step list against **actual existing files** copied from `archives/<source>/bundle/**/metadata.json` and `source.json` (not synthetic fixtures) — at least one legacy flat file and (once available) one already-enveloped file per source — asserting the migrated shape validates against the current model, `first_seen` backfills correctly, and no data is silently dropped.
- New wavefront-driver tests: several files at different starting versions (including some already at `CURRENT_VERSION`, which must produce zero commits) confirming grouping is keyed by `(source, file_kind, version)`, batching only applies to `Path`-kind groups, and per-group commit counts match `⌈group_size / 100⌉`.
- `uv run game-collections schema` then `git diff --stat schemas/` to confirm every archive schema (plus the new shared envelope/timestamp schema) regenerates cleanly; `tests/test_schema.py` also catches drift.
- `uv run game-collections migrate schema` (dry-run, no filters) against the real repo to sanity-check the reported plan/grouping/commit-message rendering before ever passing `--apply`/`--git`.
- Manually run one real `scrape dekudeals --git --url <a currently-archived bundle>` against a scratch clone to confirm the commit shape: legacy-envelope commit(s) for the touched files, then the ordinary crawl-content commit, in that order.
