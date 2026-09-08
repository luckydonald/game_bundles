## Summary

The crash is **not** happening while parsing a fresh Humble Bundle page — it happens the moment the crawler tries to load the *already-committed* list file at `lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml`, because that file **already contains the duplicate `steam:2021370` ID** (baked in by a previous crawl run, commit `9294debd3`, on 2026-09-02). Any future re-scrape of this bundle will always hit this error until the file is fixed, since simply loading it fails Pydantic validation before any new page is even fetched.

## Where the error actually comes from

- `src/game_collections/lists.py:52-68` (`load_game_list`) wraps a `pydantic.ValidationError` as:
  `ListLoadError(f"invalid game list {path}:\n{error}")` — this is verbatim the message format in the reported error.
- `src/game_collections/models.py:147-157` (`GameList.validate_games`) is what raises `"list contains duplicate qualified game IDs"`, computed from `identities = [identifier.compact() for game in self.games for identifier in game.qualified_ids]` (dedup key = `provider:value`, e.g. `steam:2021370` — name is irrelevant here, only IDs).
- `load_game_list` is called from `src/game_collections/sources/humblebundle/crawler.py:271-285` (`_write_merged_game_list`), specifically line 282: `existing = load_game_list(path, lists_root).data if path.exists() else None`. This load of the *existing* file is what throws.

## The duplicate itself

`lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml` currently contains:

```yaml
- name: Steelrising - Bastille Edition
  ids:
  - steam:2021370            # <-- WRONG: this is actually the "Discus Chain" DLC's app id
  - isthereanydeal:steelrising-bastille-edition
  requires: []
- name: Steelrising - Discus Chain
  ids:
  - steam:2021370             # <-- duplicate of the line above
  group:
    id: steelrising_bastilleedition
    name: Steelrising - Bastille Edition
  requires: []
- name: Steelrising - Cagliostro's Secrets
  ids:
  - steam:2004261
  group: {id: steelrising_bastilleedition, name: Steelrising - Bastille Edition}
  requires: []
```

The correct mapping (per the current archive, `archives/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/metadata.json`, `resolution.splits`) is:
```
"Steelrising"                       -> steam:1283400   (base game)
"Steelrising - Discus Chain"        -> steam:2021370   (DLC)
"Steelrising - Cagliostro's Secrets"-> steam:2004261   (DLC)
```
So the top-level "Steelrising - Bastille Edition" entry should have id `steam:1283400`, not `steam:2021370`.

A sibling bundle listing for the *same* Humble offer under a different date key, `lists/humblebundle/bundle/2026-09-19_dread-and-dark-fantasies-rpg-collection/tier-1.yml`, shows what a **correct**, uncorrupted split looks like (three separate grouped games, "Steelrising" with `steam:1283400`, no dup) — because for that path there was no pre-existing file to merge against.

## Root cause: two bugs, chained by history

**Bug 1 (historical, now baked into data):** the very first crawl of this bundle, commit `b3971cf61` (2026-09-01), predates the "split Editions into base+DLC" resolver logic (added later in commit `ff6ff696e`, `src/game_collections/sources/humblebundle/resolver.py:401-483`). At that time the whole "Steelrising - Bastille Edition" title was resolved as a single Steam ID, and the resolver/steamdb search matched the wrong app — landing on `2021370` (the "Discus Chain" DLC) instead of the base game `1283400`. That wrong single ID got committed as-is.

