In the repo /home/user/git/luckydonald/game_collections, investigate a bug: running `game-collections scrape humblebundle` produced this error:

```
error: https://www.humblebundle.com/games/dread-and-dark-fantasies-rpg-collection: invalid game list lists/humblebundle/bundle/2026-08-31_dread-and-dark-fantasies-rpg-collection/tier-1.yml:
1 validation error for GameList
  Value error, list contains duplicate qualified game IDs [type=value_error, input_value={'schema': 1, 'name': 'Dr...een'], 'requires': []}]}, input_type=dict]
```

This means the humblebundle crawler/parser produced two game entries in the same tier that have the same "qualified game ID" (name + platform tags, or similar dedup key — check models.py for the exact definition used by GameList's validator). 

Please investigate:
1. Look at src/game_collections/sources/humblebundle/ — the crawler, parser, and how it builds up the list of games per tier (likely parser.py or similar file producing Game entries for a bundle page).
2. Check if there's existing archived/cached data for "dread-and-dark-fantasies-rpg-collection" under archives/humblebundle/ that shows what the actual duplicate games look like (search for "dread" or "dark-fantasies" in archives/humblebundle/ and lists/humblebundle/).
3. Determine the likely root cause of how two entries with the same qualified ID could arise from parsing a single Humble bundle page - e.g. same game listed twice with different tiers/platforms, or a listing that appears as both a "played on multiple platforms" variant, or truly a duplicate listing bug on humblebundle.com itself, or a parsing bug that emits duplicate <a> tags.
4. Check git log / recent commits for humblebundle parser for related recent changes (e.g. commit 3f8ef1e4f mentions fixing HumbleLink URL validation crash - is there something related about duplicate handling either already handled elsewhere, e.g. for other bundles, that this bundle's page structure breaks?).
5. Look for any existing deduplication logic already present elsewhere in the codebase (e.g. merging entries with the same qualified ID by merging their `requires` list) that might need to be applied at parse time here too.

This is read-only research — do not edit any files. Report back with concrete file paths, line numbers, and quoted code/data showing the duplicate game entries so I can design a fix.