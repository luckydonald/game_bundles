# Fix shell completion for `game-collections` (ai/errors/5.txt)

## Context
`ai/errors/5.txt` shows a user running `uv run game-collections --install-completion`, then finding tab-completion broken two ways:
1. Typing `game-collections<TAB>` directly fails (`env: 'game-collections': No such file or directory`) — the completion script Typer/Click installs registers `complete -F ... game-collections`, but `game-collections` isn't a bare command on PATH (only reachable via `uv run game-collections`, since `.venv/bin` isn't on PATH).
2. Typing `uv run game-collections<TAB>` falls back to plain filename completion ("Display all 122 possibilities") since bash's registered completion is keyed to the literal word `game-collections`, not `uv`.

Root cause confirmed via exploration: this is stock Typer/Click `--install-completion` behavior (`src/game_collections/cli.py`, `app = typer.Typer(...)`, `app()` at the bottom with no `prog_name` override) combined with the README's `## Setup` section (lines 24-32) only ever teaching `uv run game-collections ...` — never a PATH-accessible install. No project code needs to change; this is a documentation gap.

User confirmed the fix direction: document `uv tool install --editable .` as the way to get a real `game-collections` binary on PATH, which makes `--install-completion` work normally.

## Change

Update `README.md`'s `## Setup` section to add an optional step, after the existing `uv sync --extra test` / `uv run game-collections validate` block:

- Explain that `uv run game-collections ...` is fine for normal use, but shell tab-completion needs `game-collections` to be a real command on `PATH`.
- Recommend `uv tool install --editable .` (run from the repo root) to install it as a uv-managed tool with a `game-collections` shim in `~/.local/bin` (pointing at the local editable checkout, so it stays in sync with source changes), noting `uv tool ensure-path` / `uv tool update-shims` if `~/.local/bin` isn't already on PATH.
- Note that once that shim is on PATH, `game-collections --install-completion` (no `uv run` prefix) will register correctly, and the user should restart their shell (or `source` the rc file) afterward.

Keep the addition short — a few lines, consistent with the existing terse Setup section style.

## Verification
- Re-read the edited README section to confirm it reads correctly and fits the existing doc style.
- No code changes, so no test suite run is required. If desired, optionally sanity check `uv tool install --editable .` locally to confirm the shim path and `--install-completion` behavior, but this is not required since it's a documentation-only fix.
