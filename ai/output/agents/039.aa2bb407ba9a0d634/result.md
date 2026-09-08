## Implementation Plan

### Confirmed scope (verified, not just per the brief)

Running a full read-only validation sweep (`load_game_list` over every `lists/**/*.yml`) shows **exactly 3** corrupt files, all for the same bundle, all with the identical duplicate-ID shape:
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml`
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-2.yml`
- `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-3.yml`

No other list in the repo is affected. `game-collections validate` only ever reported `tier-1.yml` because `discover_game_lists` (`src/game_collections/lists.py:71-97`) loads files in sorted path order and raises on the *first* failure — `tier-1.yml` sorts before `tier-2.yml`/`tier-3.yml`, so those two were masked and would only have surfaced once `tier-1.yml` was fixed.

**Why `validate` never caught this at commit time:** `.github/workflows/weekly-humblebundle-scrape.yml` runs `scrape humblebundle --non-interactive --git --git-style auto`, then only checks `git status`/pushes/opens a PR — there is no `game-collections validate` step anywhere after the crawl. So a corrupting merge (as analyzed in the prompt) commits straight to the PR branch with nothing catching it before humans review/merge. This is a real gap, independent of the merge-logic fix, and should be closed too.

**isthereanydeal-id precedent for grouped games:** grepping `lists/humblebundle` for files with both `group:` and `isthereanydeal`, the only split-group in the repo (`pathfinder_wrathoftherighteous_gameoftheyearedition` in `2026-09-02_crpg-pack-isometric-immersion`) has **no** member carrying an `isthereanydeal:` id — none of its 12 split rows has one, only the sibling *ungrouped* games in the same file (Black Geyser, Torment, etc.) carry `isthereanydeal:` ids directly on the `Game`. So there's no exact precedent for "grouped split member carries an itad id." `GameGroup` (models.py:56-61) has no `ids` field to hang it off the group itself. The most natural repair, consistent with the file's own later state at `2026-09-19` (base game named "Steelrising", `steam:1283400`, grouped, first among its siblings), is to keep `isthereanydeal:steelrising-bastille-edition` on that same base "Steelrising" entry, since it is the entry that most directly represents "the edition" as resolved by ITAD's title match. Flagging this as the one open question needing a human nod, since it's a modeling judgment call, not a mechanically-derived fact.

---

### 1. Data repair — 3 files, same edit in each

In each of `tier-1.yml`, `tier-2.yml`, `tier-3.yml` under `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/`, replace:

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

Leave the existing "Steelrising - Discus Chain" (`steam:2021370`, grouped) and "Steelrising - Cagliostro's Secrets" (`steam:2004261`, grouped) entries untouched in all three files — they were already correct. After the edit, re-run `game-collections validate` (or the same read-only Python sweep used above) to confirm all three files — and the whole `lists/` tree — pass.

No other files need touching for the data-repair step.

### 2. Merge-logic hardening — `src/game_collections/sources/common.py`

Recommended approach: **narrow, targeted duplicate-ID guard in the `authoritative=True` branch of `merge_game_list`**, not a broader rewrite of `find_matching_game`. Rationale: the group-aware alternative (reasoning about whole split-sets before fuzzy-matching) is considerably more invasive for a fuzzy-match cascade that already works correctly in every other observed case (the "Collection One/Three" numbered-installment fix already narrowed it once via `_number_tokens`); the actual failure mode here is generic — *any* fuzzy match, in any source, can in principle hand a fresh game a stale candidate's `ids` that collide with another fresh game's own ids — so the fix belongs at the point where the merged list's final ID set is known, which is only after the whole `authoritative` loop completes.

Concretely:

