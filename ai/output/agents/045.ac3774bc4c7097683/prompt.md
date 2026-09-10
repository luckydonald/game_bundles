In the repo /home/user/git/luckydonald/game_collections, I'm investigating a scrape error log (ai/errors/7.txt) with lines like:

Bundle 20/22: 2k-collection
Bundle 21/22: destiny-2-expansion-bundle-2025
...
error: 2k-collection: 1 validation error for GameList
  Value error, list contains duplicate game names [type=value_error, ...]
error: destiny-2-expansion-bundle-2025: 1 validation error for GameList
  Value error, list contains duplicate game names [type=value_error, ...]

Also earlier lines: "unresolved: 332", "unresolved: 333", "unresolved: 337", "unresolved: 346" (these look like numeric unresolved marker ids/counts logged during the scrape).

I need to find:
1. Which scrape source(s) this log is from. Slugs like "2k-collection", "destiny-2-expansion-bundle-2025", "warhammer-collection-bolts-blades", "the-gearbox-collection" — these look like Humble Bundle "Games" bundle slugs (not Humble Choice) or possibly isthereanydeal-driven. Search src/game_collections/sources/humblebundle/ and src/game_collections/sources/isthereanydeal/ for where a CLI logs "Bundle X/Y: <slug>" and "(cached)" and "Archived <NAME>: N file(s)" and "unresolved: <n>" and "Wrote N file(s) for N offer(s); N unresolved game(s)." — find the exact source file and function producing this log format.
2. Find where "list contains duplicate game names" validation error comes from — likely a Pydantic validator in src/game_collections/models.py on GameList checking for duplicate names among `games`.
3. Find where that particular source builds the list of Game entries for a bundle — i.e., where duplicate game names could arise (e.g., same game title appearing twice in a bundle because of separate DLC/edition entries, or a parser bug listing an item twice, or games with identical display names but different store IDs).
4. Report the relevant file paths, function names, and line numbers for all of the above, and any dedup logic that already exists elsewhere (e.g. in other sources) that could be reused as a pattern.

Do not write any code. Just report findings with file:line references, in under 400 words.