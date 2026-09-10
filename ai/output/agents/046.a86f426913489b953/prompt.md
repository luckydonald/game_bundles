In this repo (/home/user/git/luckydonald/game_collections), I need to understand "bundle variation" files under lists/ — directories where a single bundle has multiple variation files (e.g. multiple tier/edition YAML files sharing one bundle folder), and how they currently reference shared metadata.

Please investigate and report back:
1. Search for the word "variation" across the repo (code, lists/*.yml, docs, models.py) — grep -ri "variation" in src/, lists/, and *.md files. Show what it means in this codebase.
2. Look at an example bundle folder that has multiple variation files — likely under lists/greenmangaming/, lists/humblebundle/, or similar (check migrate_tiers.py and its docstring/tests for "tier" and "variation" naming, plus bundle folders with tier-N.yml files). Show the actual directory listing and file contents of 2-3 example folders with multiple files (e.g., bundle.yml + tier-1.yml + tier-2.yml, or per-variation files) so I can see the current schema/duplication.
3. Read src/game_collections/models.py fully — the GameList/Game/etc Pydantic models, and any "tier" field on Game.
4. Read src/game_collections/migrate_tiers.py fully — since it's the last "flatten/rename" migration for tiers, its logic and docstring are highly relevant to how this new "merge bundle variations" migration should work.
5. Read src/game_collections/lists.py — path-derived ID logic and discovery, since we're going to flatten a folder level (remove one level of nesting) and merge multiple files.
6. Check src/game_collections/sources/README.md and any source that writes "variation" folders (e.g. greenmangaming or humblebundle) for how bundle variations currently get scraped/written — grep for "variation" in src/game_collections/sources/.
7. Look for any existing "combine"/"merge" tooling for lists (grep for "merge" in src/).

Report with concrete file paths, folder structures (tree output), and full or near-full file contents where relevant (models.py Game/GameList models, migrate_tiers.py, a couple of real variation-bundle YAML files). Be thorough — this is research for planning a new migration script. Keep the report data-dense but organized by the 7 points above.