**Bug 2 (the actual mechanism that created the duplicate):** on 2026-09-02, commit `9294debd3` re-ran the crawler after `ff6ff696e`'s split-aware resolver went live. This time the resolver correctly produced 3 split games for `steelrising_bastilleedition` (`Steelrising`→1283400, `Discus Chain`→2021370, `Cagliostro's Secrets`→2004261) via `_games_for_item` in `src/game_collections/sources/humblebundle/crawler.py:258-268`. But this bundle already had a committed file, so `_write_merged_game_list` merged the fresh split games against the stale single "Bastille Edition" entry using **authoritative merge**:

- `src/game_collections/sources/common.py:184-231` (`merge_game_list`, `authoritative=True` branch, used by Humble) and
- `src/game_collections/sources/common.py:143-181` (`find_matching_game`)

`find_matching_game` tries ID overlap first (none — `1283400` vs `2021370`/`isthereanydeal:...`), then exact/normalized name (no match for "Steelrising" vs "Steelrising - Bastille Edition"), then **fuzzy title match** (`fuzz.WRatio`, threshold 90.0). I verified this directly:

```
fuzz.WRatio('Steelrising', 'Steelrising - Bastille Edition')                    == 90.0   # exactly at threshold -> MATCH
fuzz.WRatio('Steelrising - Discus Chain', 'Steelrising - Bastille Edition')     == 64.3   # no match
fuzz.WRatio("Steelrising - Cagliostro's Secrets", 'Steelrising - Bastille Ed.') == 59.4   # no match
```

So the fresh, correctly-resolved "Steelrising" (`steam:1283400`) fuzzy-matches the stale "Steelrising - Bastille Edition" candidate. Per `merge_game_list` line 224-225, on a match the code appends **the existing/candidate Game, not the fresh one** — i.e. it deliberately preserves the old (here, wrong) `ids`/`group` state. That old candidate is then consumed (`candidates.remove(match)`), so it's no longer available to match anything else.

The other two fresh split entries, "Discus Chain" (`steam:2021370`) and "Cagliostro's Secrets" (`steam:2004261`), find no remaining candidate to match (the only Steelrising-related candidate was just consumed), so they're appended as brand-new `Game`s. Net result: `steam:2021370` now appears twice — once from the wrongly-preserved legacy "Bastille Edition" entry and once from the legitimately new "Discus Chain" entry — which is exactly the corrupted file we see committed.

## Supporting evidence

- `config/humblebundle-store-ids.yml:604-610` shows the resolver's ID cache for this machine name, confirming the split index mapping used at some point in time:
```
steelrising_bastilleedition::1:
- steam:1283400
steelrising_bastilleedition::2:
- steam:2021370
steelrising_bastilleedition::3:
- unresolved:source:humblebundle:steelrising_bastilleedition::3
```
- Git history of the file (`git log -p --follow -- lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml`) shows the exact progression: `b3971cf61` created the single mis-resolved entry, `9294debd3` added the two new split entries alongside it without touching/replacing it.
- Commit `3f8ef1e4f` ("Fixed HumbleLink URL validation crash on whitespace-padded donation links") is a *different*, unrelated bug fixed 6 minutes before `9294debd3` on the same day; it's what allowed this bundle's crawl to get far enough to run the merge at all (it had previously been aborting on a `HumbleLink` URL-validation crash for this same offer), but it did not touch merge/dedup logic.
- No existing deduplication/reconciliation logic currently exists in `merge_game_list`/`find_matching_game` to detect or resolve an ID collision produced by matching an ungrouped legacy entry against one member of a freshly-split group — this is a gap, not a currently-handled case elsewhere.

## Design implications for a fix

Two independent things likely need fixing:
1. **Data repair**: fix the already-committed `tier-1.yml` (and any other bundle affected the same way) — change "Steelrising - Bastille Edition"'s id from `steam:2021370` to `steam:1283400` (and probably convert it into the proper 3-way `group` structure, matching the `2026-09-19` listing's shape).
2. **Merge logic**: `merge_game_list`'s authoritative path (`src/game_collections/sources/common.py:184-231`) needs to either (a) validate that the merged result has no duplicate qualified IDs before returning, and fall back to preferring the fresh data (or the fresh split's own id) when a collision is detected, or (b) tighten `find_matching_game`'s fuzzy tier so it doesn't match a bare title against an edition/bundle title that's about to be split into multiple sub-games (e.g. skip fuzzy matching for `fresh_game`s that will become `group` members, or require the *candidate* not to be a superstring/edition of `fresh_game.name` at the fuzzy tier), and/or (c) when a fresh `Game` carries a `group`, prefer matching against existing candidates that already share that same `group.id` before falling through to fuzzy title matching.