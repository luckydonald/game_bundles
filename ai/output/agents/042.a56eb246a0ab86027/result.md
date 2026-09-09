## Implementation Plan: `game-collections install` / `uninstall`

### Root-cause recap (verified against the installed toolchain)

I confirmed against `/home/user/git/luckydonald/game_collections/.venv` (typer 0.26.8, click 8.3.3) that Typer does **not** use Click 8's `bash_source`/`zsh_source` protocol here — it vendors its own old-style Click‑7 completion machinery in `typer/_completion_shared.py`:

- Bash: registers `complete -o default -F _game_collections_completion game-collections` where the function shells out with `_GAME_COLLECTIONS_COMPLETE=complete_bash $1`. This is keyed to the literal word `game-collections`, matching exactly what `ai/errors/5.txt` shows.
- Zsh: `eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _GAME_COLLECTIONS_COMPLETE=complete_zsh %(prog_name)s)`.
- `typer --install-completion` writes to `~/.bash_completions/<prog>.sh` / `~/.zfunc/_<prog>` and unconditionally appends to `~/.bashrc`/`~/.zshrc` directly — no rc.d awareness, no idempotency beyond a raw substring check.

So we will **not** rely on `typer --install-completion` at all. We reimplement the two protocols ourselves (they're simple and stable — same `_GAME_COLLECTIONS_COMPLETE=complete_bash`/`complete_zsh` env-var contract Click has kept since v7), and additionally solve the real problem two ways:
1. `uv tool install` puts an actual `game-collections` executable on `PATH`, so the *plain* `game-collections <TAB>` case just works once that binary exists — this is the primary fix.
2. We still add `uv run game-collections <TAB>` dispatch on top, since the user will keep typing that from inside the repo out of habit.

---

### New dependency: `packaging`

Add as an explicit direct dependency (currently only transitive, per `uv.lock` line ~273):

```toml
dependencies = [
    "httpx>=0.28,<1",
    "markdownify>=1.2,<2",
    "packaging>=25,<27",
    "patchright>=1.55,<2",
    "pydantic>=2.12,<3",
    "rapidfuzz>=3.13,<4",
    "PyYAML>=6.0.2,<7",
    "typer>=0.16,<1",
    "vdf>=3.4,<4",
]
```
No `uv.lock` re-resolution risk since it's already locked transitively at a compatible version.

### `platformdirs` decision: do **not** add it

`platformdirs` is also already resolved transitively, so cost would be zero-risk in terms of locking, but I'm recommending against it: this feature is explicitly bash/zsh-only (no Windows ambition per the requirements), and every mainstream dev CLI (git, npm, cargo, uv itself) puts config uniformly under `~/.config/<tool>/` on both Linux and macOS rather than macOS's `~/Library/Application Support`. Using a plain hardcoded `Path.home() / ".config" / "game-collections"` keeps the new module trivially readable and testable (just inject `home: Path`) without wrapping a third-party path resolver that would itself need mocking in tests for zero behavioral difference on our two supported platforms. If Windows/fish support is ever added later, swapping to `platformdirs` then is a small, isolated change.

Chosen paths:
- `~/.config/game-collections/completion.bash`
- `~/.config/game-collections/completion.zsh`

---

### `src/game_collections/git_ops.py` — add `repository_root()`

```python
def repository_root(start: Path) -> Path:
    """Return the top-level directory of the git repository containing `start`."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise GitAutocommitError(
            f"not inside a git repository ({start}): {(result.stderr or result.stdout).strip()}"
        )
    # end if
    return Path(result.stdout.strip())
# end def repository_root
```

Reuses the existing `GitAutocommitError` rather than inventing a new exception type — it's already the module's general "a git operation failed in a way a human needs to see" signal, and `install_command` will catch it the same way other commands catch their domain errors. Flagging this naming as slightly loose (not literally an "autocommit" error) but not worth churn to rename for one new caller.

Test (`tests/test_git_ops.py`): `test_repository_root_returns_toplevel_from_nested_cwd` (build repo under `tmp_path`, call from a subdirectory), `test_repository_root_raises_outside_a_repository` (call with `tmp_path` that isn't a repo).

---

### New module 1: `src/game_collections/tool_install.py`

Owns: local/PyPI version comparison and the `uv tool install`/`uv tool uninstall` subprocess boundary. No `_`-prefixed names anywhere, per this session's constraint.

```python
"""Version comparison against PyPI and the `uv tool install`/`uninstall` boundary
backing the `install`/`uninstall` CLI commands."""

from __future__ import annotations

import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import httpx
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

PACKAGE_NAME = "game-collections"
PYPI_URL_TEMPLATE = "https://pypi.org/pypi/{package}/json"


class InstallError(RuntimeError):
    """Install/uninstall orchestration failed in a way a human needs to see."""

# end class InstallError


class PyPiInfo(BaseModel):
    """The one field of PyPI's `info` object this project reads.

    PyPI's JSON API is a large, third-party-owned payload with many fields
    (`releases`, `urls`, `vulnerabilities`, `last_serial`, ...) this project
    has no stake in. Unlike this project's own strict `StrictModel` contracts
    (see `models.StrictModel`, used for data this project generates or
    replaces on disk), extra fields here are expected and ignored rather
    than treated as format drift.
    """

    model_config = ConfigDict(extra="ignore")

    version: str
# end class PyPiInfo


class PyPiPackageMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    info: PyPiInfo
# end class PyPiPackageMetadata


def local_version(repository_root: Path) -> Version:
    """Read the package version out of `pyproject.toml` at the repo root."""
    pyproject_path = repository_root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        raw_version = data["project"]["version"]
        return Version(raw_version)
    except (OSError, tomllib.TOMLDecodeError, KeyError, InvalidVersion) as error:
        raise InstallError(f"could not read a version from {pyproject_path}: {error}") from error
    # end try
# end def local_version


def fetch_pypi_metadata(package_name: str, timeout: float) -> httpx.Response:
    return httpx.get(PYPI_URL_TEMPLATE.format(package=package_name), timeout=timeout)
# end def fetch_pypi_metadata


def latest_pypi_version(
    package_name: str = PACKAGE_NAME,
    *,
    timeout: float = 10.0,
    fetch: Callable[[str, float], httpx.Response] = fetch_pypi_metadata,
) -> Version | None:
    """Latest published version on PyPI, or None if not published yet (404)."""
    try:
        response = fetch(package_name, timeout)
    except httpx.HTTPError as error:
        raise InstallError(f"could not reach PyPI: {error}") from error
    # end try
    if response.status_code == 404:
        return None
    # end if
    try:
        response.raise_for_status()
        metadata = PyPiPackageMetadata.model_validate(response.json())
        return Version(metadata.info.version)
    except (httpx.HTTPError, ValueError, InvalidVersion) as error:
        raise InstallError(f"PyPI response for {package_name!r} failed or changed format: {error}") from error
    # end try
# end def latest_pypi_version


def choose_install_source(repository_root: Path, package_name: str = PACKAGE_NAME) -> Literal["pypi", "editable"]:
    """PyPI if it has a strictly newer release than the local checkout; editable otherwise
    (covers: not yet published, PyPI equal, or PyPI behind local dev version)."""
    local = local_version(repository_root)
    pypi = latest_pypi_version(package_name)
    if pypi is not None and pypi > local:
        return "pypi"
    # end if
    return "editable"
# end def choose_install_source


def run_subprocess(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True)
# end def run_subprocess


def install_uv_tool(
    repository_root: Path,
    source: Literal["pypi", "editable"],
    package_name: str = PACKAGE_NAME,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_subprocess,
) -> subprocess.CompletedProcess[str]:
    if source == "pypi":
        args = ["uv", "tool", "install", "--force", package_name]
    else:
        args = ["uv", "tool", "install", "--force", "--editable", str(repository_root)]
    # end if
    result = runner(args)
    if result.returncode != 0:
        raise InstallError(f"`{' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
    # end if
    return result
# end def install_uv_tool


def uninstall_uv_tool(
    package_name: str = PACKAGE_NAME,
    *,
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess[str]] = run_subprocess,
) -> subprocess.CompletedProcess[str]:
    args = ["uv", "tool", "uninstall", package_name]
    result = runner(args)
    if result.returncode != 0:
        raise InstallError(f"`{' '.join(args)}` failed: {(result.stderr or result.stdout).strip()}")
    # end if
    return result
# end def uninstall_uv_tool
```

`--force` on install makes rerunning `install` idempotent (upgrades in place instead of erroring "already installed").

**Why not `StrictModel`/`extra="forbid"` for the PyPI payload**: CLAUDE.md's strictness rule targets "structured external data ... where data may be rewritten" — the project's own generated archives/lists and vendor formats it owns replacing (Steam VDF/JSON, `GetOwnedGamesResponse`). PyPI's index JSON is a large, foreign, unversioned-by-us payload where we read exactly one leaf field; `extra="forbid"` would make `install` break on any unrelated PyPI schema addition. This is a deliberate, justified deviation, documented in the model's docstring.

**Test seam note**: following this repo's existing precedent (`SteamApiClient.get_owned_games` itself has no direct network-mocking unit test — `adapter.py` instead takes an injectable `OwnedAppIdsSource` callable and tests inject a fake), `latest_pypi_version` takes an injectable `fetch` callable rather than requiring `httpx` mocking infrastructure that doesn't otherwise exist in this repo.

---

### New module 2: `src/game_collections/shell_completion.py`

Owns: shell detection, completion-script bodies, and idempotent rc-file wiring/unwiring.

```python
"""Bash/zsh completion script generation and rc-file wiring for `install`/`uninstall`.

Only bash and zsh are supported (macOS's non-bash default is zsh; no other
shell is in scope). Detection is by `$SHELL`'s basename only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Shell = Literal["bash", "zsh"]

COMPLETION_CONFIG_DIR = ".config/game-collections"
RC_MARKER_START = "# game-collections completion (managed by game-collections install)"
RC_MARKER_END = "# end game-collections completion"
PROG_NAME = "game-collections"
COMPLETE_VAR = "_GAME_COLLECTIONS_COMPLETE"


def detect_shell(shell_env: str | None) -> Shell | None:
    """Classify `$SHELL`'s basename; anything else is unsupported."""
    if not shell_env:
        return None
    # end if
    name = Path(shell_env).name
    if name in ("bash", "zsh"):
        return name
    # end if
    return None
# end def detect_shell


@dataclass(frozen=True, slots=True)
class ShellTarget:
    shell: Shell
    completion_path: Path
    rc_path: Path
    rc_d_dir: Path
    rc_d_file: Path
# end class ShellTarget


def shell_target(shell: Shell, home: Path) -> ShellTarget:
    config_dir = home / COMPLETION_CONFIG_DIR
    if shell == "bash":
        return ShellTarget(
            shell="bash",
            completion_path=config_dir / "completion.bash",
            rc_path=home / ".bashrc",
            rc_d_dir=home / ".bashrc.d",
            rc_d_file=home / ".bashrc.d" / "50-game-collections-completion.sh",
        )
    # end if
    return ShellTarget(
        shell="zsh",
        completion_path=config_dir / "completion.zsh",
        rc_path=home / ".zshrc",
        rc_d_dir=home / ".zshrc.d",
        rc_d_file=home / ".zshrc.d" / "50-game-collections-completion.sh",
    )
# end def shell_target


def bash_completion_script() -> str: ...  # see script body below
def zsh_completion_script() -> str: ...   # see script body below


def write_completion_script(target: ShellTarget) -> Path:
    """Write the generated script, creating parent dirs. Overwrite-safe/idempotent by content."""
    target.completion_path.parent.mkdir(parents=True, exist_ok=True)
    script = bash_completion_script() if target.shell == "bash" else zsh_completion_script()
    target.completion_path.write_text(script, encoding="utf-8")
    return target.completion_path
# end def write_completion_script


def install_rc_hook(target: ShellTarget) -> Path:
    """Idempotently wire `source <completion_path>` into the shell's rc setup.

    Prefers a conventional `~/.bashrc.d/`/`~/.zshrc.d/` directory if it
    already exists (never created by us — only used if the user's own dotfile
    framework already has one), else appends a marked block to the rc file
    itself, guarded by RC_MARKER_START so re-running `install` never duplicates it.
    """
    if target.rc_d_dir.is_dir():
        target.rc_d_file.write_text(f'source "{target.completion_path}"\n', encoding="utf-8")
        return target.rc_d_file
    # end if
    existing = target.rc_path.read_text(encoding="utf-8") if target.rc_path.is_file() else ""
    if RC_MARKER_START in existing:
        return target.rc_path
    # end if
    block = f'{RC_MARKER_START}\nsource "{target.completion_path}"\n{RC_MARKER_END}\n'
    separator = "" if existing.endswith("\n") or not existing else "\n"
    target.rc_path.write_text(existing + separator + block, encoding="utf-8")
    return target.rc_path
# end def install_rc_hook


def remove_completion(shell: Shell, home: Path) -> list[Path]:
    """Undo write_completion_script + install_rc_hook. Returns paths actually removed/modified."""
    target = shell_target(shell, home)
    changed: list[Path] = []
    if target.completion_path.is_file():
        target.completion_path.unlink()
        changed.append(target.completion_path)
    # end if
    if target.rc_d_file.is_file():
        target.rc_d_file.unlink()
        changed.append(target.rc_d_file)
    # end if
    if target.rc_path.is_file():
        text = target.rc_path.read_text(encoding="utf-8")
        if RC_MARKER_START in text:
            lines = text.splitlines(keepends=True)
            kept = []
            skipping = False
            for line in lines:
                if line.strip() == RC_MARKER_START:
                    skipping = True
                    continue
                # end if
                if skipping and line.strip() == RC_MARKER_END:
                    skipping = False
                    continue
                # end if
                if skipping:
                    continue
                # end if
                kept.append(line)
            # end for
            target.rc_path.write_text("".join(kept), encoding="utf-8")
            changed.append(target.rc_path)
        # end if
    # end if
    return changed
# end def remove_completion
```

#### Generated bash script (`bash_completion_script()` body)

```bash
# game-collections completion (managed by game-collections install)
_game_collections_completion() {
    local IFS=$'\n'
    COMPREPLY=( $( env COMP_WORDS="${COMP_WORDS[*]}" \
                   COMP_CWORD=$COMP_CWORD \
                   _GAME_COLLECTIONS_COMPLETE=complete_bash "$1" ) )
    return 0
}
complete -o default -F _game_collections_completion game-collections

# Dispatch completion for `uv run game-collections ...` without breaking
# uv's own completion for `uv sync`, `uv add`, etc. We capture whatever
# function was already bound to `uv` *at source time* (e.g. from
# `uv generate-shell-completion bash`, if it was sourced earlier in the rc
# file) and delegate to it for every case except `uv run game-collections`.
_game_collections_uv_run_dispatch() {
    if [[ "${COMP_WORDS[1]}" == "run" && "${COMP_WORDS[2]}" == "game-collections" ]]; then
        local -a COMP_WORDS=("${COMP_WORDS[@]:2}")
        local COMP_CWORD=$((COMP_CWORD - 2))
        _game_collections_completion "$1"
        return 0
    fi
    if declare -F _game_collections_uv_orig_completion >/dev/null; then
        _game_collections_uv_orig_completion "$@"
        return $?
    fi
    return 1
}

_game_collections_uv_prior="$(complete -p uv 2>/dev/null | sed -n 's/.*-F \([^ ]*\) uv$/\1/p')"
if [[ -n "$_game_collections_uv_prior" && "$_game_collections_uv_prior" != "_game_collections_uv_run_dispatch" ]]; then
    eval "_game_collections_uv_orig_completion() { \"$_game_collections_uv_prior\" \"\$@\"; }"
fi
unset _game_collections_uv_prior
complete -o default -F _game_collections_uv_run_dispatch uv
# end game-collections completion (script body)
```

#### Generated zsh script (`zsh_completion_script()` body)

```zsh
#compdef game-collections

_game_collections_completion() {
  eval $(env _TYPER_COMPLETE_ARGS="${words[1,$CURRENT]}" _GAME_COLLECTIONS_COMPLETE=complete_zsh game-collections)
}
compdef _game_collections_completion game-collections

# Wrap whatever `_uv` completion function already exists at source time so
# `uv sync`/`uv add`/... keep working; only `uv run game-collections ...`
# is intercepted. NOTE: if `_uv` is still an unautoloaded stub at this point
# (zsh completion functions are commonly autoloaded on first use rather than
# defined eagerly), this copy captures the stub, not the real completer -
# see open risk below.
if (( ${+functions[_uv]} )); then
  functions[_game_collections_uv_orig]=$functions[_uv]
fi

_game_collections_uv_dispatch() {
  if [[ "${words[2]}" == "run" && "${words[3]}" == "game-collections" ]]; then
    local -a words
    words=("${words[@]:2}")
    local CURRENT=$((CURRENT - 2))
    _game_collections_completion
    return
  fi
  if (( ${+functions[_game_collections_uv_orig]} )); then
    _game_collections_uv_orig "$@"
    return
  fi
  _default
}
compdef _game_collections_uv_dispatch uv
```

Both scripts use `_GAME_COLLECTIONS_COMPLETE`/`complete_bash`/`complete_zsh` — the exact env-var protocol Typer's own `--show-completion` already emits (verified above), so it works as-is against the current `typer` version without depending on any private Typer internals.

---

### Open design risks (flagging rather than silently deciding)

1. **Bash `uv` chaining depends on sourcing order.** Our script snapshots `complete -p uv` *at source time*; if the rc file sources our completion block *before* `uv`'s own completion registration line, we capture nothing and silently fall back to default (filename) completion for plain `uv` commands rather than clobbering it — safe, but degrades `uv sync`/`uv add` completion instead of chaining it. `install_rc_hook` always **appends**, so as long as the user's existing `uv` completion setup already precedes the rest of their rc file (typical), this is fine; but it's not guaranteed. Consider echoing an explicit note in `install_command`'s output telling the user to keep any `uv generate-shell-completion` line above ours if they see `uv` completion regress.
2. **Zsh `_uv` autoload timing.** `${+functions[_uv]}` may be false at source time if `_uv` is a lazily-autoloaded completion function not yet loaded (common zsh pattern: a stub file in `fpath`, materialized by `compinit`/first `<TAB>` press). If so, our wrap captures nothing and again just falls back to `_default` for non-`game-collections` `uv` completions — safe but degraded, not broken. This needs manual smoke-testing in a real zsh session; it isn't mechanically verifiable via `CliRunner`.
3. **`uv`'s actual completion registration function name/shape** wasn't verified in this session (no live check of `uv generate-shell-completion bash|zsh` output was run) — the `sed` extraction pattern (`-F <name> uv$`) assumes a single-token function name bound with `-F`, which is standard but should be spot-checked against the installed `uv` version during implementation.
4. **Double `@app.command` aliasing for `uninstall`/`deinstall`** (stacking two `@app.command("...")` decorators on one function) is a supported Click/Typer pattern since the decorator just registers-and-returns, but should get an explicit `--help` smoke test in `tests/test_cli.py` since it's non-obvious that both names route through identical help/behavior.
5. **`--force` on `uv tool install`** was added for install-command idempotency (rerun = reinstall/upgrade in place) — not explicitly requested, flagging as an assumption; if undesired, drop it and let a second `install` run surface uv's own "already installed" message instead.

---

### `src/game_collections/cli.py` additions

Thin wrappers only, per the "don't cram into cli.py" instruction — all real logic lives in the two new modules.

```python
from game_collections import shell_completion, tool_install


@app.command("install")
def install_command(
    source: Annotated[str | None, typer.Option("--source", help="Force 'pypi' or 'editable' instead of auto-detecting from version comparison.")] = None,
    shell: Annotated[str | None, typer.Option("--shell", help="Override detected shell (bash or zsh).")] = None,
    skip_completion: Annotated[bool, typer.Option("--skip-completion", help="Install the tool only; skip shell completion wiring.")] = False,
) -> None:
    """Install a real `game-collections` binary via `uv tool install` and wire up
    bash/zsh completion, including `uv run game-collections` completion."""
    try:
        repository_root = git_ops.repository_root(Path.cwd())
        chosen_source = source or tool_install.choose_install_source(repository_root)
        if chosen_source not in ("pypi", "editable"):
            raise typer.BadParameter("--source must be 'pypi' or 'editable'")
        # end if
        result = tool_install.install_uv_tool(repository_root, chosen_source)
        typer.echo((result.stdout or f"installed ({chosen_source})").strip())
        if skip_completion:
            return
        # end if
        detected_shell = shell or shell_completion.detect_shell(os.environ.get("SHELL"))
        if detected_shell is None:
            typer.echo("Unrecognized shell; skipping completion setup (supported: bash, zsh).", err=True)
            return
        # end if
        target = shell_completion.shell_target(detected_shell, Path.home())
        completion_path = shell_completion.write_completion_script(target)
        rc_path = shell_completion.install_rc_hook(target)
        typer.echo(f"{detected_shell} completion written to {completion_path}, hooked from {rc_path}")
        typer.echo("Restart your shell (or `source` the file above) for completion to take effect.")
    except (OSError, ValueError, RuntimeError, git_ops.GitAutocommitError, tool_install.InstallError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def install_command


@app.command("uninstall")
@app.command("deinstall")
def uninstall_command(
    shell: Annotated[str | None, typer.Option("--shell", help="Override detected shell (bash or zsh).")] = None,
) -> None:
    """Remove game-collections' generated completion wiring, then optionally
    `uv tool uninstall game-collections` after an explicit confirmation."""
    try:
        detected_shell = shell or shell_completion.detect_shell(os.environ.get("SHELL"))
        if detected_shell is None:
            typer.echo("Unrecognized shell; no completion wiring to remove.", err=True)
        else:
            for path in shell_completion.remove_completion(detected_shell, Path.home()):
                typer.echo(f"removed {path}")
            # end for
        # end if
        if typer.confirm("Also run `uv tool uninstall game-collections`?", default=False):
            result = tool_install.uninstall_uv_tool()
            typer.echo((result.stdout or "uninstalled game-collections").strip())
        # end if
    except (OSError, ValueError, RuntimeError, tool_install.InstallError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    # end try
# end def uninstall_command
```

Note: `os` is already imported in `cli.py`.

---

### `README.md` — `## Setup`

Replace the current plain `uv sync`/`uv run` block's implicit "everything via `uv run`" framing with an added `install` step, and drop any lingering `uv tool install --editable .` doc-only guidance (grep found none currently present verbatim, so this is really just adding the new recommendation, not un-writing an old one):

```markdown
## Setup

Python 3.14 or newer and [uv](https://docs.astral.sh/uv/) are required.

```console
uv sync --extra test
uv run game-collections validate
uv run pytest
```

Run `uv run game-collections install` once to get a real `game-collections` binary on
your `PATH` (via `uv tool install`, editable against this checkout unless a newer
release exists on PyPI) plus working bash/zsh tab completion for both `game-collections
...` and `uv run game-collections ...`. `game-collections uninstall` (alias
`deinstall`) removes the completion wiring and optionally the installed tool.
```

---

### Test plan

**`tests/test_git_ops.py`** (extend existing file, reuse `_init_repo`):
- `test_repository_root_returns_toplevel_from_nested_cwd`
- `test_repository_root_raises_outside_a_repository`

**`tests/test_tool_install.py`** (new):
- `test_local_version_reads_pyproject_toml(tmp_path)`
- `test_local_version_raises_install_error_on_missing_file`
- `test_local_version_raises_install_error_on_malformed_toml`
- `test_latest_pypi_version_returns_none_on_404` (inject a `fetch` stub returning a `SimpleNamespace`/minimal fake with `.status_code = 404`)
- `test_latest_pypi_version_parses_version_field` (fake 200 response with `.json()` returning `{"info": {"version": "1.2.3"}, "releases": {...}, "extra_field": "ignored"}` — asserts extra fields don't error)
- `test_latest_pypi_version_raises_install_error_on_malformed_payload` (missing `info`)
- `test_choose_install_source_prefers_pypi_when_strictly_newer` / `..._prefers_editable_when_pypi_not_newer` / `..._prefers_editable_when_pypi_unpublished` (monkeypatch `local_version`/`latest_pypi_version` module functions)
- `test_install_uv_tool_builds_pypi_args` / `..._builds_editable_args_with_repo_path` (inject `runner` stub recording args, assert exact `["uv", "tool", "install", "--force", ...]`)
- `test_install_uv_tool_raises_install_error_on_nonzero_exit`
- `test_uninstall_uv_tool_builds_expected_args` / `...raises_on_failure`

**`tests/test_shell_completion.py`** (new):
- `test_detect_shell_recognizes_bash_and_zsh_by_basename` (`/bin/bash`, `/usr/bin/zsh`)
- `test_detect_shell_returns_none_for_unrecognized_or_empty`
- `test_write_completion_script_creates_bash_and_zsh_files(tmp_path)` (assert content contains `_GAME_COLLECTIONS_COMPLETE=complete_bash` / `complete_zsh` and `game-collections`)
- `test_install_rc_hook_prefers_existing_rc_d_dir(tmp_path)` (pre-create `~/.bashrc.d`, assert a numbered file is written there, `.bashrc` untouched)
- `test_install_rc_hook_appends_marked_block_to_bashrc_when_no_rc_d(tmp_path)`
- `test_install_rc_hook_is_idempotent_on_second_run(tmp_path)` (call twice, assert marker appears exactly once / file content unchanged on second call)
- `test_install_rc_hook_appends_to_missing_rc_file(tmp_path)` (no pre-existing `.bashrc`)
- zsh equivalents of the three rc-hook tests above
- `test_remove_completion_deletes_script_and_rc_d_file(tmp_path)`
- `test_remove_completion_strips_marked_block_from_rc_file_preserving_other_content(tmp_path)` (rc file has unrelated content before/after the block; assert only the block is removed)
- `test_remove_completion_is_a_noop_when_nothing_was_installed(tmp_path)` (returns empty list, no error)

All of the above use `tmp_path` as the injected `home`, matching this repo's `test_git_ops.py` "real throwaway filesystem tree" convention — never touching the real `~/.bashrc`/`~/.zshrc`/`~/.config`.

**`tests/test_cli.py`** (extend):
- `test_install_command_calls_uv_tool_install_and_writes_completion` — monkeypatch `tool_install.install_uv_tool`/`choose_install_source` and `git_ops.repository_root` (point at a throwaway git repo under `tmp_path`), monkeypatch `Path.home` (or pass `--shell bash` and monkeypatch only the home-resolution seam inside `shell_completion` if a CLI-level home override is added — see note below) to a `tmp_path`, assert echoed output mentions the completion path and no real subprocess ran.
- `test_install_command_skip_completion_flag_skips_shell_setup`
- `test_install_command_reports_unrecognized_shell_without_failing` (`--shell bogus` — should fail typer's validation instead? Decide: since `shell` is a free `str | None` Option here, not a Typer `Literal`/`Choice`, `bogus` will reach `detect_shell` indirectly only via `$SHELL` — for an explicit `--shell` override, consider validating early: if `shell` is provided but not in `("bash","zsh")`, raise `typer.BadParameter` rather than silently "unrecognized"; align implementation and test on that.)
- `test_install_command_wraps_git_repository_root_error`
- `test_install_command_wraps_pypi_or_uv_tool_install_error`
- `test_uninstall_command_removes_completion_and_declines_uv_uninstall_by_default` (`input="n\n"`)
- `test_uninstall_command_runs_uv_tool_uninstall_when_confirmed` (`input="y\n"`, monkeypatch `tool_install.uninstall_uv_tool`)
- `test_deinstall_alias_behaves_identically_to_uninstall` (`CliRunner().invoke(app, ["deinstall", "--help"])` and one behavioral case)

**Home-path injection seam for cli.py tests**: `install_command`/`uninstall_command` currently call `Path.home()` directly per the plan above. To keep tests off the real home directory without monkeypatching `pathlib.Path.home` globally (which is fragile/global), add a hidden `--home` override is overkill for a user-facing CLI; instead, tests should `monkeypatch.setattr(Path, "home", lambda: tmp_path)` scoped to the test — an accepted, standard `pytest`/`monkeypatch` technique and consistent with this repo's `monkeypatch`-heavy `tests/test_cli.py` conventions already in use elsewhere in the file.

---

### Critical Files for Implementation
- /home/user/git/luckydonald/game_collections/src/game_collections/cli.py
- /home/user/git/luckydonald/game_collections/src/game_collections/git_ops.py
- /home/user/git/luckydonald/game_collections/src/game_collections/tool_install.py (new)
- /home/user/git/luckydonald/game_collections/src/game_collections/shell_completion.py (new)
- /home/user/git/luckydonald/game_collections/pyproject.toml
- /home/user/git/luckydonald/game_collections/tests/test_cli.py
- /home/user/git/luckydonald/game_collections/tests/test_git_ops.py
- /home/user/git/luckydonald/game_collections/README.md