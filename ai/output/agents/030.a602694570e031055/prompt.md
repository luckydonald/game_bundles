In the repo /home/user/git/luckydonald/game_collections, find the code that extracts "DLC pack" base-game link and bundled-DLC names from Humble Bundle item descriptions (this was added in commit 072398be3 "[humblebundle|parser] dlc packs: Extracted base-game link and bundled-DLC names from Humble 'DLC pack' item descriptions." and split further in commit 1d204c3bf "[humblebundle|greenmangaming|cli] resolver split").

I need to understand:
1. Where is the parsing logic that detects a Humble item is a "DLC pack" and extracts base-game + DLC names from its description? Likely in src/game_collections/sources/humblebundle/parser.py or similar.
2. Where is the resolver logic that takes a parsed game/DLC and searches storefronts (steam) for it — likely in src/game_collections/sources/humblebundle/ resolver, and src/game_collections/search.py or sources/storefronts.py.
3. Specifically, how does the code decide what text/name to search for as a DLC name? Is there some heuristic like "look for text after a certain marker" or "split description by newlines/sentences and treat bullet points as DLC names"?
4. Find the game "Whisper Mountain Outbreak" or similar test fixtures involving DLC packs to understand the description structure.

Report back with:
- Exact file paths and line numbers for the DLC-pack detection function(s) and the resolver call sites.
- The full logic/heuristic used to identify "DLC pack" items and to extract DLC names vs base game name from the description text.
- Any relevant test fixtures showing example input HTML/description text and expected output.
- Your best hypothesis for why a random bullet point of a game's description text ('Survive and fight the horde...') got treated as a DLC name to resolve, given the observed bug (the game itself, 'Whisper Mountain Outbreak', doesn't look like it should be a 'DLC pack' item at all, per the CLI output — the resolve prompt happened right after listing 'Game 7/9: Whisper Mountain Outbreak').

Be thorough — read full functions, not just grep snippets.