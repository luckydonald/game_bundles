Repo: /home/user/git/luckydonald/game_collections (Python 3.14, Pydantic-validated YAML game lists + launcher sync tool). Read CLAUDE.md at the repo root first for project conventions (in particular: every indentation level closed with `# end if`/`# end for`/`# end def`/etc comments, no `_`-prefixed private names, new concerns get their own module, early returns preferred).

## Confirmed root cause (already investigated, do not re-investigate from scratch — verify by reading the exact files/lines named below, then design the fix)

`game-collections scrape humblebundle --git` fails with:
```
error: https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection: invalid game list lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml:
1 validation error for GameList
  Value error, list contains duplicate qualified game IDs
```

This is thrown by `GameList.validate_games` (src/game_collections/models.py:147-157), which errors if the same `provider:value` qualified ID (from any `Game.ids`, computed via `Game.qualified_ids`, models.py ~63-105) appears on more than one `Game` in the list. It's raised while `load_game_list` (src/game_collections/lists.py:52-68) reads the **already-committed** file at `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml` — this load happens inside `_write_merged_game_list` (src/game_collections/sources/humblebundle/crawler.py:271-285, specifically line 282: `existing = load_game_list(path, lists_root).data if path.exists() else None`) before any fresh merge is attempted. So the committed file itself is already corrupt; any future scrape of this bundle will always hit this error at load time.

