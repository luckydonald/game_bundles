In this Python repo (game_collections), find every place that writes bundle "tier" list files (filenames like tier-1.yml, entire-N-item-bundle.yml, N-item-bundle.yml) for the humblebundle, greenmangaming, isthereanydeal, and dailyindiegame sources under src/game_collections/sources/. For each source, report:
1. The exact file/function that decides the tier filename and the naming convention/logic used (single-tier vs multi-tier case, cumulative tier numbering).
2. Whether tier count/number is stored anywhere in the list's YAML data (the Pydantic model in src/game_collections/models.py) or derived purely from filename.
3. How src/game_collections/launchers/steam/adapter.py (or wherever `--tiers highest/all` logic lives) parses/recognizes tier ordering from filenames — the exact regex or parsing used for `tier-N.yml` and `(entire-)?N-item-bundle.yml`.

Also report the full Pydantic model in models.py (GameList/Game/References etc. field names and types) verbatim, since a new field may need adding.

Report file:line citations for everything so I can jump directly to each location. Be thorough — read full functions, not just grep snippets.