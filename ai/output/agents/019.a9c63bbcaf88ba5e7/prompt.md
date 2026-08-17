In this repo (game_collections), I need to understand two related things in the `apply steam` TUI picker and the `sync steam` CLI:

A) Filter settings persistence: `apply steam` currently saves selections to `config/apply-selection.yml` (see `src/game_collections/apply/config.py` for the `ApplySelection` Pydantic model, and `src/game_collections/apply/tui.py` for the Textual app). The task is to ALSO persist whatever "filter settings" the TUI has (e.g. any search/filter text box, tier filter, mode filter, unconfigured-handling toggle, etc.) into that same config file when it saves selections.
   - Find where in `tui.py` filters currently exist as in-memory UI state (widget reactive vars, filter inputs, dropdowns) that are NOT currently written to `ApplySelection`.
   - Find where/how `ApplySelection` is currently saved (which function, triggered by what event).
   - Report the current `ApplySelection` model fields and what fields would need to be added to hold filter state.

B) "Unconfigured Handling" naming: search the codebase (CLI code in `src/game_collections/cli.py`, `src/game_collections/apply/`, `src/game_collections/launchers/base.py`, and any Steam sync/plan code) for the term "Unconfigured Handling" or similar (could be a CLI option name, enum, TUI label, or `--mode`/flag). Report:
   - Every file/line where this term or its concept appears (option name, enum values, docstrings, TUI labels).
   - What behavior it actually controls (i.e. what happens for games/collections that aren't covered by any configured list/tier) — read the surrounding code/docstrings to explain the semantics precisely, since a rename requires understanding what it currently means to propose a better name.

Report both parts together, file:line references, under 500 words total. No code changes — read-only investigation.