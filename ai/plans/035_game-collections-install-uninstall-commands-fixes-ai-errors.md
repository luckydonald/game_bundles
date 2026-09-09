# `game-collections install` / `uninstall` commands (fixes ai/errors/5.txt)

## Context

`ai/errors/5.txt` shows shell tab-completion silently failing: `uv run game-collections --install-completion` registers bash completion for the literal word `game-collections`, but the user only ever runs the tool as `uv run game-collections ...` (the venv's `bin/` isn't on `PATH`), so completion never fires. Verified against the installed toolchain (typer 0.26.8 / click 8.3.3): Typer here uses its own old Click-7-style completion protocol (`_GAME_COLLECTIONS_COMPLETE=complete_bash`/`complete_zsh`), and `--install-completion` unconditionally appends to `~/.bashrc`/`~/.zshrc` with no rc.d awareness or real idempotency.

Rather than a doc-only fix, the user wants this solved properly as two new first-class CLI commands: `game-collections install` (get a real `game-collections` binary on `PATH` via `uv tool install`, plus working bash/zsh completion for both `game-collections ...` and `uv run game-collections ...`) and `game-collections uninstall`/`deinstall` (symmetric cleanup). Decisions already made with the user (not open for re-litigation): rc files are auto-edited (idempotently); repo root is detected via `git rev-parse --show-toplevel` at install time; source (PyPI vs. editable git checkout) is chosen by semver comparison, preferring whichever is newer; uninstall always cleans up the completion/rc wiring, and separately *asks* (does not assume) whether to also `uv tool uninstall` the package.

## New dependency

Add `packaging>=25,<27` to `pyproject.toml`'s `[project.dependencies]` (currently only a transitive dep in `uv.lock`, needed directly for `packaging.version.Version` semver comparison). Do **not** add `platformdirs` — this feature is bash/zsh-only by design, and a plain `~/.config/game-collections/` (matching git/npm/cargo/uv convention on Linux and macOS) keeps the new modules trivially testable via an injectable `home: Path` without wrapping a resolver whose behavior differs only for platforms out of scope here.

## `src/game_collections/git_ops.py`: add `repository_root()`

New function following the existing `_run()`-wrapper style (see `head()` at git_ops.py:33-36 for the pattern):

```python
def repository_root(start: Path) -> Path:
    """Return the top-level directory of the git repository containing `start`."""
```

Runs `git rev-parse --show-toplevel` with `cwd=start`; on nonzero exit raises the existing `GitAutocommitError` (reused rather than inventing a new exception type — it's already this module's "a git operation failed, human needs to see it" signal).

## New package: `src/game_collections/install/`

Both new modules live under this package (`src/game_collections/install/__init__.py`, empty), keeping the two install/uninstall concerns grouped together rather than loose in the top-level `src/game_collections/` namespace: `src/game_collections/install/tool_install.py` and `src/game_collections/install/shell_completion.py`. `cli.py` imports them as `from game_collections.install import shell_completion, tool_install`.

### `src/game_collections/install/tool_install.py`

Owns PyPI-vs-local version comparison and the `uv tool install`/`uv tool uninstall` subprocess boundary:

