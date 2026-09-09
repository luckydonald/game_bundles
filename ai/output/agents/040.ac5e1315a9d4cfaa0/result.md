## Findings

**1. `pyproject.toml`** (`/home/user/git/luckydonald/game_collections/pyproject.toml`)
- Standard `hatchling` build backend, no `[tool.uv]` section at all (so it's a plain PEP 621 project, uv is just used as the dev/run tool via `uv sync` / `uv run`, not declared as a uv-specific workspace).
- Entry point:
```toml
[project.scripts]
game-collections = "game_collections.cli:app"
```
- `[tool.hatch.build.targets.wheel] packages = ["src/game_collections"]` — normal src-layout installable package. Nothing here customizes shell-completion behavior; the console script `game-collections` is generated the standard way (a `.venv/bin/game-collections` shim calling `game_collections.cli:app`), confirmed to exist: `.venv/bin/game-collections` is present.

**2. README / docs** (`/home/user/git/luckydonald/game_collections/README.md`)
- `## Setup` section (lines 24-32) only documents:
```
uv sync --extra test
uv run game-collections validate
uv run pytest
```
  and further usage examples all use `uv run game-collections ...` (lines 37-43). There is **no mention anywhere** of PATH setup, adding `.venv/bin` to PATH, or shell completion / `--install-completion`. `docs/README.md`, `AGENTS.md`, `CLAUDE.md` also have no hits for "completion"/"PATH"/"install" in this context (only an unrelated mention of "IDE completion and diagnostics" for the JSON Schema at line 22). So the README exclusively teaches users to invoke via `uv run game-collections`, never a bare `game-collections` on PATH — which is exactly the setup that breaks Typer's default completion install.

**3. `src/game_collections/cli.py`**
- Typer app construction (line 104-106):
```python
app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
scrape_app = typer.Typer(no_args_is_help=True)
app.add_typer(scrape_app, name="scrape")
```
  No `name=` is passed to `typer.Typer(...)`.
- Entry point (lines 1601-1602):
```python
if __name__ == "__main__":
    app()
```
  `app()` is called with no `prog_name` override, and there's no custom `--install-completion`/`--show-completion` handling anywhere — it's purely Typer/Click's built-in mechanism. Since no explicit program name is configured, Click derives the completion program name from `sys.argv[0]`'s basename at runtime. When invoked as `.venv/bin/game-collections` (which is what the `[project.scripts]` shim is, and what `uv run game-collections` ultimately execs), `sys.argv[0]` is that shim path, so Click/Typer registers the bash `complete` function for the literal word `game-collections` — never for `uv` or `uv run game-collections` as a phrase. This is stock Typer/Click behavior, not anything game-collections customizes.

**4. Existing completion-related code**
- No hits for `COMP_WORDS`, `_GAME_COLLECTIONS_COMPLETE`, or any custom `--install-completion` implementation anywhere in `src/` or docs.
- The only repo files matching "completion" are unrelated: `src/game_collections/completion.py` and `tests/test_completion.py`, which implement/​test **game-list ownership completion percentages** (owned vs. missing games in a list) — a domain concept entirely unrelated to shell tab-completion. No confusion risk once you know this, but worth noting it's a red herring when grepping.
- No scripts (`scripts/`) generate or ship a bash/zsh completion file; the completion script referenced in the bug report is the one Typer/Click writes on-the-fly to `~/.bash_completion` (or similar) when `--install-completion` runs — not anything version-controlled in this repo.

**5. `.venv/bin`**
- `.venv/bin/game-collections` exists (confirmed via `ls .venv/bin | grep -i game`), i.e. `uv sync` did create the standard console-script shim; it's just not on the user's `PATH`, which is precisely the mismatch causing the bug: Typer installs completion keyed to the shim's basename (`game-collections`), but the user only ever types `uv run game-collections`, so bash's `complete -F ... game-collections` registration never fires for `uv`.

### Summary of the bug mechanism
Typer's `--install-completion` is untouched stock behavior (Click's `shell_completion` module) invoked via `app()` in `cli.py` with no `prog_name` override. It derives the target command name from `sys.argv[0]` (the `.venv/bin/game-collections` shim from `[project.scripts]` in `pyproject.toml`), and writes a bash `complete -F _game_collections_completion game-collections` registration. Because the README/docs only ever instruct users to run via `uv run game-collections` (venv's `bin/` not on PATH), that registration is dead: bash never resolves the completion function for the `uv` command word, and if the user tries running `game-collections` directly it isn't found on PATH either. There is no existing project code, docs, or scripts addressing this gap — it would need new work (e.g., wrapping installation to target `uv`/`uvx` invocation, or documenting/adding `.venv/bin` to PATH, or a custom completion function keyed off `uv run game-collections`).