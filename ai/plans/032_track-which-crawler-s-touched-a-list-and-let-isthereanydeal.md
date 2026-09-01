# Track which crawler(s) touched a list, and let isthereanydeal backfill instead of just skip

## Context

`scrape isthereanydeal` dedups against dedicated scrapers by string-matching
the bundle's slug against filenames under `lists/<provider>/**`
(`_existing_list_match` / `_existing_choice_match` in
`src/game_collections/sources/isthereanydeal/crawler.py:376-419`). When it
finds a match (e.g. Humble already scraped the same bundle), it writes the
ITAD archive but skips the public list entirely — forever, on every future
run, even though the ITAD page may have resolved storefront IDs that the
dedicated scraper's own resolver missed (the "shop 61 (Steam) has no matching
resolved id" warnings the user saw are exactly this case). There's currently
no record anywhere of which crawler(s) have actually processed a given list,
so there's no way to know whether a "covered" bundle has ever actually been
cross-checked by ITAD, and no path for ITAD to contribute the IDs it *did*
resolve into the list a different crawler owns.

This adds a `crawlers` provenance field to `GameList` and uses it to turn
ITAD's dedup skip into a one-time "cross-check and backfill IDs, then mark
done" pass instead of a permanent no-op.

## Model change

`src/game_collections/models.py` — add to `GameList` (near `references`,
`models.py:136`):

```python
# Crawler module slugs (e.g. "humblebundle", "isthereanydeal") that have
# contributed to or verified this list. Lets a later crawler tell an
# already-covered bundle from one it has actually cross-checked.
crawlers: list[NonEmptyString] = Field(default_factory=list)
```

Optional field, default `[]`, so existing hand-authored/older scraped lists
stay valid without a migration. Regenerate `schemas/game-list.schema.json`
(`uv run game-collections schema`) — required per `tests/test_schema.py`.

`src/game_collections/sources/common.py`, `render_game_list_yaml` (line 218):
apply the same "drop if empty" treatment already used for `invalid`
(line 222-224) to `crawlers`, so files with no recorded crawler don't grow a
noisy `crawlers: []` line.

## Shared merge helpers (`common.py`)

Promote the two helpers `merge_game_list` (line 171) already relies on from
module-private to shared, cross-module utilities, since the isthereanydeal
backfill path (below) needs the same matching/merging logic:

- `_find_match` (line 130) → rename to `find_matching_game` (public). Used
  as-is by `merge_game_list` and by the new ITAD backfill function.
- `_merged_references` (line 75) → rename to `merge_references` (public).
- Add a new `merge_crawlers(existing: GameList, fresh: GameList) -> list[str]`
  next to it: union of `existing.crawlers` and `fresh.crawlers`, preserving
  `existing`'s order and appending any new entries from `fresh` — same shape
  as `merge_references`. Wire it into `merge_game_list`'s two return paths
  (lines 200, 214) so a dedicated scraper's own re-crawl never drops a
  `crawlers` entry ITAD's backfill previously added.

Each source's own writer sets its own slug when constructing a fresh
`GameList`:
- `humblebundle/crawler.py:328,379` → `crawlers=["humblebundle"]`
- `greenmangaming/crawler.py:290` → `crawlers=["greenmangaming"]`
- `dailyindiegame/crawler.py:277` → `crawlers=["dailyindiegame"]`
- `isthereanydeal/crawler.py:467,508` (the "not covered, write our own list"
  branches) → `crawlers=["isthereanydeal"]`

Humble's `_write_merged_game_list` (crawler.py:271) already routes through
`merge_game_list` on re-crawl, so it picks up the `crawlers` union for free
once the above is wired in.

## isthereanydeal: backfill instead of permanent skip

In `write_itad_offer` (`isthereanydeal/crawler.py:422`), replace the
unconditional skip-and-return (lines 439-442) with:

1. Resolve `existing` as today via `_existing_choice_match` /
   `_existing_list_match`.
