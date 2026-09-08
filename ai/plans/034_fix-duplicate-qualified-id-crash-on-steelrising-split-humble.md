# Fix duplicate-qualified-ID crash on Steelrising split (Humble Bundle merge)

## Context

`game-collections scrape humblebundle --git` fails to (re-)scrape the "Dread and
Dark Fantasies RPG Collection" bundle with:

```
error: https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection: invalid game list lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml:
1 validation error for GameList
  Value error, list contains duplicate qualified game IDs
```

Root cause, traced through git history and code:

1. Commit `b3971cf61` (2026-09-01) first crawled this bundle before the resolver
   had "split an Edition into base+DLC" logic. It resolved the whole
   "Steelrising - Bastille Edition" title to a single (wrong) Steam app id,
   `steam:2021370` — that id actually belongs to the "Discus Chain" DLC; the
   real base game is `steam:1283400`. This got committed as-is.
2. Commit `9294debd3` (2026-09-02) re-ran the crawl after split-aware resolver
   logic landed (`src/game_collections/sources/humblebundle/resolver.py:401-483`).
   This time the crawler correctly produced 3 separate split `Game`s: "Steelrising"
   (1283400), "Steelrising - Discus Chain" (2021370), "Steelrising - Cagliostro's
   Secrets" (2004261). Because the file already existed, these were merged via
   `merge_game_list(existing, fresh, authoritative=True)`
   (`src/game_collections/sources/common.py:184-231`).
3. Inside that merge, `find_matching_game` (`common.py:143-181`) fuzzy-matched
   (`fuzz.WRatio` == 90.0, exactly at `FUZZY_MATCH_THRESHOLD`) the fresh base
   game "Steelrising" against the stale existing "Steelrising - Bastille
   Edition" candidate. On a match, `merge_game_list` keeps the **stale
   candidate's** `ids`/`group` (line 225: `merged_games.append(match)`), so the
   base game's correct id (`1283400`) was discarded and the old wrong
   `2021370` was kept for that entry.
4. The other two fresh split entries had no remaining candidate to match, so
   "Discus Chain" (also `2021370`, this time correctly) was appended fresh.
   Net result: `steam:2021370` now appears on two different `Game` entries in
   the same list — the exact state committed to
   `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/{tier-1,tier-2,tier-3}.yml`
   (all three tiers affected identically, confirmed by reading each file).

This is a real content bug (three committed files are wrong right now) plus a
latent hole in the merge algorithm (a fuzzy match can hand a fresh game a
stale candidate whose id collides with a *different* fresh game from the same
pass — nothing currently detects or prevents that). Both need fixing so the
scrape stops failing and this class of corruption can't quietly recur.

Decisions confirmed with the user:
- CI: add a post-scrape `game-collections validate` step to the weekly Humble
  workflow, but only as a warning (does not block the commit/PR), consistent
  with the workflow's existing "still commit whatever it produced" style.
- The repaired base "Steelrising" entry keeps the
  `isthereanydeal:steelrising-bastille-edition` id (no exact repo precedent
  for grouped split members carrying an itad id, but this best matches how
  the base game is later represented in the 2026-09-19 re-crawl of the same
  offer).

## Plan

### 1. Data repair (3 files)

In each of:
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml`
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-2.yml`
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-3.yml`

replace:

```yaml
- name: Steelrising - Bastille Edition
  ids:
  - steam:2021370
  - isthereanydeal:steelrising-bastille-edition
  requires: []
