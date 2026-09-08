In the repo /home/user/git/luckydonald/game_collections, find the Pydantic validation logic for GameList that raises: "Value error, list contains duplicate qualified game IDs". This is likely in src/game_collections/models.py.

Report:
1. The exact validator code (file path + line numbers) that checks for duplicate qualified game IDs, and what "qualified game ID" means (how it's computed per game entry - which fields feed into it).
2. Where this GameList model is used for validation when writing scraped files (search for calls to this model or "invalid game list" error message in the humblebundle scraping code, likely under src/game_collections/sources/humblebundle/).
3. Any related models/fields like `requires`, `ids`, storefront identifiers, etc. that are part of the qualified ID computation.

Be thorough and quote the actual code with line numbers. This is read-only research, do not edit anything.