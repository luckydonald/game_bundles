In the repo /home/user/git/luckydonald/game_collections, investigate the humblebundle source pipeline under src/game_collections/sources/humblebundle/ (crawler, parser, resolver) and its interaction with src/game_collections/models.py's Game model (name + ids: list[str]).

I need to understand:
1. How does the crawler discover bundle "tiers" and "offers" (games within a tier)? What's the raw data model for an offer (title, subtitle, DLC info if any)?
2. How is an offer's title resolved to a Steam storefront ID? Is there any handling today for an offer title that actually represents a bundle/product with multiple sub-items (e.g. "Dead Cells + The Bad Seed DLC", or "Frostpunk: Game of the Year edition")? Search for any "multi", "compound", "+", "DLC", "bundle" special-casing in the resolver.
3. How does the crawler/writer decide the final list of `Game` entries (name + ids) written to lists/humblebundle/.../*.yml? Where's that logic (writer/common.py render_game_list_yaml)?
4. How are archives structured (archives/humblebundle/...) — is there a place to store "this offer resolved to N storefront items" metadata, or is it strictly 1 offer -> 1 Game with possibly multiple `provider:id` entries already?
5. Are there existing tests demonstrating the current behavior for offers, e.g. tests/fixtures related to humblebundle?

Also check src/game_collections/sources/README.md for documented behavior of this source's pipeline.

Report file paths and line numbers for the key logic, and a concise summary (under 500 words) of exactly how an offer becomes a Game today, and where multi-item support would need to be added.