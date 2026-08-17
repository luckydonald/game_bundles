In the repo /home/user/git/luckydonald/game_collections, I need to understand how tier numbers (tier-1.yml, tier-2.yml, tier-3.yml, bundle.yml, and the `tier:` field inside each GameList) are assigned by:
1. The humblebundle source (src/game_collections/sources/humblebundle/ — crawler.py, parser.py)
2. The isthereanydeal source (src/game_collections/sources/isthereanydeal/ — crawler.py, parser.py)

Specifically I need to know: for a Humble Choice/Games bundle with multiple pick-tiers, which tier number (1, 2, 3...) does each source assign to which conceptual tier (e.g., is the "full/entire" bundle tier numbered lowest or highest? are smaller item-count tiers numbered lower or higher?). Look for where filenames like `tier-{n}.yml` or `bundle.yml` get chosen, and where the `tier:` model field gets set, in both sources. Also check `src/game_collections/migrate_tiers.py` and `lists/README.md` for any documented convention on tier ordering/numbering, and `src/game_collections/models.py` for how `tier:` is defined/validated.

Also look at a couple of real example directories under `lists/humblebundle/` and `lists/isthereanydeal/` that have multiple tier files for the same bundle (if any exist) to see actual on-disk tier numbers versus item counts.

Report: the exact tier-numbering convention each source's code uses (with file:line references), whether they agree or actually differ, and what the "correct" convention should be per lists/README.md if documented. Keep the report under 400 words, factual, code-referenced.