- `InstallError(RuntimeError)` — module's error type.
- `PyPiInfo` / `PyPiPackageMetadata` (Pydantic `BaseModel`, `model_config = ConfigDict(extra="ignore")`) — read only the `info.version` field from PyPI's JSON API. Deliberately **not** this project's strict `extra="forbid"` convention (used for data this project generates/replaces on disk, e.g. Steam VDF/JSON): PyPI's index payload is large, foreign, and unversioned by us — forbidding extras would break `install` on any unrelated PyPI schema addition. Document that deviation in the model's docstring.
- `local_version(repository_root: Path) -> Version` — reads `pyproject.toml`'s `project.version` via stdlib `tomllib` (Python floor is 3.14, no new TOML dependency needed).
- `fetch_pypi_metadata(package_name, timeout) -> httpx.Response` and `latest_pypi_version(package_name=PACKAGE_NAME, *, timeout=10.0, fetch=fetch_pypi_metadata) -> Version | None` — `httpx` (already a dependency, already used in `launchers/steam/api.py` etc.) queries `https://pypi.org/pypi/{package}/json`; a 404 (package not published yet — the expected case right now) returns `None`. The injectable `fetch` callable is the test seam (mirrors this repo's existing pattern of injectable data sources, e.g. `OwnedAppIdsSource` in the Steam adapter, rather than mocking `httpx` directly).
- `choose_install_source(repository_root, package_name=PACKAGE_NAME) -> Literal["pypi", "editable"]` — `"pypi"` only if PyPI's version is strictly newer than local; `"editable"` covers not-yet-published, equal, or PyPI-behind-local-dev.
- `run_subprocess(args) -> subprocess.CompletedProcess[str]` (default runner) plus `install_uv_tool(repository_root, source, package_name=PACKAGE_NAME, *, runner=run_subprocess)` and `uninstall_uv_tool(package_name=PACKAGE_NAME, *, runner=run_subprocess)` — build and run `uv tool install --force [--editable <root> | <name>]` / `uv tool uninstall <name>`, raising `InstallError` on nonzero exit. `--force` makes `install` idempotent (rerun = upgrade in place). The injectable `runner` is the test seam — no existing generic subprocess helper in this codebase to reuse (`git_ops._run` is git-specific and module-private), so this is new, following the same "small function per operation, explicit error type" shape as `git_ops.py`.

### `src/game_collections/install/shell_completion.py`

Owns shell detection, the two generated completion scripts, and idempotent rc-file wiring/unwiring. Supports **bash and zsh only** (per the user: macOS's non-bash default is zsh; no other shell in scope), detected from `$SHELL`'s basename (`detect_shell`), with an unrecognized shell skipping completion setup with a clear message rather than failing the whole `install`.

- `shell_target(shell, home) -> ShellTarget` (frozen dataclass) resolves per-shell paths: completion script at `~/.config/game-collections/completion.{bash,zsh}`; rc file (`~/.bashrc` / `~/.zshrc`); and an optional rc.d-style directory (`~/.bashrc.d` / `~/.zshrc.d`) + numbered file (`50-game-collections-completion.sh`) used **only if that directory already exists** (never created by us — we don't invent a dotfile-framework convention the user's setup doesn't already have).
- `bash_completion_script()` / `zsh_completion_script()` — generated script bodies built on Typer's own already-verified `_GAME_COLLECTIONS_COMPLETE=complete_bash`/`complete_zsh` protocol (not a private Typer internal — this is the same env-var contract `--show-completion` already emits), plus a layer that dispatches `uv run game-collections <TAB>` to the same completion function by rewriting `COMP_WORDS`/`COMP_CWORD` (bash) or `words`/`CURRENT` (zsh) to drop the leading `uv run`, while chaining to any pre-existing `uv` completion function for every other `uv ...` invocation so `uv sync`/`uv add`/etc. completion isn't broken. (Known limitation, to surface in `install`'s output text: this chaining only sees a `uv` completion function that was already registered *before* our script is sourced, and zsh's `_uv` may be a lazy-autoloaded stub at that point — degrades gracefully to default completion for plain `uv` in that case, never breaks anything.)
- `write_completion_script(target) -> Path` — writes the generated script (creates parent dir).
- `install_rc_hook(target) -> Path` — idempotent: writes the rc.d file if that directory exists, else appends a `# game-collections completion (managed by game-collections install)` … `# end game-collections completion` marked block to the rc file (only if the marker isn't already present).
- `remove_completion(shell, home) -> list[Path]` — deletes the completion script and rc.d file if present, and strips the marked block out of the rc file if present, returning the paths actually touched (empty list if nothing was installed — a safe no-op, not an error).

## `src/game_collections/cli.py`

Thin wrappers only (per this repo's own convention of pushing logic into dedicated modules, e.g. `scrape` commands delegating to `git_ops.py`/source packages — nothing new inlined into cli.py itself):

- `install_command` (`@app.command("install")`): resolves `repository_root` via `git_ops.repository_root(Path.cwd())`, picks `source` via `tool_install.choose_install_source` (overridable with `--source pypi|editable`), runs `tool_install.install_uv_tool`, echoes the result; unless `--skip-completion`, detects the shell (overridable with `--shell`), writes the completion script and rc hook via `shell_completion`, and echoes the paths touched plus a "restart your shell" note. Catches `(OSError, ValueError, RuntimeError, git_ops.GitAutocommitError, tool_install.InstallError)`, echoes `str(error)` to stderr, `raise typer.Exit(1) from error` — matching this file's existing error-handling convention throughout (e.g. cli.py's other commands).
- `uninstall_command`: stacked `@app.command("uninstall")` / `@app.command("deinstall")` on one function (both names route through identical behavior — verify via a `--help` smoke test in each name, since stacking isn't used elsewhere in this file). Removes completion/rc wiring via `shell_completion.remove_completion`, echoing each path removed, then `typer.confirm("Also run \`uv tool uninstall game-collections\`?", default=False)` (mirrors the existing confirm-gated pattern at `_confirm_unverified_ownership`, cli.py:1121) before calling `tool_install.uninstall_uv_tool`.

Every new function body closes each indentation level with a bare `# end if`/`# end for`/`# end def <name>`/`# end class <Name>` comment (never repeating the function/class name after `# end def`/`# end class` themselves per project convention), uses complete type annotations throughout, and introduces no `_`-prefixed names.

## `pyproject.toml`

Add `packaging>=25,<27` to `[project.dependencies]`.

## `README.md`

In `## Setup`, after the existing `uv sync` / `uv run game-collections validate` / `uv run pytest` block, add a short paragraph recommending `uv run game-collections install` once to get a real `game-collections` binary on `PATH` (editable against the checkout unless a newer PyPI release exists) plus bash/zsh completion for both plain and `uv run`-prefixed invocation, and mention `game-collections uninstall` (alias `deinstall`) for symmetric cleanup.

## Tests

- `tests/test_git_ops.py` (extend, reusing its existing `_init_repo` tmp_path-git-repo helper): `repository_root` resolves the toplevel from a nested cwd, and raises `GitAutocommitError` outside a repo.
- `tests/test_tool_install.py` (new, flat — matches this repo's existing test layout, which has no subpackages, e.g. `test_git_ops.py`/`test_cli.py` sit directly under `tests/` regardless of their source module's nesting): `local_version` reads `pyproject.toml` correctly and raises `InstallError` on a missing/malformed file; `latest_pypi_version` returns `None` on a stubbed 404, parses `info.version` from a stubbed 200 (including an extra unrelated field, to confirm `extra="ignore"` doesn't break), and raises `InstallError` on a malformed payload — all via the injectable `fetch` callable, no real network; `choose_install_source` prefers PyPI only when strictly newer (monkeypatching `local_version`/`latest_pypi_version`); `install_uv_tool`/`uninstall_uv_tool` build the exact expected `uv` argv (via an injected `runner` stub) for both the PyPI and editable branches, and raise `InstallError` on nonzero exit — no real `uv tool install`/`uninstall` ever runs in tests.
- `tests/test_shell_completion.py` (new): `detect_shell` classifies `bash`/`zsh` by `$SHELL` basename and returns `None` otherwise; `write_completion_script` produces bash/zsh files containing the expected `_GAME_COLLECTIONS_COMPLETE=...` markers; `install_rc_hook` prefers an existing rc.d directory over editing the rc file, appends a marked block when no rc.d dir exists (creating the rc file if missing), and is idempotent on a second call (no duplicate marker) — for both bash and zsh; `remove_completion` deletes the script/rc.d file and strips only the marked block from a rc file that has unrelated surrounding content, and is a safe no-op when nothing was installed. All of these use a `tmp_path`-based fake `home`, matching `test_git_ops.py`'s "real throwaway filesystem tree, no mocking of the OS" convention — the real `~/.bashrc`/`~/.zshrc`/`~/.config` are never touched.
- `tests/test_cli.py` (extend, using `typer.testing.CliRunner` per this file's existing convention, `monkeypatch.setattr(Path, "home", lambda: tmp_path)` scoped per test): `install` calls through to `tool_install`/`shell_completion` (monkeypatched) and echoes the completion path; `--skip-completion` skips shell setup; an explicit invalid `--shell` value is rejected via `typer.BadParameter`; git-root and PyPI/uv-tool errors are caught and surfaced as `typer.Exit(1)` with the error text on stderr; `uninstall`/`deinstall` remove completion wiring and, per `input="n\n"`/`"y\n"`, decline or run `tool_install.uninstall_uv_tool` (monkeypatched) accordingly; a `--help` smoke test confirms the `deinstall` alias works identically to `uninstall`.

## Verification

- `env UV_CACHE_DIR=/tmp/uv-cache uv sync --extra test` (picks up the new `packaging` dependency).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/test_git_ops.py tests/test_tool_install.py tests/test_shell_completion.py tests/test_cli.py -q`.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` (full suite, no regressions).
- Manual smoke test (not automatable): in a real bash and a real zsh session, run `uv run game-collections install`, confirm a `game-collections` binary appears on `PATH`, that plain `game-collections <TAB>` and `uv run game-collections <TAB>` both offer real subcommand completion, and that unrelated `uv <TAB>` completion (e.g. `uv sync`) still works if it did before. Then run `game-collections uninstall` and confirm the rc file / completion script are cleaned up as expected, declining the `uv tool uninstall` prompt first, then re-running and accepting it.
