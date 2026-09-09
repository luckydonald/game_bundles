Read these two things in /home/user/git/luckydonald/game_collections and report back concisely (quote the relevant code, with line numbers, no more than needed):

1. In src/game_collections/search.py, the "Multiple…" / ChosenNames handling around building `games_out` (mentioned near lines 241-251 in an earlier report) — show the full function it's in, from its start to end.
2. In src/game_collections/models.py, the full `GameList` class definition including `validate_games` (around lines 150-200), and the `Game` model definition (name, ids, group, requires fields) above it.
3. In src/game_collections/sources/humblebundle/resolver.py, the `_resolve_title` method (interleaved variant) and `collect_one_name` usage, to see how it handles the "Multiple" split there — quote it in full.

Keep the report factual and just quote code with file:line references, no analysis needed beyond noting where dedupe/name-collision checks would need to be inserted.