```

with:

```yaml
- name: Steelrising
  ids:
  - steam:1283400
  - isthereanydeal:steelrising-bastille-edition
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
```

Leave the "Steelrising - Discus Chain" and "Steelrising - Cagliostro's
Secrets" entries in all three files untouched — they're already correct.

After editing, run `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate`
to confirm the whole `lists/` tree loads cleanly.

No other files in the repo have this corruption pattern (verified by loading
every `lists/**/*.yml` through `GameList.model_validate`).

### 2. Merge-logic hardening — `src/game_collections/sources/common.py`

Add a narrow, targeted guard in the `authoritative=True` branch of
`merge_game_list` (around lines 217-227): track a running `used_ids: set[str]`
of qualified ids already claimed by games appended so far in this pass. When
`find_matching_game` returns a `match` for a `fresh_game`, check whether any of
`match.ids` are already in `used_ids` — that only happens when an earlier
fresh game in the *same* merge pass already claimed one of the same ids (i.e.
the case that produced the Steelrising duplicate). If so, reject the match:
append `fresh_game` itself instead (its own freshly-resolved ids stand), and
leave `match` in the `candidates` pool so it falls through to the normal
end-of-loop quarantine into `invalid` — nothing is silently dropped, it's
recoverable exactly like any other unmatched candidate today. After appending
each accepted game (whether `match` or `fresh_game`), extend `used_ids` with
its `ids`.

Extract the duplicate-id-detection logic currently inlined in
`GameList.validate_games` (`src/game_collections/models.py:147-157`, lines
154-156) into a small reusable helper (e.g. a module-level function in
`models.py`) that both the validator and a final defensive check at the end of
the `authoritative` branch in `merge_game_list` can call — a cheap
belt-and-suspenders assertion that the merged result really has no duplicate
ids, so a case the local `used_ids` guard doesn't anticipate fails loudly at
merge time instead of silently producing a corrupt commit again.

Update `merge_game_list`'s docstring (`common.py:196-203`) to describe this
new behavior, and add a short comment at the guard itself explaining why
(referencing this collision pattern), per the project's comment conventions.

### 3. CI — post-scrape validate (warning-only)

Add a step to `.github/workflows/weekly-humblebundle-scrape.yml` that runs
`uv run game-collections validate` after the crawl step. Per the confirmed
decision, this should warn/annotate but not fail the job or block the
commit/PR — match whatever pattern the workflow already uses for its existing
non-fatal notices (e.g. unresolved-count reporting). Check
`weekly-isthereanydeal-scrape.yml` for the same gap and add the equivalent
step there too if it's missing.

### 4. Tests — `tests/test_sources_common.py`

Add a regression test alongside the existing
`test_merge_game_list_authoritative_*` tests (same `Game`/`GameList`
construction style; add a `GameGroup` import from `game_collections.models`,
which isn't currently imported in this file):

```python
def test_merge_game_list_authoritative_rejects_a_fuzzy_match_that_would_duplicate_an_earlier_fresh_games_id() -> None:
    existing = _list(Game(name="Foo - Bar Edition", ids=["steam:1"]))
    fresh = _list(
        Game(name="Foo", ids=["steam:2"], group=GameGroup(id="foo_baredition", name="Foo - Bar Edition")),
        Game(name="Foo - DLC", ids=["steam:1"], group=GameGroup(id="foo_baredition", name="Foo - Bar Edition")),
    )

    merged = merge_game_list(existing, fresh, authoritative=True)

    identities = [identifier for game in merged.games for identifier in game.ids]
    assert len(identities) == len(set(identities))
    assert ("Foo", ["steam:2"]) in [(g.name, g.ids) for g in merged.games]
    assert ("Foo - DLC", ["steam:1"]) in [(g.name, g.ids) for g in merged.games]
    assert [g.name for g in merged.invalid] == ["Foo - Bar Edition"]
```

Before finalizing, verify `fuzz.WRatio("Foo", "Foo - Bar Edition")` actually
scores >= `FUZZY_MATCH_THRESHOLD` (90.0, the real bug's names scored exactly
90.0) — adjust the fixture strings if not, so the test genuinely exercises the
fuzzy tier rather than an earlier (id/name) tier.

If the `models.py` duplicate-id helper is extracted, add one small direct unit
test for it too (in whichever test file already covers `GameList`/`Game`
validators) confirming it flags a list with duplicate ids and returns nothing
for a clean list.

### Schema regeneration

Not needed — no Pydantic model shapes change, only file content and merge
algorithm behavior. `tests/test_schema.py` will confirm no drift.

## Verification

1. `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections validate` — confirm
   the whole `lists/` tree (including the 3 repaired files) loads cleanly.
2. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_sources_common.py -q`
   — new regression test passes, existing merge tests still pass.
3. `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` — full suite, confirm no
   regressions (schema drift test included).
4. Optionally re-run `env UV_CACHE_DIR=/tmp/uv-cache uv run game-collections scrape humblebundle --url https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection`
   (non-`--git`, so nothing is committed) to confirm the originally-reported
   crawl no longer crashes on load.
