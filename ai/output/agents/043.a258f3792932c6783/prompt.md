In the repo /home/user/git/luckydonald/game_collections, I'm investigating a bug from a scrape session log (ai/errors/5.txt). During `game-collections scrape --git greenmangaming`, the tool interactively resolves game names to steam store IDs. When a search result doesn't match, the user can select "Multiple…" to split one entry into several separate games (prompted "Name of one separate game (blank to finish)"), or "Other…" to paste a raw ID/URL.

After a long interactive session resolving many games in bundles "2k-collection" and "destiny-2-expansion-bundle-2025", the final write failed with:
```
error: 2k-collection: 1 validation error for GameList
  Value error, list contains duplicate game names [...]
error: destiny-2-expansion-bundle-2025: 1 validation error for GameList
  Value error, list contains duplicate game names [...]
```
This happened because when using "Multiple…", the user typed a separate-game name identical to the original game's name (e.g. typed "BioShock: The Collection" again after selecting "Multiple" for "BioShock: The Collection"), or typed a name that already exists elsewhere in the same bundle (e.g. "Destiny 2: The Edge of Fate" was already a separate game entry #8, but was also typed as a sub-name during Multiple resolution for "Destiny 2: Year of Prophecy Edition"). This produces duplicate game names in the final GameList, which fails Pydantic validation only at the very end — after the entire lengthy interactive resolution session — discarding/failing the whole bundle's output despite all the manual work already done.

Please investigate and report back (do not make any edits, this is read-only research):

1. Where is the interactive "Resolve '<name>' on steam:" prompt and the "Multiple…"/"Other…" handling implemented? (likely in src/game_collections/search.py, src/game_collections/cli.py, or a completion/resolver module related to `complete` command / storefront resolution. Search for "Name of one separate game" and "Multiple…" and "Select a result" strings.)
2. Where exactly does the "Multiple" flow collect separate game names and turn them into GameList entries — find the code path from prompt input to constructing Game objects added to the list.
3. Where is "list contains duplicate game names" validator defined (likely in models.py on GameList) — show the validator code.
4. Is validation of the GameList (including duplicate-name check) run only once at the very end after all interactive resolution for a bundle, or is it possible to validate incrementally per-bundle/file write? Find where `scrape greenmangaming` (and shared scrape code) writes files and where GameList(...) validation is invoked relative to the interactive resolve loop.
5. Is there any existing dedupe/collision check when adding a new game name during the "Multiple" flow, or when merging resolved IDs back into the list? 
6. Note any related handling for case where the typed separate-game name matches an EXISTING game already in the list (either the original entry itself, or a different entry) — is this checked anywhere currently?

Report file paths and line numbers, and quote the relevant code (validator, prompt loop, list-building code). Keep the report focused and factual — this is for planning a fix, not implementing one.