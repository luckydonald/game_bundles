In the repo /home/user/git/luckydonald/game_collections, I need to understand two things:

1. `src/game_collections/sources/humblebundle/steamdb.py` — how does it search SteamDB? Find the function(s) that perform a search request (what URL/endpoint is hit, what params, e.g. app-type filtering). I suspect it's not using SteamDB's "global search" endpoint, but something narrower (e.g. only apps, not bundles), so bundle results are missed. Show the exact request-building code (method name, URL, params) with line numbers.

2. `src/game_collections/sources/humblebundle/resolver.py` — how does it use steamdb.py, and how does the overall resolution flow work (game title -> Steam appid/link)?

3. Find where "unresolved" items are handled — search for `unresolved:source:` or similar markers (mentioned in CLAUDE.md as `unresolved:source:isthereanydeal:...`), and find where a user can provide a "custom link" to resolve an item manually. Look in `src/game_collections/completion.py`, `src/game_collections/cli.py`, and `src/game_collections/sources/storefronts.py`. I need to know exactly how custom link input is parsed today — what URL patterns/formats are accepted for Steam (e.g. store.steampowered.com/app/<id>/...), and whether bundle URLs like `https://store.steampowered.com/bundle/46228/Forgive_Me_Father_2_Deluxe_Edition/` are handled or would fail.

4. Find the data model(s) for storefront IDs / links (likely in `src/game_collections/models.py` or `sources/storefronts.py`) — specifically how a Steam ID/link is represented (e.g. `steam:<appid>` format), and whether there's any existing concept of "bundle" as a distinct storefront reference type, or only single games/apps.

Report back with:
- Exact file:line locations and relevant code snippets for each of the above.
- Confirmation of whether SteamDB search currently restricts to non-bundle apps (and how).
- Confirmation of what custom-link parsing currently accepts, and whether it errors on bundle URLs and why (e.g. regex only matches /app/ not /bundle/).
- The current shape of the ID/link data model, including any enums for "kind" of storefront reference.

Be thorough — read full functions, not just grep snippets. This is research only, do not modify anything.