- **Extract a small reusable helper** in `src/game_collections/models.py`, e.g. `duplicate_qualified_ids(games: Iterable[Game]) -> list[str]` (or similar name matching project style), that returns the list/set of qualified-ID strings appearing on more than one game — the same logic currently inlined in `GameList.validate_games` (models.py:148-152). Have `validate_games` call it instead of inlining, and have `merge_game_list` import and call the same helper. This avoids duplicating the dedup logic per CLAUDE.md's don't-repeat-yourself norm, and keeps the validator and the merge-time check provably in sync.
- In `merge_game_list`'s `authoritative=True` loop (common.py:219-227), after computing `match` via `find_matching_game`, before accepting it: build the candidate's post-merge ID set against everything appended to `merged_games` **so far** (a running `set[str]` of qualified ids used across all already-decided fresh games), plus, importantly, against the *remaining* fresh games' own ids too. Simpler and sufficient: keep a running `used_ids: set[str]` seeded empty; for each `fresh_game`, if `find_matching_game` returns a `match` whose `ids` overlap `used_ids` (i.e., a fresh game earlier in this same pass already claimed one of the same qualified IDs — which is exactly what happened with the two Steelrising splits both landing on `steam:2021370`), **treat the match as invalid**: don't consume it from `candidates`, and instead append `fresh_game` itself (its own freshly-resolved ids stand), leaving the original stale `match` in `candidates` to fall through to the final `invalid` quarantine as normal (matching the existing "unmatched candidate → invalid" behavior, so nothing is silently dropped — it's recoverable exactly like the existing quarantine path).
- After appending each accepted game (whether `match` or `fresh_game`), extend `used_ids` with its `ids`.
- This is a strictly *local* fix scoped to "a match this pass already handed to an earlier fresh game in the same batch," not a general re-validation/backtracking pass — it doesn't need the full extracted duplicate-checker inside the loop itself (that would be O(n²) per iteration and overkill); the extracted `models.py` helper is used only for a final sanity assertion at the very end of the authoritative branch (defensive belt-and-suspenders, should never fire given the above, but cheap and turns "we missed a case" into a loud `AssertionError`/`ValueError` at merge time instead of a silent corrupt commit slipping through again).

- **Docstring update**: `merge_game_list`'s `authoritative=True` paragraph (common.py:196-203) needs a sentence added describing this: e.g. "...if accepting a matched candidate would reintroduce a qualified ID a fresh game already claimed earlier in this same pass, the match is rejected instead: the fresh game keeps its own ids, and the stale candidate remains in the pool to be quarantined into `invalid` like any other unmatched game." Also add a short comment at the point of the check itself explaining *why* (referencing the Steelrising-style collision as the motivating case), per CLAUDE.md's "add comments that explain bigger algorithms."

### 3. CI gap — add a `validate` step post-scrape

Add a step to `.github/workflows/weekly-humblebundle-scrape.yml` (and check `weekly-isthereanydeal-scrape.yml` too, since it presumably has the same gap) that runs `uv run game-collections validate` after the crawl and before/alongside the "Check for changes"/push steps. If it fails, the workflow should fail loudly (not open/update the PR silently) — exact placement: right after "Run Humble Bundle crawler" and before "Commit any files --git missed"/push, so a validation failure surfaces as a red CI run rather than a green PR containing corrupt data. This is a good candidate for the same PR as the merge-logic fix, since it's the mechanism that should have caught exactly this bug.

### 4. Tests — `tests/test_sources_common.py`

Add a regression test near the existing `test_merge_game_list_authoritative_*` tests (same file, same `_list`/`Game`/`GameGroup` construction style already used there — no new fixture files needed):

```python
def test_merge_game_list_authoritative_rejects_a_fuzzy_match_that_would_duplicate_an_earlier_fresh_games_id() -> None:
    """Regression for a real corrupted commit: an ungrouped pre-split candidate's name
    fuzzy-matched one grouped split member, but that split member's *sibling* in the same
    fresh crawl already carried the exact same (correct) id the stale candidate itself held -
    accepting the match would duplicate that id across two Games in the same list."""
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

Tune the two fixture names so `fuzz.WRatio("Foo", "Foo - Bar Edition")` is actually ≥ `FUZZY_MATCH_THRESHOLD` (90.0) — the real bug used `"Steelrising"` vs `"Steelrising - Bastille Edition"` which scored exactly 90.0; verify the chosen test strings score similarly before finalizing (quick `python -c "from rapidfuzz import fuzz; print(fuzz.WRatio(...))"` check), otherwise the test won't actually exercise the fuzzy tier.

Also add a `Game`/`GameGroup` import if not already present at the top of `tests/test_sources_common.py` (currently imports `Game, GameList, Reference` from `game_collections.models` — `GameGroup` needs adding).

If the `models.py` duplicate-ID helper is extracted, add one small direct unit test for it too (either in `tests/test_models.py` if that file exists, or alongside `GameList` validator tests) confirming it returns the colliding IDs for a list with duplicates and an empty result otherwise — check `tests/` for the actual existing models test file name before deciding where it goes.

### 5. Schema regeneration — confirmed not needed

`Game`, `GameGroup`, `GameList` field shapes are unchanged (no new/removed/retyped fields) — only merge algorithm behavior and file *content* change, not the Pydantic model shape `schemas/game-list.schema.json` is generated from. `tests/test_schema.py` (drift detector) will confirm this passes as-is; no `game-collections schema` regen step is needed in this change.

---

### Open questions requiring a human decision

1. **isthereanydeal id placement**: confirmed no exact repo precedent for a grouped split member carrying an `isthereanydeal:` id (the one other split group in `lists/humblebundle` has none on any member). Proposed default: keep it on the base "Steelrising" entry (matches the `2026-09-19` file's shape for the base game). Needs a human nod since it's a modeling call, not a mechanically derived fact.
2. **Scope of the merge-logic hardening**: the plan above is deliberately narrow (reject only same-pass id collisions between the currently accepted match and already-processed fresh games this pass) rather than a fully general "any post-merge duplicate anywhere" fix. Confirm that's the desired scope versus wanting the broader defensive assertion at the end of the authoritative branch to be a hard error (fails the whole crawl) rather than best-effort local avoidance — I've recommended both (local avoidance during the loop, plus a cheap final assertion as a last-resort net), but which of those two should be considered "the fix" versus "an extra safety net" is worth confirming explicitly.
3. **CI validate placement**: whether a validate failure should also block the automatic push/PR-open (recommended: yes, fail the job) or just annotate a warning like the existing unresolved-count handling does — worth a human decision since the existing workflow generally prefers "still commit whatever it produced" over hard failures.

### Critical Files for Implementation
- /home/user/git/luckydonald/game_collections/lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml
- /home/user/git/luckydonald/game_collections/lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-2.yml
- /home/user/git/luckydonald/game_collections/lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-3.yml
- /home/user/git/luckydonald/game_collections/src/game_collections/sources/common.py
- /home/user/git/luckydonald/game_collections/src/game_collections/models.py
- /home/user/git/luckydonald/game_collections/tests/test_sources_common.py
- /home/user/git/luckydonald/game_collections/.github/workflows/weekly-humblebundle-scrape.yml