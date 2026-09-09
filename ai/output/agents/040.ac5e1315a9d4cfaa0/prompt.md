In the repo /home/user/git/luckydonald/game_collections, investigate how the `game-collections` CLI is packaged and installed, and how shell completion is set up. I need to understand a bug where `uv run game-collections --install-completion` installs a bash completion script that assumes `game-collections` is a directly-executable command on PATH, but the user only has it available via `uv run game-collections` (i.e. the venv's bin directory is not on PATH). This causes tab-completion to fail with "No such file or directory" (since bash tries to run `game-collections` directly) or fall back to plain filename completion (when the user types `uv run game-collections <TAB>` since bash's `complete` was registered only for the literal command word `game-collections`, not `uv`).

Please report:
1. `pyproject.toml`: the `[project.scripts]` / entry point defining `game-collections`, and whether it's a uv project (`[tool.uv]` section), whether there's `packages`/build-system info suggesting it's installable as a normal console script.
2. Any README or docs sections (root README.md, or docs/) mentioning installation, `uv run`, PATH setup, or shell completion.
3. `src/game_collections/cli.py`: how the Typer app is constructed (app name, entry point function), and whether it uses `typer`'s built-in `--install-completion`/`--show-completion` flags (default click/typer behavior) or something custom.
4. Whether there's any existing completion-related code, docs, or scripts in the repo (search for "completion", "install-completion", "COMP_WORDS", "_GAME_COLLECTIONS_COMPLETE").
5. Check if `.venv/bin` exists and whether `game-collections` binary is present there.

Report back concisely with file paths and relevant excerpts (don't need full file dumps).