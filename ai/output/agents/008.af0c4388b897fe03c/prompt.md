In this Python repo (game_collections), I need a map of the `sync steam` / `eligible steam` CLI flow to plan a new TUI command `game-collections apply`.

Report with file:line citations:
1. src/game_collections/cli.py — the full `sync` and `eligible` command implementations (options, flow, what functions they call).
2. src/game_collections/launchers/base.py — the adapter registry interface, and the semantic "plan" types (what a sync plan / candidate looks like: fields like list id, tier, owned ids, bundle size, date, etc.)
3. src/game_collections/launchers/steam/adapter.py — how it builds the plan: how it discovers eligible lists, filters by tiers highest/all, computes ownership matches, and what --apply staging/backup does (just describe at a high level with file:line, no need to quote everything).
4. src/game_collections/lists.py — how lists are discovered/loaded, and whether bundle metadata (source, date, item count) is available on the loaded object or has to be derived (e.g. from directory name or archive metadata.json).
5. Whether there's any existing TUI/interactive prompt library already used in the repo (check pyproject.toml dependencies and any existing interactive prompts in cli.py or sources, e.g. for the humble scrape's manual ID resolution prompts).

Be thorough, read full functions. This is for planning a new feature, not implementing yet.