2. If `existing is None`: unchanged, fall through to the normal
   own-list-writing code.
3. If `existing` is found, gather the on-disk list file(s) to consider:
   `existing` itself if it's a file, or `existing.glob("*.yml")` if it's a
   bundle directory (the current dedup match is usually the directory, since
   `sorted(rglob("*"))` yields the directory path before its children).
4. Load each with `GameList.model_validate` (skip unreadable/invalid files
   defensively, same tolerance style as `load_cached_archive`).
5. If **every** loaded list already has `"isthereanydeal"` in `crawlers`:
   log the existing "Skipped … already covered by …" message unchanged and
   return — this bundle has already been cross-checked, nothing to redo.
6. Otherwise, this is the first ITAD pass over an already-covered bundle:
   - Build the ITAD-derived game pool the same way the normal write path
     already does (flatten `archive.tiers`/`byob_tiers` items into
     `Game(name=..., ids=...)`, reusing the existing per-tier
     dedup-by-id loop rather than duplicating it — factor that inner loop
     at lines ~448-457/486+ into a small helper if needed).
   - For each on-disk list file, and each of its `games`, find the matching
     ITAD-derived game via `find_matching_game` (promoted above). For a
     match, add any qualified IDs from the ITAD side whose **provider** is
     not already present on the existing game (never override or duplicate
     a provider the dedicated scraper already resolved; the `unresolved`
     provider from ITAD's own marker convention is exempt from this
     provider-presence check, since those are markers, not resolved IDs, and
     multiple can coexist).
   - Merge in `references` (`merge_references`) and `crawlers`
     (`merge_crawlers`, ensuring `"isthereanydeal"` ends up present) same as
     `merge_game_list` does.
   - Write the updated list back via `atomic_write`/`render_game_list_yaml`
     only if anything actually changed (new IDs, references, or the
     crawlers entry itself), and log a one-line summary, e.g. `f"  Backfilled
     {n} id(s) into {path} from isthereanydeal"` or, when nothing new was
     found, keep the existing "already covered by" log line so silent runs
     stay quiet.
   - Do not create new games or remove/reorder existing ones — the dedicated
     scraper's tier/pick structure stays authoritative; ITAD only adds IDs,
     references, and its own crawlers entry.
7. Still return early (no independent `lists/isthereanydeal/...` file is
   written for an already-covered bundle) — only the existing dedicated
   list(s) get touched.

## Tests

- `tests/test_isthereanydeal_crawler.py`: extend the existing dedup-skip
  test(s) (around lines 283-389) to cover: (a) a covered bundle where the
  existing list has no `crawlers` yet → IDs get backfilled and `crawlers`
  gains `"isthereanydeal"`; (b) a second run over the same now-marked list →
  no-op skip, unchanged file; (c) an ITAD-resolved provider that's already
  present on the existing game → not duplicated/overridden.
- `tests/test_humblebundle_crawler.py`, `test_greenmangaming_crawler.py`,
  `test_dailyindiegame_crawler.py`: update assertions that check the written
  `GameList`'s fields to also expect the new `crawlers=["<source>"]` entry.
- No golden/fixture YAML files exist for these sources (confirmed), so no
  snapshot files need regenerating — only in-test field assertions.

## Verification

```console
env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections schema
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_schema.py tests/test_isthereanydeal_crawler.py tests/test_humblebundle_crawler.py tests/test_greenmangaming_crawler.py tests/test_dailyindiegame_crawler.py -q
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

Then a real dry-run against the bundle from the report to confirm the new
behavior end-to-end (read-only, writes into the working tree like any other
scrape):

```console
uv run game-collections scrape isthereanydeal
```

Check that a previously-"Skipped" bundle now either logs a "Backfilled …"
line (first pass) or the same quiet "already covered" line (second pass,
`crawlers` already contains `isthereanydeal`), and that
`lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/*.yml`
gained a `crawlers: [humblebundle, isthereanydeal]` line without losing or
reordering any existing games.
