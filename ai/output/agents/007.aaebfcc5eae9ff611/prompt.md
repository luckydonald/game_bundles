In repo /home/user/git/luckydonald/game_collections, I need full understanding of:

1. How the CLI currently determines the user's "owned games" library (the API-key-based lookup) — likely in src/game_collections/cli.py or src/game_collections/launchers/steam/*.py, for the `eligible steam` and `sync steam` commands.
2. How Steam "collections" are represented/read internally (models, io.py) — specifically how a collection like the internal `all` collection is parsed/read from Steam's local config (sharedconfig.vdf or similar), and what fields identify a collection by name/id.
3. Where CLI arguments for `eligible`/`sync` steam commands are defined (Typer options), especially anything related to API key, e.g. `--api-key` or similar.
4. Any existing tests related to owned-games source or collections in tests/ directory.

Report:
- File paths and line numbers for: the function/class that fetches owned games via Steam Web API, the function/class that reads Steam collections from local files, the Typer command definitions for `eligible steam` and `sync steam`.
- The exact data model/schema for a Steam collection entry (fields, types).
- How collections are keyed/looked up by name (is there a "manual-all" style naming, and is the internal `all` collection literally named "all"?).
- Any relevant SteamFileGateway methods for reading collections.
Be thorough with file:line citations. Do not modify any files.