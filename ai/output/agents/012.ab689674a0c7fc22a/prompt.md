In repo /home/user/git/luckydonald/game_collections, find where `sync steam` and `apply steam` CLI commands collect/load game lists before building the plan.

Look at:
- src/game_collections/cli.py — the `sync` and `apply` command functions
- src/game_collections/lists.py — the list discovery/loading functions used
- src/game_collections/apply/tui.py — how the TUI loads lists and whether it has any progress bar already (Textual has ProgressBar widget)
- src/game_collections/launchers/steam/*.py — any ownership-collection loading involved in sync (e.g. local_ownership.py, discovery.py) since that may also be slow

Report: exact file:line locations of the list-loading loop(s) that iterate over many list files, what function is called per iteration, whether any progress/logging already exists there, and how `sync` vs `apply` differ in their loading path. Also note the Textual app structure in tui.py (App class, screens, workers) so we know where a ProgressBar could be added. Keep report under 400 words, focus on facts and line numbers.