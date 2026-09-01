In this repo (/home/user/git/luckydonald/game_collections), I need full detail on:

1. The `complete` CLI command in src/game_collections/cli.py (around line 350-432) — read the full function body, its options (file, --store, --provider, --mode blank|missing|unresolved|refetch_all, --non-interactive if any, --refresh, --no-cache etc.), and how it calls complete_game_list from src/game_collections/search.py.

2. src/game_collections/search.py — read complete_game_list, completion_mode, selected_providers fully, and any relevant helper functions/types they use.

3. src/game_collections/lists.py — how game lists are discovered/enumerated on disk (function(s) that list all list files under lists/), and how list IDs relate to file paths. I want to know how to iterate "all draft/incomplete list files in the repo" similar to how `validate` or `migrate-tiers` commands iterate all lists.

4. Look at the `validate` command and `migrate-tiers` command in cli.py to see the existing pattern for "operate over all lists in the repo" (iterating discover functions, error handling, progress reporting style).

5. Check tests/test_cli.py or similar for any existing tests of the `complete` command, to understand testing patterns.

6. Check README.md and lists/README.md for how `complete FILE` is documented, since a new `--all` flag would need matching doc updates there.

Report back: 
- the complete_command function signature and full body (or a clear paraphrase with line numbers)
- the discovery function(s) available for enumerating all list files (name, file, signature, behavior — does it return draft/incomplete lists distinctly? how would we detect a list still needs `complete` i.e. has draft/unresolved ids?)
- the exact mode semantics for blank/missing/unresolved/refetch_all
- how errors/failures currently propagate (does it raise on first error, or continue?)
- how progress/logging is done for multi-item operations elsewhere (scrape logs "Bundle x/y" etc — is there a similar existing loop pattern to reuse)
- relevant line numbers throughout since I'll need them for the plan file.
