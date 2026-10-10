Repo: /Users/user/Documents/programming/Python/game_bundles (read-only exploration, medium breadth). Investigate the root causes of these scrape errors (from ai/errors/9.md) and report file paths + line numbers + the relevant code:

Humble Bundle scraper (src/game_collections/sources/humblebundle/):
1. `https://www.humblebundle.com/games/dying-light-2-stay-human-complete-dlc-bundle: Steam URLs must use store.steampowered.com` - find where this message is raised (probably a Pydantic validator in models / ids) and what Steam URL form (e.g. steamcommunity.com, store.steampowered.com/sub/, other host) humble pages likely contain, and how the humble parser/resolver extracts steam URLs.
2. `https://www.humblebundle.com/games/make-play-games-in-godot-software: 1 validation error for GameList / games: List should have at least 1 item after validation, not 0` - a bundle with zero games (software bundle?). Find how the humble crawler builds the GameList, how empty bundles are or should be handled (skip with warning vs error), and whether similar handling exists elsewhere (e.g. other sources skipping empty bundles).

Deku Deals scraper (src/game_collections/sources/dekudeals/ - find it):
3. `bundle page has an unrecognized tiering_style: 'all_one_price'` - find where tiering_style is parsed/mapped and what styles are recognized; figure out what 'all_one_price' should map to (single-tier bundle?).
4. `item page has no storefront links: https://www.dekudeals.com/items/...?platform=all` - find where raised; consider whether items without storefront links (DLC/goodies packs, etc.) should be skipped with a warning or yield an unresolved marker, and how other sources handle unresolved games (e.g. `unresolved:source:...` markers).
5. `bundle page has an item with no slug/name` - find where raised; see whether it should be skipped.

Also check existing tests for these modules (tests/ dir, fixtures in tests/fixtures/) and any README (src/game_collections/sources/README.md, sources/dekudeals README) documenting behavior. Report concisely: for each error the raise location, the surrounding logic, and tests that cover it. Do not edit anything.