I already read the corrupt file. Its `games:` list currently is:
```yaml
- name: Steelrising - Bastille Edition
  ids:
  - steam:2021370
  - isthereanydeal:steelrising-bastille-edition
  requires: []
- name: Steelrising - Discus Chain
  ids:
  - steam:2021370
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: Steelrising - Cagliostro's Secrets
  ids:
  - steam:2004261
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: The Axis Unseen
  ids:
  - steam:1807810
  - isthereanydeal:the-axis-unseen
  requires: []
```
`steam:2021370` appears twice: once on "Steelrising - Bastille Edition" (wrong — that ID actually belongs to the "Discus Chain" DLC) and once correctly on "Steelrising - Discus Chain". The base game "Steelrising" itself is `steam:1283400` — confirmed both via `archives/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/metadata.json` (`resolution.splits`) and via a sibling, uncorrupted listing for the same offer at a later crawl date, `lists/humblebundle/bundle/2026-09-19_dread-and-dark-fantasies-rpg-collection/tier-1.yml`, which I also read and looks like this (the correct shape for a 3-way split of "Steelrising - Bastille Edition"):
```yaml
- name: Steelrising
  ids:
  - steam:1283400
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: Steelrising - Discus Chain
  ids:
  - steam:2021370
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: Steelrising - Cagliostro's Secrets
  ids:
  - unresolved:source:humblebundle:steelrising_bastilleedition::3
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: The Axis Unseen
  ids:
  - unresolved:source:humblebundle:axisunseen
  requires: []
```
(Note: in the 2026-09-19 file "Cagliostro's Secrets" and "The Axis Unseen" happen to still be unresolved — that's just because that later crawl hadn't resolved them yet; it doesn't need to be copied verbatim. What matters is the *shape*: base game named "Steelrising" grouped under `steelrising_bastilleedition`/"Steelrising - Bastille Edition", with id `steam:1283400`.)

**How the corruption was created (mechanism, already traced through git log and code):**
1. Commit `b3971cf61` (2026-09-01) first crawled this bundle *before* the resolver had "split Editions into base+DLC" logic (that logic was added later in commit `ff6ff696e`, src/game_collections/sources/humblebundle/resolver.py:401-483). At that time "Steelrising - Bastille Edition" was resolved as one single Steam ID, and the resolver picked the wrong Steam app (`2021370`, actually the Discus Chain DLC, instead of `1283400`, the base game). That wrong single-entry got committed.
2. Commit `9294debd3` (2026-09-02) re-ran the crawl after the split-aware resolver landed. This time the resolver correctly produced 3 separate split `Game`s (`_games_for_item`, src/game_collections/sources/humblebundle/crawler.py:258-268): "Steelrising"→1283400, "Steelrising - Discus Chain"→2021370, "Steelrising - Cagliostro's Secrets"→2004261. But because the file already existed, `_write_merged_game_list` (crawler.py:271-285) merged these 3 fresh games against the 1 stale existing "Bastille Edition" entry via `merge_game_list(existing, fresh, authoritative=True)` (src/game_collections/sources/common.py:184-231).
3. Inside that authoritative merge, each fresh game is matched against remaining candidates via `find_matching_game` (common.py:143-181), which tries id-overlap, then exact name, then normalized name, then fuzzy `fuzz.WRatio` (threshold `FUZZY_MATCH_THRESHOLD`, defined near the top of common.py — check its exact value). I confirmed:
   - `fuzz.WRatio('Steelrising', 'Steelrising - Bastille Edition') == 90.0` — exactly at/above threshold, so the fresh "Steelrising" (base game, `steam:1283400`) fuzzy-matched the stale "Steelrising - Bastille Edition" candidate (`steam:2021370`).
   - The other two fresh split names scored well below threshold against the same candidate (64.3 and 59.4).
4. Per `merge_game_list` lines 219-226, on a match the code appends **the existing candidate object itself** (`merged_games.append(match)` at line 225), not the fresh game — i.e. on a fuzzy match, the *stale* `ids`/`group` are kept and the fresh, correctly-resolved data is discarded entirely (this is deliberate elsewhere, to preserve manual curation of `ids:`/`group:`, but here it preserves a wrong legacy value instead). The matched candidate is also removed from the pool (line 224), so it can't be matched again.
5. Net effect: the merged list ends up with "Steelrising - Bastille Edition" keeping its stale wrong `steam:2021370`, AND a separate fresh "Steelrising - Discus Chain" entry also carrying `steam:2021370` (correctly, this time) — producing the duplicate that later fails validation. The base game's correct id (`steam:1283400`) is lost entirely from the file.

There is currently no post-merge validation in `merge_game_list`/`find_matching_game` that catches an ID collision produced this way, and no logic that prefers a group-aware match (matching split siblings that share `group.id` as a set, rather than fuzzy-matching one split member's bare name against the pre-split edition title) over the generic fuzzy fallback.

## What needs a plan

Two independent fixes:

1. **Data repair**: fix the already-committed `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml` so "Steelrising - Bastille Edition" becomes "Steelrising" with `ids: [steam:1283400]`, grouped under `steelrising_bastilleedition`/"Steelrising - Bastille Edition" like its siblings (matching the 2026-09-19 shape), and keep the `isthereanydeal:steelrising-bastille-edition` id somewhere sensible (check whether the base "Steelrising" game or the group parent should carry it — look at how `isthereanydeal` ids attach to grouped games elsewhere in `lists/humblebundle/` for precedent, e.g. `grep -rl "group:" lists/humblebundle | xargs grep -l isthereanydeal` or similar). Also check whether any *other* committed humblebundle list files have the same corruption pattern (an ungrouped edition-titled entry whose id collides with a grouped sibling's id, or more generally any list that would fail `GameList.validate_games` if reloaded) — write a quick read-only check (e.g. a small script using `GameList.model_validate` over every `lists/humblebundle/**/*.yml`, or check if `game-collections validate` already covers/would already have caught this — if it does, explain why this one file evaded it, e.g. maybe `validate` doesn't get run in CI post-scrape, or does but this file was committed before a validate step, etc.) — read `src/game_collections/cli.py`'s `validate` command and `.github/workflows/` (or wherever the scheduled scrape workflow lives, per CLAUDE.md's "scheduled GitHub Actions scrape (Humble only)") to see if `validate` runs after `scrape --git` and if not, whether it should.

2. **Merge-logic hardening** in `src/game_collections/sources/common.py` (`merge_game_list`/`find_matching_game`) so this class of corruption can't recur silently. Design an approach and pick ONE, with rationale, from options like:
   - After building `merged_games` in the `authoritative=True` branch, validate no duplicate qualified IDs exist across the result (mirroring `GameList.validate_games`'s dedup logic — check if that logic should be extracted into a small reusable helper in models.py that both the validator and this check can call, to respect the project's don't-repeat-yourself/no-duplicate-logic norms) — and if a collision is found, treat the fuzzy match that caused it as a false positive: put the stale candidate back into `invalid` (or otherwise don't let it consume/clobber a fresh game's ids), and let the fresh game's own (correctly resolved) ids stand instead.
   - Make `find_matching_game` group-aware: when multiple `fresh_game`s in the same merge pass share the same `group.id`, treat them as a set that together replaced a candidate; only fuzzy-match into a pre-split, ungrouped candidate if reasoning about the whole split group (rather than one member's bare title) makes it a good match — or simply refuse to consume an ungrouped candidate's `ids` values for a fresh game if doing so would introduce a new duplicate that didn't exist before the merge.
   - Something narrower/simpler if you find one — favor minimal, targeted logic over a broad rewrite; this is a bug-fix, not a redesign of the merge algorithm. Don't add speculative generality beyond what's needed to close this hole.

   Whichever approach you choose, make sure `merge_game_list`'s docstring (lines 184-203) still accurately describes the new behavior — the project's CLAUDE.md explicitly says to keep comments accurate and add value, not just leave stale ones.

3. **Tests**: identify (don't necessarily enumerate every one, but name the file) which existing test file(s) cover `merge_game_list`/`find_matching_game` (likely `tests/test_sources_common.py` or similar — check `tests/` for the actual name) and design a regression test reproducing this exact scenario: an existing ungrouped single-entry candidate, a fresh `GameList` with 3 grouped split members where one's fuzzy-matches the candidate's name, asserting the merge result has no duplicate qualified IDs and preserves the fresh split's correct ids. Also check `tests/fixtures/` for how humblebundle merge fixtures are structured if any exist, to follow existing conventions rather than inventing a new fixture style.

Also check whether `schemas/game-list.schema.json` or the humblebundle archive schema need regeneration — they shouldn't, since no model shape is changing, just data content and merge logic, but confirm this is true rather than assuming.

Produce a concrete, ordered implementation plan: exact files to touch, the specific logic to add/change (describe the code, don't necessarily write full diffs), the data repair diff for the corrupted YAML file, and the test(s) to add. Flag any open question that needs a human decision (e.g. exactly how to represent the isthereanydeal id on the repaired entry, or whether merge-logic hardening should be scoped to just this collision type vs a more general post-merge duplicate check).